# Twitter Pipeline Bot — 4-Stage LLM Composition

**Date:** 2026-04-26
**Status:** Spec

## Problem

[storybot/twitter_simple.py](../../../storybot/twitter_simple.py) collapses three distinct decisions into a single LLM call: (a) which alerts to tweet about, (b) which chart to ship, and (c) the tweet text. The model sees 20 compact alerts and emits one JSON blob with `decision`, `alert_ids`, `chart_type`, and `tweet`.

Splitting these into discrete stages buys two things:
1. **Focused inputs.** The chart picker and writer can see a small, rich bundle for the chosen event instead of skimming 20 alerts.
2. **Cheaper iteration on prompts.** Each stage's prompt is shorter and addresses one job, so tuning one stage doesn't cascade.

This spec describes a new bot, **`twitter_pipeline.py`**, that lives alongside `twitter_simple.py` (not a replacement) and runs a 4-stage pipeline: 3 LLM calls + 1 deterministic data fetch.

## Out of scope

- Replacing `twitter_simple.py`. Both bots coexist; cron schedules and feature comparison are the user's call.
- Changing the seed-alert pipeline (`fetch_seed_alerts`), the chart renderers in `charts.py`, or the `tweeted_alerts` dedup model.
- Tool-driven research agents (rejected as option A for stage 2 — see Decisions below).
- New chart types. Existing five (`price_sparkline`, `volume_bar`, `wallet_record_card`, `cluster_card`, `none`) are unchanged.

## Pipeline shape

```
fetch_seed_alerts()  →  filter_posted_alerts
        │
        ▼
  ┌─────────────┐    decision: "skip"  ┐
  │ Stage 1 LLM │ ───────────────────  │  end run (exit 0)
  │ event picker│                      │
  └─────────────┘                      ┘
        │ decision: "post"
        │ alert_ids, event_summary
        ▼
  ┌─────────────────┐
  │ Stage 2 (det.)  │  trades + token_map + facts_bundle
  │ data fetcher    │
  └─────────────────┘
        │
        ▼
  ┌─────────────┐
  │ Stage 3 LLM │   chart_type, hook_anchor
  │ chart picker│
  └─────────────┘
        │
        ▼
  ┌─────────────┐
  │ Stage 4 LLM │   tweet text (retry once on validation failure)
  │  writer     │
  └─────────────┘
        │
        ▼
   render chart  →  post to X  →  record_tweet
```

All four stages run sequentially. Skip can only originate from stage 1 — once stage 1 commits to `decision: "post"`, the writer cannot abort.

## Stage contracts

### Stage 1 — event picker (LLM)

**Purpose:** Look at the top alerts and pick a single event-cluster worth tweeting about, or skip.

**Input:** Up to 20 compact alerts produced by `_compact_alert_for_picker` (existing helper in `bot_utils.py`).

**Output (strict JSON):**
```jsonc
// skip
{ "decision": "skip", "reason": "<one sentence>" }

// post
{ "decision": "post",
  "alert_ids": [<int>, ...],          // 1+ alert IDs that share one event
  "event_summary": "<paragraph>"      // what's the event, why this cluster, what's surprising
}
```

**System prompt focus:** "You are choosing the single best event to tweet about, or skipping. You do not write the tweet. Group alerts that share the same underlying event (same `event_slug` or same `condition_id`). Output one event's alert IDs plus a short framing paragraph for downstream stages, or skip if nothing stands out."

### Stage 2 — data fetcher (deterministic)

**Purpose:** Fetch the trades and token map for the chosen alert IDs, then derive a small facts bundle that downstream LLMs can quote precisely.

**Input:** `alert_ids` + the matching full alert rows from `seed_alerts` (so signals/wallet/total_usd/etc. are available locally).

**Output:**
```jsonc
{
  "trades": [...],                                    // rows from alert_trades, shaped like Polymarket Data API
  "token_map": {"<outcome>": "<token_id>"},            // from Gamma /markets
  "facts_bundle": {
    "distinct_wallets": <int>,
    "total_usd": <float>,
    "trade_count": <int>,
    "time_span_minutes": <int>,                       // first → last trade
    "biggest_price_move": {"from": 0.32, "to": 0.41} | null,   // first→last price on the outcome with the largest USD share of the trades
    "peak_hour_volume_usd": <float> | null,            // max USD across rolling 60-minute windows over the trades
    "has_sharp_wallet": {"wallet": "0x...", "record": "29-4", "win_pct": 0.88} | null,
    "cluster_size": <int> | null,                     // from wallet_clustering signal severity, if present
    "has_volume_spike": <bool>,                       // true iff a pre_event_volume_spike signal exists on any chosen alert
    "minutes_to_resolution": <int> | null              // (game_start_time or event_end_estimate) - now
  }
}
```

**Implementation:** Reuses today's `_fetch_alert_trades` and `_fetch_market_tokens`. The facts bundle is built from (a) cheap stats over `trades` (distinct wallets, time span, biggest price move, peak hour volume) and (b) fielded data on the chosen alert rows (signals list, `llm_copy_action`, `game_start_time`, `event_end_estimate`).

`has_sharp_wallet` is the trickiest field: signals only carry `{strategy, severity, headline}`, so the actual record string isn't directly available. Resolution path during implementation: try `llm_copy_action` (which the LLM filter already populates with structured copy data) first; fall back to a lookup against the `wallet_pnl` SQLite table if signals contain a `win_rate_tracking` entry but no record string is available. If neither yields a record, set `has_sharp_wallet = null` — the chart picker treats this as "no `wallet_record_card` available."

No new HTTP calls beyond what `enrich_alert_for_charts` already does.

**Failure handling:** Same as `enrich_alert_for_charts` today — fetch failures are absorbed (missing trades → empty list; missing tokens → no token_id). Facts bundle fields gracefully degrade to `null`. The pipeline continues even if `trades=[]` and `token_map={}`.

### Stage 3 — chart picker (LLM)

**Purpose:** Pick the chart type whose visual proves the surprise the tweet should lead with.

**Input:** chosen alerts (compact form) + `event_summary` + `facts_bundle`.

**Output:**
```jsonc
{ "chart_type": "price_sparkline" | "volume_bar" | "wallet_record_card" | "cluster_card" | "none",
  "hook_anchor": "<one phrase: what the chart proves>"   // e.g., "29-4 sharp record", "32c→41c flip", "12× normal volume"
}
```

**System prompt focus:** Keep the existing "Chart selection" guidance from `twitter_simple` (chart matches the lead clause), but give the picker the facts bundle so it can choose informedly: prefer `wallet_record_card` only if `has_sharp_wallet` is non-null; prefer `price_sparkline` only if `biggest_price_move` is meaningful; etc.

**Validation:** `chart_type` must be one of the five enum values; `hook_anchor` must be a non-empty string ≤ 80 chars.

### Stage 4 — writer (LLM)

**Purpose:** Compose the tweet.

**Input:** chosen alerts (compact form) + `event_summary` + `facts_bundle` + `chart_type` + `hook_anchor`.

**Output:**
```jsonc
{ "tweet": "<text with one polyspotter.com link>" }
```

**System prompt focus:** Inherits today's full Style / Audience / Strategy primer / BANNED jargon block from `twitter_simple` (this is the durable part — it encodes the tone). Drops the chart-selection block and the alert-picking block (those are earlier stages). Adds: "Lead with the hook_anchor. Expand using event_summary and facts_bundle. End on the polyspotter link."

**Validation** (against the tweet text):
- `_tweet_length(tweet) <= TWEET_MAX_CHARS` (280, URLs counted as 23)
- No phrase from `_BANNED_TWEET_PHRASES`
- Contains a polyspotter.com deep link matching `_POLYSPOTTER_URL_RE`

**Retry:** On validation failure, stage 4 is re-called once with an extra system message: `"Your previous tweet failed validation: <error>. Regenerate."` Stages 1–3 are not re-run. If the retry also fails, log `validation_error stage=4 attempts=2` and exit 1.

## Module layout

### New file: `storybot/twitter_pipeline.py`

Holds the four stage functions and the orchestration:
- `pick_event(llm_client, seed_alerts, *, usage) -> dict` — stage 1
- `fetch_data_bundle(alert_ids, seed_alerts) -> dict` — stage 2
- `pick_chart(llm_client, chosen_alerts, event_summary, bundle, *, usage) -> dict` — stage 3
- `write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick, *, usage, prior_error=None) -> dict` — stage 4 (the `prior_error` parameter drives the retry path)
- `validate_tweet(tweet: str) -> tuple[bool, str]` — text-only validation
- `main() -> int` — orchestrates the four stages and reuses `prepare_chart`, `post_tweet`, `record_tweet`, etc. from `tweet_utils`

Each stage gets its own focused system prompt (a constant near the top of the file: `STAGE_1_PROMPT`, `STAGE_2_PROMPT` is N/A, `STAGE_3_PROMPT`, `STAGE_4_PROMPT`).

### Extended file: `storybot/tweet_utils.py`

Move these helpers from `twitter_simple.py` into `tweet_utils` (drop leading underscores as they become public):
- `already_tweeted_ids` (was `_already_tweeted_ids`)
- `filter_posted_alerts`
- `strip_polyspotter_url` (was `_strip_polyspotter_url`)
- `fetch_alert_trades` (was `_fetch_alert_trades`)
- `fetch_market_tokens` (was `_fetch_market_tokens`)
- `enrich_alert_for_charts`
- `prepare_chart`
- `post_tweet`

`twitter_simple.py` is updated to import from `tweet_utils` — no behavior change.

### New env var: `TWITTER_PIPELINE_DRY_RUN`

Independent of `TWITTER_SIMPLE_DRY_RUN`. Same dry-run semantics: skip the Twitter post, save the chart PNG to `dry_runs/twitter_pipeline_<run_id>.png`, and dump the full stage transcript to `dry_runs/twitter_pipeline_<run_id>.json`.

## Logging and observability

Additive to existing scheme. All events include `run_id` and `bot="twitter_pipeline"`.

- `run_start`, `run_end` (existing convention)
- `seed_fetched`, `dedup_filtered` (existing)
- `stage_start stage=N`, `stage_end stage=N elapsed_ms=...`
- `event_picked alert_ids=... event_summary=...` (stage 1)
- `data_fetched trade_count=... has_token_map=... facts_bundle_keys=...` (stage 2)
- `chart_picked chart_type=... hook_anchor=...` (stage 3)
- `tweet_drafted attempt=N length=...` (stage 4)
- `validation_retry error=...` (stage 4 retry only)
- `chart_selected`, `chart_render_error` (existing)
- `posted tweet_id=... alert_ids=...` (existing)

`llm_usage` accumulates across all 3 LLM stages into one `usage_totals` dict (same shape as today). The dict's keys (`requests`, `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`, `reasoning_tokens`) already cover what we need to monitor cache hit rate and reasoning-token spend.

## Failure handling summary

| Stage | Failure | Behavior |
|-------|---------|----------|
| 1 | LLM error / invalid JSON / unknown decision | Log, exit 1 (cron retries) |
| 1 | `decision: "skip"` | Log skip + reason, exit 0 |
| 2 | Trade fetch error | Log, set `trades=[]`, continue |
| 2 | Gamma fetch error | Log, set `token_map={}`, continue |
| 3 | LLM error / invalid JSON | Log, exit 1 |
| 3 | Invalid `chart_type` | Log, exit 1 (no auto-fallback — same as `twitter_simple` today) |
| 4 | LLM error | Log, exit 1 |
| 4 | Validation failure (1st attempt) | Log `validation_retry`, retry stage 4 once |
| 4 | Validation failure (2nd attempt) | Log, exit 1 |
| Render | `charts.render_chart_for_alert` raises | Log silently, post tweet without media |
| Post | Twitter create_tweet error | Log, exit 1 |
| Record | `record_tweet` error | Log, return 0 (tweet already posted) |

## Testing

Under `test/`, pytest:

- `test/test_twitter_pipeline_facts_bundle.py` — unit tests for the facts-bundle builder. Synthesize trade lists + signals, assert each field of `facts_bundle`. No DB, no network.
- `test/test_twitter_pipeline_validation.py` — same writer-validation cases as `twitter_simple`'s implicit checks (length, banned phrases, polyspotter link), plus one new test asserting the validation-failure-then-retry path calls the writer twice.

Stage prompts themselves are tuned via dry-run inspection (same approach as `twitter_simple` today). The dry-run JSON dump (each stage's input + output) is the primary debugging surface.

## Decisions

- **Step 2 is fully deterministic, not LLM-driven.** Chosen over a tool-driven research agent (option A in brainstorming) and an LLM-as-data-planner (option B). Reason: the seed alert already carries enough fielded data (`signals`, `llm_summary`, `total_usd`, etc.) that an LLM data-planner would mostly rubber-stamp; a research agent would over-spend tokens for a tweet bot.
- **Skip lives only in stage 1.** Chosen over shared skip across stages (option B in brainstorming). Reason: writer's job is to write; if quality drops, we add a stage-4 skip later. Easier to add than to remove.
- **Facts bundle (option B in brainstorming) sits between minimal raw fetch and full timeseries.** Gives the chart picker non-trivial signal without paying for full price/volume history.
- **Decisions + one-line framing flow between stages.** Each stage's output narrows the next stage's job (`event_summary` for stages 3+4; `hook_anchor` for stage 4). Avoids re-derivation while keeping handoffs cheap.
- **Validation retries once.** Cheap insurance against fixable formatting nits; anything beyond suggests a prompt issue that should be fixed upstream.
- **Coexists with `twitter_simple.py`.** Both bots run from cron at different cadences; comparing output quality is the user's evaluation, not a coded A/B test.

## Open questions

None at design time. Tuning details (exact wording of stage prompts, exact `facts_bundle` thresholds for `has_volume_spike` etc.) are deferred to implementation.
