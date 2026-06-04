# Twitter Accountability & Identity Layer — Follower Growth

**Date:** 2026-06-04
**Status:** Approved design — **Phase 1 = Component A only**

> **Scope note (2026-06-04):** The implementation plan covers **Component A**
> (turn on the settle loop: result selection, scorecard image, posting via
> `publish_result.py`, and the `result_tweets` table). Components B (scoreboard
> module), C (weekly leaderboard), and light-B (track-record closer) are
> documented here for context but are **deferred** to later phases. The
> `result_tweets` table is built now (in A) so B/C can read it later without a
> second migration.

## Problem

The X account is not gaining followers. Measured state (per the account
owner): **decent impressions, few follows** — tweets *are* seen, but views do
not convert to follows.

This is a different bottleneck from the one
[2026-05-21-twitter-pipeline-peak-window-cadence](./2026-05-21-twitter-pipeline-peak-window-cadence-design.md)
fixed. That spec correctly diagnosed a *reach* problem and solved it with
peak-window cadence gating. Reach is now adequate; the bottleneck has moved to
**conversion**.

The root cause is structural, not per-tweet quality. Reading ~35 shipped
tweets back-to-back, every tweet is the same self-contained artifact:

> `[timing] + [N accounts bought $Xk on <side>] + [wallet record] + [volume ran Nx] + [reply-bait question?]`

Each is individually strong and fact-checked. But they are **interchangeable**
and each is a **dead end** — the reader never learns whether the flagged bet
hit, and the account's value does not accumulate across tweets. A follow is a
bet on *future* value the reader can't get by scrolling past one post. Nothing
in the current feed creates that expectation: no outcome follow-up, no
verifiable track record, no recurring identity.

## Goal

Convert impressions into follows by making the account's value **cumulative and
verifiable**. Three loops that feed each other:

1. **Flag** (already shipped): "a 170-12 wallet just dropped $191k on Felix."
2. **Settle** (computed today, but never posted): "That Felix call? ✅ Cashed +$140k."
3. **Keep score** (does not exist): "Flagged sharp calls: 9-4, +$210k over 14 days."

The scoreboard line in (3) is the follow-trigger. (2) supplies its data and is
engaging on its own. A weekly leaderboard turns the scoreboard into recurring,
recognizable identity.

## Non-goals

- No engagement/reach mechanics (auto-replies, quote-tweets, follow-loops,
  newsjacking). The bot stays a standalone-tweet bot. (Owner-selected scope:
  "add new content types," not "content + engagement mechanics.")
- No change to the **core shape** of the main flag tweet or its
  writer/validator/picker prompts, beyond adding one optional closer category
  (light B). The flag content is not the bottleneck.
- No rebuild of the resolution/P&L computation in `result_pipeline.py` — it is
  correct and reused as-is.
- No profile-level changes (bio, pinned tweet, header). Those are manual and
  out of code scope, though they are the natural complement to this work.

## Approach

Four components, built and shippable in order. Each reuses existing
infrastructure (the resolution/P&L math, the chart renderers, the
draft → Claude-edit → publish loop pattern) rather than introducing new
patterns.

```
   alert_trades / alerts / tweeted_alerts (existing)
                     │
        ┌────────────┴─────────────┐
        ▼                          ▼
  twitter_pipeline.py        result_pipeline.py  ── computes W/L + P&L (exists)
  (flag tweets, exists)              │
        ▲                            ▼ A: select + render scorecard + publish
        │  light-B closer       publish_result.py (new) ── posts, records row
        │                            │
        │                            ▼
        └──────── B: scoreboard.py ◄── result_tweets table (new, Postgres)
                         │
                         ▼  C
                  weekly_recap.py (new) ── weekly leaderboard post
```

### Data model — `result_tweets` table (new)

The source of truth for posted results, dedup, and the scoreboard. Added to
`backend/schema.sql` as a forward-only migration.

| column              | type          | note                                            |
|---------------------|---------------|-------------------------------------------------|
| `id`                | serial PK     |                                                 |
| `original_tweet_id` | text          | the flag tweet this settles; unique (dedup)     |
| `result_tweet_id`   | text NULL     | X id of the posted result tweet                 |
| `alert_ids`         | int[]         | alerts the original covered                     |
| `condition_ids`     | text[]        | markets that resolved                           |
| `n_won`             | int           | trade-level wins                                |
| `n_lost`            | int           | trade-level losses                              |
| `net_pl_usd`        | numeric       | realized payout − invested                      |
| `total_invested_usd`| numeric       |                                                 |
| `outcome`           | text          | `cashed` \| `burned` \| `mixed` \| `wash`       |
| `event_label`       | text          | human label for leaderboard/scorecard           |
| `posted_at`         | timestamptz   | NULL until published                            |
| `created_at`        | timestamptz   | default now()                                   |

`UNIQUE(original_tweet_id)` replaces the current artifact-file dedup in
`result_pipeline.py` with a robust DB constraint. The `live_runs/result_*.json`
artifacts remain as a human-readable transcript, but they are no longer the
dedup key.

### Component A — Turn on the settle loop

Files: `result_pipeline.py` (modify), `charts.py`/`chart_grid.py` (add a
scorecard renderer), `publish_result.py` (new), `run_result_pipeline_loop.sh`
(modify to chain compose → optional Claude edit → publish).

**Selection (curated, win-weighted, with an honesty floor).** Not every
resolved cluster is posted. `result_pipeline.py` ranks resolution candidates
and selects up to `RESULT_DAILY_CAP` per day:

- Prefer notable calls: larger `|net_pl_usd|`, sharper originating wallet,
  bigger original stake.
- Win-bias is a single tunable, `RESULT_WIN_BIAS` (default 0.8) — the
  target fraction of posted results that are wins.
- **Honesty floor (hard):** any loss whose `|net_pl_usd|` exceeds
  `RESULT_LOSS_NOTABLE_USD` is *always* eligible regardless of win-bias. We do
  not hide big losses. Rationale: a visibly all-wins record gets screenshotted
  and called cherry-picked on X, destroying the trust this whole layer exists
  to build. "They post their losses" is itself a follow-trigger.
- A rolling check keeps the *actually posted* win share near `RESULT_WIN_BIAS`
  rather than letting variance drift it to 100%.

**Prompt change.** `SYSTEM_PROMPT_RESULT` drops the `polyspotter.com` URL
(result tweets ship link-free like the main feed) and the `alert_url` payload
field is removed. The scorecard image is the payload.

**Result scorecard image.** A new renderer (new `chart_type`
`result_scorecard`, living alongside the existing renderers and reusing their
fonts/palette/canvas helpers) draws:

- A large verdict band: green `✅ CASHED +$31k` or red `❌ BURNED −$28k`
  (mixed → neutral `± NET +$4k`, wash → `BROKE EVEN`).
- Original event label + the side the cluster was on.
- Trade W-L and the originating wallet's record.
- Small "flagged N days ago" stamp to make the loop legible.

**Publishing.** `publish_result.py` mirrors `publish_tweet.py`: read the
composed draft + artifact, re-validate (length / banned-phrase / no-URL via the
existing `validate_tweet`), post text + scorecard PNG via the existing
`post_tweet`, then write the `result_tweets` row (`posted_at`, `result_tweet_id`).
Idempotency via the `UNIQUE(original_tweet_id)` constraint + draft deletion,
same as the twitter loop. `run_result_pipeline_loop.sh` gains the
compose → `claude -p` edit → `publish_result.py` chain (the Claude edit step
reuses the same fact-fidelity review prompt shape as the twitter loop).

### Component B — Scoreboard module (`scoreboard.py`, new)

Pure functions over the `result_tweets` table; no LLM.

- `compute_record(window_days=14)` → `{wins, losses, hit_rate, net_pl_usd,
  n_calls, window_days}` aggregated across posted results in the window.
- `format_record_line(record)` → a one-line, exact-figure string for the writer
  ("Our flagged sharp calls: 9-4, +$210k over 14 days.").
- `is_record_strong(record)` → bool gate: only surface when the window has
  enough settled calls (`>= SCOREBOARD_MIN_CALLS`, default 6) AND a non-
  embarrassing hit rate. Prevents citing a 1-1 record.

**Accuracy is non-negotiable.** Every figure is computed from resolved on-chain
data already aggregated by `result_pipeline.py`. Nothing here is LLM-estimated.
Downstream writers may only echo `format_record_line` verbatim or cite its
exact integers — mirroring the fact-fidelity discipline the existing tweet
validators already enforce.

### Component C — Weekly leaderboard franchise (`weekly_recap.py`, new)

A once-weekly appointment post. Mostly a renderer + one caption LLM call over
B's data.

- Selects the week's top cashed calls + the rolling scoreboard from
  `result_tweets`.
- Renders a leaderboard image (reuses scorecard/chart styling).
- One short LLM-composed caption (exact figures only), validated by the same
  `validate_tweet` checks.
- Published via the same publish helper as A. Own weekly cap (see budgets).

### Light B — Follow-reason closer in the flag feed (`twitter_pipeline.py`)

- Add a new closer category to `SYSTEM_PROMPT_WRITER`'s closer list: the
  **track-record closer** ("Our flagged sharp calls: 9-4 the last two weeks.").
- The writer is offered the `format_record_line` string in its payload **only
  when** `scoreboard.is_record_strong()` is true; otherwise the field is absent
  and the writer falls back to existing closers. This keeps the closer honest
  and avoids over-using it (it is one option among the existing closer types,
  not a mandate).
- The tweet validator gets one rule: a cited record line must exactly match the
  provided `scoreboard_record_line` (reject fabricated records), consistent
  with existing rules 1–9.

### Post budgets (separate, owner-selected)

Result and weekly posts do **not** share the flag feed's `DAILY_POST_CAP=2`.
New independent caps:

- `RESULT_DAILY_CAP` (default 2) — result tweets per ET day.
- Weekly leaderboard: once per ISO week, gated in `weekly_recap.py`.
- Result/weekly posting still respects peak-window timing (reuse the existing
  `_current_peak_window` helper) so settle posts also land when the audience is
  awake.

## Testing

`pytest` suite under `test/`, matching existing test style:

- **A:** selection ranking (win-bias target, honesty-floor always admits big
  losses), URL absence in the result prompt path, scorecard renderer produces
  PNG bytes for cashed/burned/mixed/wash, `publish_result` dedup via the unique
  constraint (no double-post).
- **B:** `compute_record` aggregation math on fixture rows; `is_record_strong`
  gating at the min-calls and hit-rate boundaries; `format_record_line` exact
  formatting (rounding rules: "$210k", exact "9-4").
- **C:** weekly selection picks the right window; once-per-week gate.
- **Light B:** validator rejects a record line that doesn't match the provided
  scoreboard line; writer payload omits the field when the record is weak.

Renderers are tested for "returns bytes / doesn't raise," not pixel output,
matching how `charts.py` is currently tested.

## Risks & mitigations

- **Cherry-picking perception.** Mitigated by the honesty floor + rolling
  win-share check + posting losses. This is the single biggest reputational
  risk and is treated as a hard rule, not a tunable-to-zero.
- **Fact errors in results** (wrong W/L, inflated P&L). Mitigated by reusing
  the already-correct `aggregate_result` and the Claude-edit fact review step;
  results cite only computed figures.
- **Feed flooding.** Mitigated by separate small caps + peak-window timing +
  curated selection.
- **Resolution lag / ambiguous markets.** Already handled by
  `result_pipeline.py` (`_resolution_for_market` skips unresolved/ambiguous;
  `RESULT_LOOKBACK_DAYS` bounds staleness). Unchanged.

## Open tuning knobs (safe defaults, adjust from live data)

`RESULT_DAILY_CAP=2`, `RESULT_WIN_BIAS=0.8`, `RESULT_LOSS_NOTABLE_USD=20000`,
`SCOREBOARD_WINDOW_DAYS=14`, `SCOREBOARD_MIN_CALLS=6` (last two used by deferred B).
