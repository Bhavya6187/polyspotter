# Twitter Pipeline — Peak-Window Cadence Gating

**Date:** 2026-05-21
**Status:** Approved design

## Problem

The Twitter bot gets low engagement. The measured cause is **low reach /
impressions** — tweets are barely seen — not weak content. `twitter_pipeline.py`
is a drafting pipeline with already heavily-tuned writer/validator prompts;
further prompt tuning will not fix a reach problem.

The bot currently posts ~3–5 tweets/day. `run_twitter_pipeline_loop.sh` fires
every 5 hours on a blind timer, so a tweet can land at any hour — including
times when the (US sports/politics/crypto) audience is asleep. For a small
account, every post that lands in an empty feed and flops trains the algorithm
that the account is low-quality, suppressing the *next* post's reach.

## Goal

Cut to ~1–2 tweets/day, posted only inside known high-traffic windows, so each
post gets a fair algorithmic shot. No changes to drafting/content.

## Non-goals

- No writer/validator/picker **prompt** changes. Content quality is not the
  bottleneck and the prompts are already over-tuned.
- No quote-tweet / reply / newsjacking capability. The bot stays a cold
  standalone-tweet bot (explicitly chosen).
- No new persistent state store. Cadence is derived from data already
  available via `fetch_recent_tweets()`.

## Approach

Add a **scheduling/gating layer** in `twitter_pipeline.py`. The loop wakes
hourly; the pipeline self-gates at startup and exits early (skip) unless it is
a good time to post. All gating logic lives in pure Python functions so it is
unit-testable; DST is handled by `zoneinfo`.

Rejected alternatives:
- Gating in `run_twitter_pipeline_loop.sh` via bash date math — fragile,
  untestable, ugly DST handling.
- Replacing the screen-loop with fixed-hour cron entries — cron cannot express
  "skip if already posted today / under cap" and it abandons the existing
  screen/tmux workflow.

## Design

### Peak windows

Defined in the `America/New_York` timezone (so DST shifts automatically),
as a module-level constant in `twitter_pipeline.py`:

| Window id | ET hours      | Rationale                    |
|-----------|---------------|------------------------------|
| `morning` | 08:00–10:00   | US morning commute/feed scan |
| `midday`  | 12:00–14:00   | Lunch                        |
| `evening` | 18:00–22:00   | Sports primetime             |

Each window is a half-open `[start_hour, end_hour)` range in ET. Easy to
retune by editing the constant.

### Daily cap

`DAILY_POST_CAP = 2` (module-level constant). Three windows, cap of 2 → at
most 2 windows used per day.

### Gating functions (pure, testable)

Added to `twitter_pipeline.py`:

- `_current_peak_window(now: datetime) -> str | None` — converts `now` to ET
  and returns the window id it falls in, or `None`.
- `_posts_today(recent_tweets: list[dict], now: datetime) -> int` — counts
  tweets in `recent_tweets` whose `tweeted_at` is the same ET calendar day as
  `now`. Rows with missing/unparseable `tweeted_at` are ignored.
- `_posts_in_window(recent_tweets, window, now) -> int` — counts tweets in
  `recent_tweets` whose `tweeted_at` falls in the same window block on the
  same ET day as `now`.

Counts derive from `fetch_recent_tweets()` (already used by the event picker;
returns the last ~10 posted tweets with `tweeted_at`). At ≤2 posts/day, 10
rows covers several days — ample for both counts.

### Gate placement in `main()`

Inserted before any LLM work (cheapest checks first, fail fast):

1. `now = datetime.now(timezone.utc)`.
2. `window = _current_peak_window(now)`. If `None` → `log("skip", reason=
   "outside peak window")`, `log("run_end", drafted=False)`, `return 0`.
   This needs no DB call.
3. Fetch `recent_tweets` (move the existing `fetch_recent_tweets(limit=10)`
   call up to here; it is reused later by stage 1 and the validator, so it is
   fetched once and threaded through).
4. If `_posts_today(recent_tweets, now) >= DAILY_POST_CAP` → skip
   (`reason="daily cap reached"`).
5. If `_posts_in_window(recent_tweets, window, now) >= 1` → skip
   (`reason="already posted in <window>"`). Enforces one post per window.
6. Otherwise continue into the existing seed/dedup/quality-floor/stage-1 flow
   unchanged.

`DRY_RUN` bypasses the entire gate (steps 2/4/5) so previews and manual test
runs work at any hour. A `log("peak_window_gate", ...)` line records the
window id and the two counts for telemetry.

### Loop change

`run_twitter_pipeline_loop.sh`: `INTERVAL_SECONDS` default `18000` → `3600`
(wake hourly). Update the explanatory comment block at the top to describe the
new cadence model. The claude-edit + `publish_tweet.py` chain is unchanged and
completes well within an hour.

Most hourly wakes will skip at step 2 (outside a window) or step 5 (window
already used), exiting before the seed fetch and any LLM call — so total LLM
cost drops relative to the current every-5h behavior.

### Tests

New `pytest` cases (in `test/`, alongside existing pipeline tests):

- `_current_peak_window`: a time inside each window → its id; a time between
  windows / overnight → `None`; a time during US DST and during US standard
  time both resolve correctly (verifies `zoneinfo`, not a fixed UTC offset).
- `_posts_today`: counts tweets on the same ET day; excludes yesterday;
  ignores rows with missing/bad `tweeted_at`.
- `_posts_in_window`: counts a tweet inside the window block; excludes one in
  a different window the same day; excludes one in the same window a prior day.

## Net effect

~1–2 tweets/day, posted only when the audience is online, never two in the
same window. Same drafting machinery, same quality floor — just no more
posting into the void.
