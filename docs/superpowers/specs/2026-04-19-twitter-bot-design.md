# Twitter Bot — Design

**Date:** 2026-04-19
**Status:** Approved, pending implementation plan

## Goal

An autonomous bot that runs hourly, reviews recent PolySpotter alerts, and posts a single engaging tweet to X (Twitter) when there's something worth saying — driving traffic to the PolySpotter website via a "link in bio" CTA (no URLs in tweets themselves, since the X API tier that enables link tweets is cost-prohibitive).

## Non-goals

- Not a long-running service. One pass per invocation, exits when done.
- No Twitter replies, DMs, quote-tweets, threading, or engagement loops.
- No URLs in tweet bodies.
- No automated handling of Twitter rate limits beyond logging and skipping the hour.

## Architecture

### Deployment

- Runs as a second Railway service on the existing `polybot` repo.
- Start command: `python backend/twitter_bot.py`.
- Cron schedule: `0 * * * *` (top of every hour).
- Reuses the existing Postgres database (`DATABASE_URL`) and Azure OpenAI credentials already configured for the main backend.

### File layout

All bot logic lives in a single file per user preference.

| Path | Purpose |
|---|---|
| `backend/twitter_bot.py` | Single file containing: entry point (`main()`), API fetch, dedup filter, LLM composer (`decide_and_compose()`), Twitter client helpers (`post_tweet()`), DB recording, config loading. |
| `backend/test_twitter_bot.py` | Pytest test suite, follows conventions of existing `test_endpoints.py`. Uses injected fakes for API / LLM / Twitter / DB. |
| `backend/schema.sql` | Appended with the `tweeted_alerts` table definition. |
| `backend/requirements.txt` | Adds `tweepy>=4.14`. |

Module functions accept injectable dependencies (e.g., `llm_client`, `twitter_client`, `db_conn`) so tests can substitute fakes without monkey-patching.

### Environment variables

Already in `.env` locally; must also be set in the Railway bot service:

| Var | Purpose |
|---|---|
| `X_CONSUMER_KEY` | OAuth 1.0a consumer key |
| `X_CONSUMER_KEY_SECRET` | OAuth 1.0a consumer secret |
| `X_ACCESS_TOKEN` | OAuth 1.0a access token |
| `X_ACCESS_TOKEN_SECRET` | OAuth 1.0a access token secret |
| `DATABASE_URL` | Existing Postgres connection string |
| `AZURE_OPENAI_*` | Existing variables already used by `llm_filter.py` |
| `POLYSPOTTER_API_URL` | Default `https://api.polyspotter.com` |
| `TWITTER_BOT_MIN_SCORE` | Default `5.0` — minimum `composite_score` to consider (7c) |
| `TWITTER_BOT_DRY_RUN` | Default `false` — when `true`, logs tweet text instead of posting, skips DB recording |

## Data flow

Per invocation:

1. **Fetch candidates.** GET `{POLYSPOTTER_API_URL}/api/alerts?per_page=100&min_score={TWITTER_BOT_MIN_SCORE}`. Response is sorted by `created_at DESC`. Client-side filter to alerts with `created_at` within the last **65 minutes** (60 + 5-min slack for cron drift).

2. **Apply dedup filter.** Drop any candidate whose `id` already exists in `tweeted_alerts`. Also drop any candidate whose `(wallet, condition_id)` pair was tweeted within the last 24 hours.

3. **Score-sort and take top 5.** By `composite_score DESC`.

4. **Short-circuit on empty.** If 0 candidates remain, log `event=no_candidates`, exit 0.

5. **LLM call.** One call to GPT-5.4 via the existing Azure OpenAI client wiring used by `llm_filter.py`. Temperature `0.7`. JSON-mode structured output (see schema below).

6. **Short-circuit on skip.** If LLM returns `decision=skip`, log `event=llm_skip` with reason, exit 0.

7. **Validate tweet.**
   - `alert_ids` is a non-empty list and every id appears in the 5 alerts sent to the LLM.
   - If `is_composite == false`, `alert_ids` length must be 1.
   - `tweet` length ≤ 260 characters.
   - **Length retry:** if tweet > 260 chars, send a single follow-up LLM call with the over-length tweet and message: *"Your tweet was N characters, must be ≤260. Shorten it, keep the hook and CTA."* If the retry also fails the length check, log `event=validation_error`, exit 1.
   - Other validation failures (`alert_ids` not in input, empty `alert_ids`, etc.) do **not** retry — log `event=validation_error`, exit 1.

8. **Post to X.** `tweepy.Client.create_tweet(text=tweet)`. On exception (rate limit, auth, duplicate content, etc.), log `event=post_error` with status/reason, exit 1. No retries (per 7b=A).

9. **Record.** On successful post, insert one row into `tweeted_alerts` per `alert_id` in `alert_ids`, all sharing the same `tweet_id` and `tweet_text`. If the DB insert fails after a successful post, log `event=record_error` but exit 0 (tweet is already live; the worst case is one duplicate next hour).

### Dry-run mode

When `TWITTER_BOT_DRY_RUN=true`, step 8 logs the tweet text and is treated as successful. Step 9 is skipped — dry runs must not poison dedup state for real runs.

## Dedup table

Appended to `backend/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS tweeted_alerts (
    alert_id       TEXT PRIMARY KEY,
    wallet         TEXT NOT NULL,
    condition_id   TEXT NOT NULL,
    tweet_id       TEXT NOT NULL,
    tweet_text     TEXT NOT NULL,
    tweeted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweeted_alerts_wallet_market
    ON tweeted_alerts (wallet, condition_id, tweeted_at DESC);
```

The bot also runs this SQL idempotently at startup (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`) so the first production run provisions the table without requiring a manual migration step.

## LLM prompt

### System prompt (key content)

> You are the social media voice for PolySpotter, a service that surfaces notable Polymarket bets from sharp wallets, whales, and coordinated flow. You'll be given up to 5 alerts from the last hour. Your job: write ONE tweet that's as engaging as possible, drawing on **one or multiple** of the alerts, or skip the hour if nothing is compelling.
>
> **Single vs. composite:**
> - If one alert clearly stands out, write a tight hook-driven tweet focused on it.
> - If 2+ alerts tell a bigger story together (same market, same wallet across markets, a theme like "3 whales all loaded up on Iran markets today"), compose a synthesis tweet that's more interesting than any single alert.
> - Never force synthesis — if the alerts are unrelated, just pick the best one.
>
> **Tweet rules:**
> - ≤ 260 characters (safety margin under X's 280 limit).
> - Hook-driven opening: lead with the most striking fact (dollar amount, win rate, timing).
> - Use specific numbers, not vague descriptors.
> - End with a CTA that drives clicks to bio: e.g., `"→ link in bio"`, `"full details in bio 👀"`, `"who is this wallet? bio link"`.
> - 1–2 relevant hashtags max. Prefer topic-specific (`#Election2024`, `#Iran`) over generic (`#Polymarket`).
> - 0–2 emojis, only if they add something. No emoji spam.
> - No URLs. No `@mentions` of real users (we can't verify them).
> - Never fabricate numbers or facts not in the alert data.
> - Write like a sharp trading desk analyst, not a corporate account.
>
> **Skip criteria:** if all 5 alerts are routine/low-signal, return `decision=skip` with a short reason.

### User-message payload

Compact JSON with the 5 candidate alerts. Each alert includes:

- `alert_id`
- `composite_score`
- `llm_headline`
- `llm_summary`
- `market_title`
- `wallet`
- `wallet_win_rate`
- `wallet_total_pnl`
- `signal_strategies` (list of strategy names that fired)
- `trade_usd_size`

### Structured output schema (JSON mode, strict)

```json
{
  "decision": "post" | "skip",
  "reason": "short string explaining the choice",
  "alert_ids": ["<id>", "..."] | null,
  "tweet": "<string ≤260 chars | null>",
  "is_composite": true | false
}
```

## Error handling

Matches user choice **7b=A** (log and skip the hour, no retries), with the one targeted exception of the length retry.

| Failure | Behavior |
|---|---|
| API fetch fails (network / 5xx) | Log `event=fetch_error`, exit 1 |
| LLM call fails or returns invalid JSON | Log `event=llm_error`, exit 1 |
| LLM returns `decision=post` but `tweet` > 260 chars | Retry once with "shorten it" follow-up. If retry also > 260, log `event=validation_error`, exit 1 |
| LLM returns `alert_ids` not in the input 5, or empty, or violates `is_composite` invariant | Log `event=validation_error`, exit 1 |
| Twitter `create_tweet` raises (rate limit, auth, duplicate, etc.) | Log `event=post_error` with status/reason, exit 1 |
| DB insert fails after successful post | Log `event=record_error`, exit 0 |

## Logging

Structured single-line JSON to stdout (Railway captures stdout). Every run emits:

- One `run_start` line with run id and timestamp.
- One `run_end` line with counts: `candidates_fetched`, `after_dedup`, `llm_decision`, `posted` (bool), `tweet_id` (if posted).
- Event lines at each decision point: `no_candidates`, `llm_skip`, `llm_error`, `validation_error`, `post_error`, `record_error`, `dry_run_tweet`.

## Testing

`backend/test_twitter_bot.py` — pytest style matching `test_endpoints.py` conventions. Functions take injected fakes; no monkey-patching. Cases:

1. Empty candidate list → exits cleanly, no LLM call, no post.
2. All candidates below `min_score` → filtered out, no LLM call.
3. Dedup: candidate with `alert_id` already in `tweeted_alerts` is dropped.
4. Dedup: candidate whose `(wallet, condition_id)` was tweeted <24h ago is dropped.
5. Dedup: same `(wallet, condition_id)` tweeted >24h ago is *not* dropped.
6. LLM returns `skip` → no post, no DB write.
7. LLM returns single-alert `post` → posts, writes one `tweeted_alerts` row.
8. LLM returns composite `post` with 3 `alert_ids` → posts, writes 3 rows, all sharing the same `tweet_id` and `tweet_text`.
9. LLM returns `alert_id` not in the input 5 → validation fails (no retry), no post.
10. LLM returns tweet > 260 chars, retry returns valid shorter tweet → posts successfully.
10b. LLM returns tweet > 260 chars, retry also > 260 chars → validation fails, no post.
11. Twitter raises → logged, no DB write.
12. Dry-run mode → logs tweet text, does not call Twitter, does not write DB.

## Open questions

None remaining — all design decisions locked with user in brainstorming session.
