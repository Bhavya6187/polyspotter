# Twitter Receipts Visibility — Design

**Date:** 2026-06-11
**Status:** Approved (brainstorm with Bhavya, 2026-06-11)
**Builds on:** `2026-06-04-twitter-accountability-layer-design.md` (Component A, shipped as PR #23)

## Problem

@polyspotter has 73 followers after ~8 weeks and 385 tweets (~0.19 followers/tweet).
Impressions are tiny (<500/tweet per analytics.x.com). The account is broadcast-only
by deliberate choice (follows 2, likes 0, no replies) — confirmed 2026-06-11: Bhavya
ruled out human-in-the-loop reply workflows and paid X API tiers.

The accountability settle loop (Component A) is live and posting, but its output
doesn't *function* as a receipt on X:

- `publish_result.py` posts result tweets **standalone** — no `quote_tweet_id` —
  so the timestamped original call is invisible to anyone seeing the result.
  The proof-of-foresight mechanic, the entire selling point, never renders.
- Flag tweets carry no track record. A first-time viewer has no reason to follow.
- The $20k honesty floor (`RESULT_LOSS_NOTABLE_USD`) overrides the 0.8 win bias:
  the visible settled record is exactly 8-8, a coin flip.
- Component B (scoreboard tweet) and C (weekly leaderboard) remain unbuilt.
- Nothing measures anything: the free API tier 401s on tweet reads, and follower
  count isn't snapshotted, so there is no trend line to steer by.

Since replies/engagement are out of scope by user decision, the only remaining
distribution channel is **content that earns shares on its own** — which means the
receipts must be visible, the track record must be legible, and we must be able to
measure whether it's working.

## Goals

1. Every result tweet visibly proves the original call (quote-tweet linkage).
2. Every flag tweet carries a one-line track record once enough results exist.
3. The publicly settled record trends toward the 0.8 win-bias target instead of 50/50.
4. A weekly scoreboard tweet aggregates the week into one shareable graphic.
5. A free daily follower snapshot gives us a trend line to judge all of this.

## Non-goals

- No reply/engagement automation, no automated likes/follows (user decision + X
  automation rules).
- No paid X API tier; measurement stays within the free tier (`get_me` works;
  tweet reads do not).
- No cadence increase (flag cap stays 2/day, result cap stays `RESULT_DAILY_CAP=2`).
- No overhaul of the flag-tweet template beyond appending the closer line.
- No changes to articlebot or the email digest (digest CTA may come later).

## Delta 1 — Quote-tweet linkage (core fix)

**`storybot/tweet_utils.py` — `post_tweet()`** gains an optional
`quote_tweet_id: str | None = None` keyword, passed through to
`twitter_client.create_tweet(..., quote_tweet_id=...)`. tweepy 4.16.0 supports
this; quoting your own tweet is allowed and works on the free tier.

**`storybot/publish_result.py` — `publish()`** passes
`quote_tweet_id=original_tweet_id`. Everything else (validation, scorecard PNG
attach, `result_tweets` recording, exit codes) is unchanged.

**`storybot/result_pipeline.py` — `SYSTEM_PROMPT_RESULT`** changes because the
quoted tweet is now visible under the result:

- New required lead: sentence 1 opens with the time delta between flag and
  resolution, e.g. *"Flagged 14h before tip-off: Knicks beat the Spurs; the
  cluster was on the Spurs."* The payload gains a `flagged_hours_before` field
  (computed from `tweeted_at` vs. resolution time; fall back to days when > 48h —
  the pipeline already computes `flagged_days_ago` for the scorecard).
- Keep referencing event/team names (search surface) but drop the instruction
  that the reader "should not need to remember the prior tweet" — the quote
  renders it.
- Sentence 2 (plain-English P&L) and all other rules (two sentences, no links,
  no banned phrases, honest losses) are unchanged.

**`storybot/run_result_pipeline_loop.sh`** — the claude-edit prompt gets one
added check: the lead's time delta must match the transcript's
`flagged_hours_before` value.

Failure mode: if X rejects the quote (e.g. original tweet deleted), `post_tweet`
raises, `publish()` returns 1, the draft stays on disk — same handling as any
post failure today. No fallback-to-standalone: a result without its receipt is
the bug this design exists to fix.

## Delta 2 — Track-record closer in flag tweets (light-B)

**`storybot/result_store.py`** gains `recent_record(days: int = 30) -> tuple[int, int]`
returning `(n_cashed, n_burned)` over `result_tweets` rows with
`posted_at >= NOW() - days` (row-level outcomes, not trade-level `n_won/n_lost`).

**`storybot/twitter_pipeline.py`** appends a deterministic closer after the
writer stage, before validation:

- Format: `Recent flags: {cashed}-{burned}.` (~20 chars; shortened from the
  original `Settled flags, last 30d:` wording to raise the attach rate under
  the 280-char budget — the 30d window still applies via `recent_record(days=30)`).
- Only when `cashed + burned >= 10` (sample-size guard) **and**
  `cashed > burned` (don't amplify a losing stretch; the honesty lives in the
  result feed itself, which still posts notable losses).
- The closer is appended programmatically — never composed by the LLM — so the
  number is always exactly what the DB says.
- The closer is appended only when the combined text fits the 280 twitter-counted
  char budget; on a maximal-length draft it is dropped (logged as
  `closer_decision attached=false`) rather than constraining the writer.
  The closer is part of the draft Claude reviews, and the claude-edit prompt
  gains a line: do not alter the closer's numbers.

Honesty caveat (accepted): the closer counts *publicly settled* results, which
are win-biased by design (Delta 3). It is verifiable against the public feed,
which is the standard we hold.

## Delta 3 — Win-bias fix

**`storybot/result_pipeline.py`**: `RESULT_LOSS_NOTABLE_USD` 20000.0 → 50000.0.

Rationale: at $20k nearly every cluster loss qualifies as "notable" (observed
losses were ~$24k), so `select_results`' honesty floor admits losses as fast as
wins and the posted record pins at ~50%. At $50k, routine losses no longer force
their way in, and the running win share converges toward `RESULT_WIN_BIAS=0.8`
while genuinely big losses still always post. No logic changes to
`select_results()` — its existing tests stay green; add one test asserting a
$30k loss is no longer auto-eligible.

## Delta 4 — Weekly scoreboard tweet (Component B)

Runs inside the existing hourly result loop — no new daemon.

**`storybot/result_pipeline.py`** (new step at end of run):

- Trigger window: Sunday 17:00–22:00 ET (evening peak), at most once per ISO week.
- Dedup: new Postgres table `weekly_scoreboards(iso_week TEXT PRIMARY KEY,
  tweet_id TEXT, n_cashed INT, n_burned INT, net_pl_usd NUMERIC, posted_at
  TIMESTAMPTZ)` via `result_store`; skip if this week's row exists.
- Data: aggregate `result_tweets` for the trailing 7 days — rows cashed/burned,
  total net P&L. Skip (log, no row) if fewer than 3 settled results that week.
- Graphic: new `charts.py` renderer `render_weekly_scoreboard(...)` modeled on
  `render_result_scorecard` — verdict-style W-L, net P&L, "week of <date>",
  PolySpotter branding.
- Text: deterministic template, no LLM: `This week's settled flags: {W}-{L},
  net {±$Xk}. Every result quote-tweets the original call.` Validated by
  `validate_tweet` like everything else.
- The weekly tweet does NOT count against `RESULT_DAILY_CAP` (it summarizes,
  it doesn't settle) and is posted directly by the pipeline (deterministic text
  → no claude-edit hop needed).

## Delta 5 — Free follower tracking

- New Postgres table `follower_snapshots(snapshot_date DATE PRIMARY KEY,
  followers_count INT, tweet_count INT, created_at TIMESTAMPTZ DEFAULT NOW())`
  via `result_store`.
- At the start of each result-pipeline run: if no row for today's ET date,
  call `client.get_me(user_fields=["public_metrics"])` and insert
  (`ON CONFLICT DO NOTHING`). At most ~1 call/day, far under the free-tier
  `users/me` rate limit. `get_me` failure is logged and non-fatal — the run
  continues.
- Read-out: simple query for now (`SELECT * FROM follower_snapshots ORDER BY
  snapshot_date`); no dashboard in this phase.

## One-time manual actions (Bhavya, no recurring commitment)

1. Follow ~50 relevant accounts from @polyspotter (Polymarket official, prediction
   market analysts, sports-betting data accounts). An account following 2 people
   reads as spam to both the algorithm and humans.
2. Once a strong receipt quote-tweet exists, pin it to the profile.

## Data model changes (all Postgres, via `result_store`)

| Table | Change |
|---|---|
| `weekly_scoreboards` | new (iso_week PK, tweet_id, n_cashed, n_burned, net_pl_usd, posted_at) |
| `follower_snapshots` | new (snapshot_date PK, followers_count, tweet_count, created_at) |
| `result_tweets` | unchanged |

Tables are created idempotently (`CREATE TABLE IF NOT EXISTS`) by `result_store`
at import, matching how `result_tweets` was applied.

## Testing

- `post_tweet` passes `quote_tweet_id` through to `create_tweet` (mocked client);
  omitted when None.
- `publish_result.publish()` passes the original tweet id as `quote_tweet_id`.
- Closer line: built from a mocked `recent_record`; suppressed below 10 settled
  or when burned ≥ cashed; final text passes `validate_tweet`.
- `select_results`: $30k loss not eligible at the new floor; ≥$50k loss still is.
- Weekly scoreboard: window/ISO-week dedup logic (pure function over a passed-in
  `now`), <3-results skip, aggregate math.
- Follower snapshot: insert-once-per-day idempotence (mocked `get_me`).
- Full suites stay green: `pytest` (root) and `cd backend && pytest`.

## Success criteria

- Result tweets render as quote-tweets of the original flagged call.
- Within ~3 weeks of settles at the new floor, the public settled record sits
  visibly above 50% wins.
- `follower_snapshots` accumulates a daily series; review the trend after 2 weeks
  to judge whether receipts visibility moved follows (and decide on next levers,
  e.g. digest CTA or template variety).

## Rollout

Ship behind nothing — these are small deltas to a live loop. Sequence:
Delta 5 (measurement first), then 1, 3, 2, 4. Restart the `results` screen
session after merge; the `twitter_pipeline` session restart picks up Delta 2.
