# Zombie Sports Alerts Fix — Design

## Problem

The Top 3 cards on the home page surface alerts for sports markets whose games have already concluded. The example observed on 2026-04-18 ~23:06 local:

- Rank 1 — "Barcelona Open: Andrey Rublev vs Hamad Medjedovic" — labelled "Resolves in 149h 23m". The match ran earlier that day and the market is `closed: true`.
- Rank 2 — "Tampa Bay Rays vs. Pittsburgh Pirates" — labelled "Resolves in 157h 58m". The game ran earlier, the market is `closed: true`.

Both alerts are unactionable (you cannot copy a bet on a closed market) but stay ranked in Top 3 because the filter falls back to the UMA resolution deadline, which for sports is ~7 days after the actual event.

## Root Cause

Three signals are supposed to keep concluded events out of Top 3; today only one runs, and it misses the common case.

1. **Gamma lookup drops closed markets.** [gamma_cache.py:41-50](../../../gamma_cache.py#L41-L50) calls Gamma's `/markets?condition_ids=…` with no status flag. Gamma's default excludes `closed=true` markets, so the lookup returns `None` for any market that has closed since ingest.
2. **Missing market → missing `game_start_time`.** [seeder.py:157-181](../../../seeder.py#L157-L181) can only populate `game_start_time` if `get_market_by_condition()` returns a market. When it returns `None`, the alert row is upserted with `game_start_time = NULL`.
3. **Top 3 SQL falls back to UMA deadline.** [backend/app.py:1170-1179](../../../backend/app.py#L1170-L1179) filters out sports alerts past "kickoff + 3h" — but only when `game_start_time IS NOT NULL`. When NULL, it falls back to `event_end_estimate / end_date > NOW()`, which for sports is the UMA oracle deadline ~7 days out.
4. **Candle filter misses mid-price closes.** The existing `latest_candle.p > 0.03 AND latest_candle.p < 0.97` guard only catches markets whose price has migrated to 0 or 1 (settled). Closed-but-unresolved sports markets sit frozen at the last traded price (e.g. 0.795 for a winning favorite), so this filter is silent for them.

## Solution

Fix the root cause: make `get_market_by_condition()` find closed markets.

### Change

[gamma_cache.py](../../../gamma_cache.py) — modify `get_market_by_condition()` so that when the default `/markets?condition_ids=…` request returns an empty list, it retries once with `closed=true`. Cache the result the same way.

- Active markets: 1 request, same as today (no regression).
- Recently closed markets: 2 requests, then cached so subsequent lookups are free.
- Markets that genuinely don't exist: 2 requests, `None` cached in a negative-cache variant or just re-tried next call (current behaviour — uncached miss — is acceptable; do not change it in this fix).

### Cascading effect

Once this one function reliably returns closed markets:

1. `seeder._resolve_event_timing()` successfully reads `gameStartTime` (or the `events[0].startTime` fallback) and writes a real value into `alerts.game_start_time`.
2. On the next scanner run that touches these alerts, the rows are upserted with `game_start_time` set.
3. The already-existing SQL guard `a.game_start_time + INTERVAL '3 hours' > NOW()` evaluates to `FALSE` for concluded games, dropping them from `/api/top3`, `/api/spotlight`, and `/api/resolving-soon`.

No schema migration, no new column, no new API field, no frontend change.

### In-flight zombies

Alerts already in the database with `game_start_time = NULL` will not be retroactively repaired by this change alone. They stay visible until they age out via the existing `created_at > NOW() - INTERVAL '1 day'` clause at [backend/app.py:1178](../../../backend/app.py#L1178). Since the observed zombies were ingested within the last ~24h, they drop on their own within a day. **Decision: do not run a backfill.** Accept the short residual window in favor of zero operational work.

## Out of Scope

- New `market_closed` column / migration — considered; rejected as over-engineered given the `game_start_time` path already exists.
- UI changes to the countdown label ("Resolves in 142 days" → absolute date, urgency-based coloring) — considered as option B; deferred. The observed user complaint ("Resolves in 149h for a concluded sports game") is resolved purely by the cards dropping.
- `/api/spotlight` and `/api/resolving-soon` filter hardening — they benefit automatically from the populated `game_start_time`; no additional work needed.
- Retroactive backfill of existing alert rows.

## Testing

- Unit: extend [gamma_cache.py](../../../gamma_cache.py) tests (or add one) asserting that a closed market is returned when the first lookup is empty.
- Manual verification after deploy: run the scanner, confirm that the two zombie alerts observed on 2026-04-18 (Rublev tennis, Rays MLB) either drop from `/api/top3` or come back with `game_start_time` populated. No UI regression on currently active sports alerts (A-League O/U 2.5 at rank 3 should still render identically).

## Files Touched

- [gamma_cache.py](../../../gamma_cache.py) — retry lookup with `closed=true` on empty.

That's the entire change.
