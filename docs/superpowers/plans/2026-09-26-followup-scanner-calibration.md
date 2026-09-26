# Scanner calibration follow-up (PR E) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three measured calibration fixes from the 2026-09-26 handoff (items 1.1, 1.3, 1.6) as separately revertable commits, with the measured impact recorded in each commit message.

**Architecture:** Branch `fix/scanner-calibration` created from the head of `fix/scanner-followup` (PR A) so the `wallet_clustering.py` edits do not conflict. Measurements come from `docs/superpowers/specs/2026-09-26-scoring-items-analysis.md`; they are the justification for shipping under the handoff's "propose, measure, then ship" rule. No other constants change.

**Tech Stack:** Python 3.13, SQLite via `db.py`, pytest.

---

### Task 1: LLM cache key gets a score band; cached verdicts expire after 7 days (handoff 1.1)

**Files:**
- Modify: `seeder.py` (`_build_llm_cache_key`), `db.py` (`get_llm_evaluation` or equivalent read helper), `llm_filter.py` only if the read call site needs the TTL argument
- Test: `test/test_seeder_llm_cache_key.py`, `test/test_llm_filter_gate.py` (extend)

Measured: today ~125 alerts/day surface with a reused verdict; over 90 days 2,511 of 10,109 reuse rows would fail the gate on their own content; p90 age of a reused verdict is 2.5 days, p99 37.8 days. Adding `floor(composite_score)` to the key costs ≈ +17–20 GPT calls/day (+1.8%); a 7-day TTL ≈ +2/day. Baseline ≈ 957 calls/day.

- [ ] Read `_build_llm_cache_key` (per-wallet and cluster branches) and the `llm_evaluations` read/write helpers.
- [ ] Failing tests: (a) `test_per_wallet_cache_key_includes_score_band` — same wallet/cid/trade_count with scores 2.9 and 5.5 produce different keys, scores 5.1 and 5.9 the same key; (b) `test_cluster_cache_key_unchanged` — the cluster branch keeps its existing `composite_score // 2` band (regression guard); (c) `test_cached_verdict_older_than_ttl_is_ignored` — a row with `evaluated_at` 8 days old is treated as a miss and a fresh evaluation runs, a 6-day-old row is a hit.
- [ ] Implement: per-wallet key `llm:{wallet}:{cid}:{floor(log2(trade_count))}:{floor(composite_score)}`; module constant `LLM_CACHE_TTL_S = 7 * 86400` applied in the read helper (rows older than the TTL return `None`; do not delete them).
- [ ] Commit: `fix(llm): score band in the cache key and a 7-day verdict TTL` — body cites the numbers above.

### Task 2: `wallet_clustering` known-funder boost only for funders known before this window (handoff 1.3)

**Files:**
- Modify: `detection_strategies/wallet_clustering.py` (~218–290)
- Test: `test/test_wallet_clustering.py` (fix the patch at line 7 that hides the bug; extend)

Measured: 100% of 1,552 wallet_clustering signals in 90 days carry the boost (severity ≥ 6.0); the loop-2 "Known linked funder" branch never fired; with the boost removed, 0 of 1,514 alerts fall below the 3.0 gate floor (lowest recomputed composite 4.5), mean composite drop −0.81.

- [ ] Read the function; identify where `known_sybils` is read relative to `_get_first_funder()`'s `save_funder` calls.
- [ ] Failing tests: (a) `test_two_wallet_cluster_without_prior_funder_scores_5` — two wallets sharing a funder first seen this window → severity 5.0 (remove the `{}` patch so the real `get_known_sybil_funders` runs against the test DB); (b) `test_cluster_with_previously_known_funder_scores_6` — the funder already has two wallets in `wallet_funders` from an earlier run → 6.0; (c) `test_lone_wallet_with_historical_funder_lower_severity` — one wallet this window, funder historically linked to another wallet → the loop-2 branch fires with severity 4.0 (constant `HISTORICAL_LINK_SEVERITY = 4.0`).
- [ ] Implement: snapshot `known_sybils = get_known_sybil_funders(2)` BEFORE the funder lookups; loop 2 uses the snapshot and the lower constant.
- [ ] Commit: `fix(wallet_clustering): known-funder boost only for funders known before this window` — body cites the numbers.

### Task 3: `pre_event_volume_spike` normalises by the fetch window (handoff 1.6)

**Files:**
- Modify: `detection_strategies/pre_event_volume_spike.py` (~79–123), `polybot.py` (pass the window length to `analyze_all` context if it is not already available)
- Test: `test/test_pre_event_volume_spike.py` (extend)

Measured: the trade span used is p50 651 s vs a fetch window p50 ~1,300 s (ratio 0.48), so ratios are inflated ≈ 2×; with the window divisor 11.2% of 25,525 spike signals would not fire, survivors' severity shifts ≈ −0.32 (log10) before caps, and 57 alerts in 81 days drop below 3.0.

- [ ] Read the strategy and how batch strategies receive `since_ts` / the scan window (check `DetectionStrategy.analyze_all` signature in `detection_strategies/__init__.py` and the call in `polybot.scan_once`).
- [ ] Failing tests: (a) `test_spike_normalised_by_fetch_window` — three trades within 60 s totalling $10k on a market with $300k/day baseline, fetch window 1,200 s: no signal (ratio ≈ 2.4×); the same trades with the old span divisor would have fired; (b) `test_spike_fires_with_window_divisor_when_genuine` — $10k in a 1,200 s window on a $20k/day market fires (ratio ≈ 36×) with severity `log10(36)`.
- [ ] Implement: `window_seconds = max(now - since_ts, 60)` supplied by the scanner (fall back to the trade span only when no window is known, e.g. `--once` without a cursor).
- [ ] Commit: `fix(pre_event_volume_spike): normalise the baseline by the fetch window` — body cites the numbers.

### Task 4: Final check

- [ ] Full suite from the worktree root, zero failures; `ruff check` on changed files.
- [ ] Report with commits; note that alert volume and average composite will shift slightly after deploy (fewer duplicate/inflated signals), which is expected.
