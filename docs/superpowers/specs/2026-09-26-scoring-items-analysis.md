# Scoring-item calibration numbers (read-only analysis, 2026-09-26)

**Data sources and scope**
- SQLite `polybot.db`, opened read-only.
- Postgres, SELECT only.
- `llm_prompts.jsonl`, streamed. Each GPT evaluation is one line and carries the `Composite score`, `Total USD`, `Trade count` and `Detection signals` it was sent.
- `polybot.log`, the only scanner log on disk. It covers 2026-07-04 to 07-09: 1,596 LLM-filter passes, about 4.9 days.

**Data gap:** the newest alert, LLM verdict and prompt are all from **2026-09-19 21:24 UTC**. The scanner was restarted today at 18:40 UTC. Because of that, every "last N days" window below effectively ends on Sep 19. The Postgres "90 days" window covers Jun 28 to Sep 19, which is **81 days with data**.

**Postgres holds only kept alerts.** `seeder.push_to_backend` runs `filter_alerts` before ingest, so every Postgres-based count below describes alerts that were kept (freshly or from cache). Discarded alerts never reach Postgres.

---

## Item 1: LLM cache key ignores size and score, and never expires

**What the code does**
- `seeder._build_llm_cache_key` builds the key for per-wallet alerts as `sha256("llm:{wallet}:{cid}:{floor(log2(trade_count))}")[:32]`.
  - `trade_count` is the number of the wallet's trades **in the current scan window**, not a cumulative count.
  - Cluster alerts already add `composite_score // 2`.
- `llm_filter.filter_alerts` looks the key up in `llm_evaluations` **before** the pre-LLM gate and the market-day cap. A hit bypasses both, and it reuses the stored headline, summary and copy_action.
- Gate discards are cached under the same key, with `interesting=0` and a summary that starts `auto-discarded:`.
- `save_llm_evaluation` uses INSERT OR REPLACE and has no TTL.
- I confirmed the key reconstruction on the 3,000 most recent per-wallet alerts: 2,999 were found with `interesting=1`, and 1 was found with `interesting=0`.

### (a) `llm_evaluations` contents

| metric | value |
|---|---|
| rows | 440,668 |
| oldest / median / newest `evaluated_at` | 2026-03-23 / 2026-06-13 / 2026-09-19 |
| age buckets as of 09-26: 0–7d / 7–30d / 30–90d / >90d | 2,710 / 51,838 / 123,180 / 262,940 |
| gate discards (`summary LIKE 'auto-discarded%'`) | 108,326 (24.6%) |
| GPT verdict, kept (`interesting=1`) | 228,945 (52.0%) |
| GPT verdict, discarded | 103,397 (23.5%) |

Gate discard reasons:

| reason | rows |
|---|---|
| score < 3 | 66,741 |
| solo `correlated_cross_market` | 24,564 |
| junk tag | 7,196 |
| negative P&L | 6,407 |
| other solo strategies | 3,283 |

```sql
SELECT CASE WHEN summary LIKE 'auto-discarded%' THEN 'gate_discard'
            WHEN interesting=1 THEN 'llm_kept' ELSE 'llm_discard' END k, count(*)
FROM llm_evaluations GROUP BY k;
```

### (b) How often a cached verdict is reused

`scan_runs` has **no LLM counters**. Its columns are only `trades_*`, `signals_raised`, `unique_markets` and `alerts_pushed`. The only per-pass counters are the stdout lines `[llm_filter] N alert(s) resolved from cache` and `Kept K, discarded D of T`, and these survive only in `polybot.log`. The table below is parsed from that log (Jul 4–9).

| per LLM-filter pass, Jul 4–9 (4.9 days) | total | per day |
|---|---|---|
| alerts entering the filter | 35,399 | ~7,200 |
| cache hits | 20,738 (58.6%) | ~4,200 |
| └ cache hit, kept (kept − fresh INTERESTING) | 5,803 | ~1,175 |
| └ cache hit, discarded | 14,935 | ~3,020 |
| gate discards (fresh) | 5,218 | ~1,060 |
| deferred by the market-day cap | 5,573 | ~1,130 |
| GPT calls (kept / discarded / error) | 3,144 / 725 / 1 | ~783 |

Most of these hits are the same trades being re-scanned inside the 10-minute overlap. In Postgres those become upserts of the same `dedup_key` row. A cache hit on **new trades** shows up as a new Postgres row that has the same cache key as an earlier row.

Postgres check over the last 90 days: I grouped per-wallet composite alerts by `(wallet, cid, floor(log2(trade_count)))`.
- **10,109 later rows** share a key with an earlier row, which is **~125/day** of alerts surfaced with a reused verdict.
- 10,108 of the 10,109 have an `llm_summary` byte-identical to the first row in their group, which confirms that the verdict was reused.
- **2,511 of these 10,109 rows would fail today's gate on their own content**, and 1,285 of those have a score below 3. The cache lookup runs before the gate, so those rows skipped it.

| age of the reused verdict at reuse time | p50 | p75 | p90 | p99 | rows >1d | rows >7d | rows >30d |
|---|---|---|---|---|---|---|---|
| days | 0.04 | 0.22 | 2.5 | 37.8 | 1,385 | 687 | 155 |

### (c) Postgres, last 90 days: (wallet, condition_id) pairs with more than one alert

- Per-wallet composite alerts: 56,765.
- Pairs: 44,330. Pairs with more than one alert: **7,540**, covering 19,975 alerts.
- Cluster alerts (11,008, `wallet IS NULL`) are excluded because their key already includes a score band.

**Composite-score spread per pair (max − min):**

| p10 | p25 | p50 | p75 | p90 | p99 | mean | ≥1.0 | ≥2.0 |
|---|---|---|---|---|---|---|---|---|
| 0.00 | 0.02 | 0.61 | 2.30 | 4.26 | 8.54 | 1.47 | 40.4% | 27.5% |

**Later alert vs first alert in the pair (12,435 later alerts):**

| metric | p10 | p25 | p50 | p75 | p90 | p99 |
|---|---|---|---|---|---|---|
| score delta | −2.35 | −0.44 | 0.00 | +0.42 | +2.05 | +6.80 |
| total_usd delta ($) | −8,900 | −2,257 | 0 | +2,444 | +9,096 | +77,181 |
| total_usd ratio (later/first) | 0.29 | 0.54 | 1.00 | 1.75 | 3.23 | 14.8 |

- 20.9% of later alerts are at least 2× the first alert's USD, and 5.3% are at least 5×.
- 73.9% of later alerts carry a summary identical to the first alert's.

Restricted to the 10,109 same-key reuse rows:
- |score delta| ≥ 1: 3,494 rows. |score delta| ≥ 2: 2,244 rows.
- USD ratio ≥ 2×: 1,645 rows. USD ratio ≥ 5×: 365 rows.

```sql
SELECT id, alert_type, composite_score, tags, condition_id, wallet, total_usd, trade_count,
       md5(coalesce(llm_summary,'')) sum_md5, dedup_key, created_at, scanned_at
FROM alerts WHERE created_at > now() - interval '90 days';
-- grouped in Python by (lower(wallet), condition_id) and by (…, floor(log2(max(trade_count,1))))
```

### (d) Estimated extra GPT calls

Method: replay each same-key group in `created_at` order and count the later rows that would miss under the new key. Each miss is then filtered in two steps:
1. **Gate.** Apply the current gate: junk tags, score < 3, and the solo-strategy rule. The negative-P&L rule could not be replayed. A gated miss is cached under the new key and costs no GPT call.
2. **Market-day cap.** Use `llm_market_evals.evals` for that (cid, day) plus the replay's own extra calls, with a limit of 5. Alerts of $50k or more are exempt.

| variant | raw new-key misses | gated | capped | **extra GPT calls** | **per day** | vs baseline ~956 calls/day |
|---|---|---|---|---|---|---|
| add `floor(composite_score)` to the key | 4,344 | 1,278 | 1,707 | 1,359 | **~16.8** | +1.8% |
| 7-day TTL | 386 | 203 | 26 | 157 | **~1.9** | +0.2% |

**Caveats**
- These rows cover only groups whose verdict was **kept**, because Postgres holds only kept alerts.
- Groups with a GPT-discard verdict make up about 15% of GPT verdicts in Aug–Sep (see Item 4). Scaling by 1.18 gives roughly 20/day for the floor(score) variant and 2.3/day for the 7-day TTL.
- Groups with a **gate-discard** verdict cannot be observed at all. A later alert on the same key with score ≥ 3 is silently served the cached "score X < 3" discard. For scale, there are 66,741 such rows in total and about 1,300 gate-discard writes per day in Sep. The size of this effect is unmeasured.
- The first row of a group may itself be a cache reuse of a verdict made before Jun 28, so the TTL figure is a lower bound.
- `polybot.log` covers only 5 days in early July, before the Jul 11 negative-P&L gate and before the switch to gpt-5.6-luna.

---

## Item 2: the wallet_clustering "known linked funder" +1.0 always fires

**What the code does:** `wallet_clustering.py` lines ~210–263.
- `_get_first_funder()` persists every looked-up funder to `wallet_funders` **before** `get_known_sybil_funders(2)` is read.
- Every loop-1 cluster has n_total ≥ 2 wallets, so its funder is always already in `known_sybils`.
- Severity is therefore `min(8, 5 + log2 n)` instead of `min(8, 4 + log2 n)`.
- The loop-2 "Known linked funder … severity 6.0" branch is effectively unreachable.

The composite is computed by `compute_composite_score`: max severity per strategy × `STRATEGY_WEIGHTS` (wallet_clustering = 0.9), with 1, ½, ¼… decay. The gate floor is `GATE_MIN_SCORE = 3.0`. I executed the repo's function directly from `detection_strategies/__init__.py`.

**Postgres, last 90 days (kept alerts):**

| metric | value |
|---|---|
| wallet_clustering signal rows | 1,552 |
| alerts containing one | 1,514 of 67,773 (2.2%) |
| headlines that are loop-2 ("Known linked funder") | **0** |
| loop-1 signals whose severity equals the boosted formula | **1,552 / 1,552 (100%)** |
| severity distribution | 6.0: 546 · 6.58: 73 · 7.0: 127 · 7.32: 88 · 7.58: 292 · 7.81: 144 · 8.0: 282 |
| lowest stored composite among these alerts | 5.4 |

Cluster size is parsed from the headline `"{n} wallets share funder"`. There are no 1-wallet clusters.

| cluster size | alerts | solo wallet_clustering | mean composite drop (sev −1.0) | mean drop (exact unboosted `min(8,4+log2 n)`) | **fall below 3.0** |
|---|---|---|---|---|---|
| 2 | 520 | 7 | −0.78 | −0.78 | **0** |
| 3+ | 994 | 104 | −0.83 | −0.66 | **0** |
| all | 1,514 | 111 | −0.81 | −0.70 | **0** |

- With the −1.0 variant, the lowest composite is 4.5 and the 5th percentile is 5.75. None are below 4.
- The same result holds on every GPT-evaluated alert since Jun 28 in the prompt log, which includes alerts GPT discarded: 81,279 evaluations, 2,313 with wallet_clustering, **0 cross below 3.0**, lowest recomputed composite 4.5.

```sql
SELECT s.alert_id, s.strategy, s.severity, s.headline
FROM alert_signals s JOIN alerts a ON a.id = s.alert_id
WHERE a.created_at > now() - interval '90 days';
-- Python: compute_composite_score(signals) vs same with wallet_clustering severity −1.0
```

**Caveats**
- `alert_signals` has no details JSON, so cluster size comes from the headline text.
- 188 of the 1,514 alerts don't recompute to their stored `composite_score`. Across all alerts it's 9,391, mostly rows scanned before the 2026-07-03 score rescale. None of these rows are near the floor.
- The boost's other effects are not measured: ranking, the cluster-alert cache score band, and the severities GPT sees in the prompt.

---

## Item 3: pre_event_volume_spike normalises by trade span instead of the fetch window

**What the code does**
- `normalised_avg = baseline * window_seconds / 86400`, where `window_seconds = max(max_ts − min_ts, 60)` over the market's trades in the batch.
- The spike fires when `ratio ≥ 10`, `window_vol ≥ $10k` and `n_trades ≥ 3`.
- `severity = min(cap, log10(ratio))`, with cap 4 for a historical baseline and 3 for a 24h baseline. If the 24h ratio is also at least 10×, it gets +0.5.
- The fetch window is `polybot.resume_since_ts`: last trade − 600 s, floored at now − 3600. I measured it as `started_at − cutoff_ts` per `scan_runs` row.

**Signals, last 90 days (kept alerts):** 25,525 signals on 25,214 alerts. The baseline was historical for 16,703 and 24h for 8,822.

| distribution | p5 | p10 | p25 | p50 | p75 | p90 | p95 |
|---|---|---|---|---|---|---|---|
| severity | 1.18 | 1.32 | 1.70 | 2.42 | 3.00 | 3.46 | 3.89 |
| headline ratio (×) | 15.1 | 20.5 | 41.1 | 118 | 519 | 2,595 | 8,290 |
| fetch window W, all runs since 06-28 (s) | 900 | 945 | 1,030 | 1,131 | 1,246 | 1,379 | 1,517 |
| W for the run that produced the signal (s) | 1,018 | 1,069 | 1,169 | 1,299 | 1,479 | 1,887 | 5,716 |
| reconstructed trade span used (s) | 50 | 134 | 369 | 651 | 891 | 1,269 | 1,809 |
| max(span, 60) / W | 0.05 | 0.08 | 0.25 | 0.48 | 0.66 | 0.77 | 0.83 |

**How the span was reconstructed**
- For each signal, the alert's `scanned_at` is matched to the last `scan_runs.started_at` at or before it.
- The span is then taken from `tracked_bets` rows for that `condition_id` with `cutoff_ts ≤ trade_timestamp ≤ latest_trade_ts`. `tracked_bets` records every scanned trade via `win_rate_tracking`.
- The reconstructed trade count matches the headline's `n trades` exactly for 19,961 of 25,525 signals (78%). It is lower for 5,317 and higher for 247.

**Counterfactual:** `ratio' = ratio × max(span, 60) / W`.

| set | signals | **ratio′ < 10× (would not fire)** | ratio′ p10 / p50 |
|---|---|---|---|
| all | 25,525 | **2,855 (11.2%)** | 9.3 / 45 |
| count-matched only | 19,961 | **2,163 (10.8%)** | 9.5 / 44 |
| historical baseline | 16,703 | 2,014 (12.1%) | – |
| 24h baseline | 8,822 | 841 (9.5%) | – |

- Among surviving signals, the median log-shift in severity is about −0.32 (log10 of 1/0.48), before caps.
- 2,828 alerts lose the signal entirely. For **57** of them the composite then drops from ≥3 to below 3.0.

```sql
-- per signal (SQLite, read-only)
SELECT started_at, cutoff_ts, latest_trade_ts FROM scan_runs WHERE started_at >= '2026-06-20' ORDER BY started_at;
SELECT trade_timestamp FROM tracked_bets
WHERE condition_id = :cid AND trade_timestamp >= :cutoff_ts AND trade_timestamp <= :latest_trade_ts;
```

**Caveats**
- These are kept alerts only. Solo pre_event_volume_spike alerts are gated anyway.
- The `tracked_bets` unique key `(wallet, cid, outcome, side, ts)` collapses same-second fills, which explains some of the "lower" count mismatches.
- The +0.5 escalation can't be replayed because the baseline dollar values aren't stored.
- For 21 runs with a NULL cutoff (the 24h first-run window), W = 86,400.

---

## Item 4: baseline for a SYSTEM_PROMPT rewrite (last 30 days = Aug 27 – Sep 19, 24 days of data)

GPT calls are counted from eval prompts in `llm_prompts.jsonl`, excluding `thesis:` headline prompts; all use model gpt-5.6-luna. Verdict counts come from `llm_evaluations`, grouped by the `evaluated_at` date.

| day | GPT eval calls | GPT kept | GPT discarded | gate discarded (no call) | PG alert rows created |
|---|---|---|---|---|---|
| 08-27 | 791 | 681 | 110 | 1,176 | 716 |
| 08-28 | 925 | 797 | 118 | 1,217 | 860 |
| 08-29 | 1,305 | 1,141 | 174 | 1,622 | 1,175 |
| 08-30 | 1,466 | 1,205 | 261 | 1,689 | 1,253 |
| 08-31 | 754 | 630 | 120 | 1,046 | 682 |
| 09-01 | 656 | 554 | 102 | 1,070 | 616 |
| 09-02 | 772 | 677 | 95 | 1,177 | 744 |
| 09-03 | 673 | 576 | 97 | 1,028 | 634 |
| 09-04 | 801 | 683 | 118 | 1,247 | 729 |
| 09-05 | 1,385 | 1,203 | 182 | 1,654 | 1,234 |
| 09-06 | 1,111 | 932 | 178 | 1,350 | 966 |
| 09-07 | 970 | 807 | 160 | 1,098 | 784 |
| 09-08 | 874 | 736 | 138 | 1,312 | 763 |
| 09-09 | 994 | 824 | 169 | 1,484 | 898 |
| 09-10 | 815 | 695 | 120 | 1,282 | 733 |
| 09-11 | 780 | 641 | 139 | 1,221 | 725 |
| 09-12 | 1,326 | 1,150 | 175 | 1,879 | 1,234 |
| 09-13 | 1,289 | 1,069 | 210 | 1,771 | 1,114 |
| 09-14 | 672 | 575 | 99 | 1,034 | 617 |
| 09-15 | 798 | 652 | 145 | 1,159 | 704 |
| 09-16 | 810 | 668 | 142 | 1,140 | 691 |
| 09-17 | 823 | 682 | 141 | 1,221 | 720 |
| 09-18 | 938 | 800 | 138 | 1,252 | 829 |
| 09-19 | 1,230 | 1,048 | 182 | 1,480 | 1,112 |
| **total** | **22,958** (~957/day) | **19,426** | **3,513** | **31,609** | **20,533** |

- GPT keep rate is **84.7%** (19,426 / 22,939 cached verdicts).
- Calls reconcile with cached verdicts to within 19. The difference is inconclusive and error results, which are not cached.

**Graded copy return (`graded_calls` ⋈ `alerts` on `alert_id`)**
- These are the highest-score alerts per resolved market, all of which were kept.
- $100 flat stake, held to resolution. `return_pct` is (1−entry)/entry on a win and −1 on a loss.
- Junk-tag markets are excluded, as on the scoreboard. None of the last-30-day graded rows had junk tags.

| alert cohort (by `alerts.created_at`) | graded n | hit rate | mean return | median return | avg entry |
|---|---|---|---|---|---|
| last 30d (≥ 08-27) | 751 | 64.7% | **+8.8%** | +33.3% | 0.591 |
| └ composite | 504 | 65.7% | +9.8% | +28.2% | 0.596 |
| └ cluster | 247 | 62.8% | +6.6% | +35.1% | 0.582 |
| last 90d | 2,469 | 64.5% | +9.6% | +28.2% | 0.591 |
| 2026-07 | 805 | 65.5% | +13.0% | +31.6% | 0.581 |
| 2026-08 | 1,033 | 64.7% | +9.1% | +28.2% | 0.601 |
| 2026-09 (partial) | 558 | 63.1% | +5.6% | +30.7% | 0.589 |

```sql
WITH j AS (SELECT g.*, a.created_at, a.alert_type,
  EXISTS (SELECT 1 FROM json_array_elements_text(COALESCE(NULLIF(a.tags,''),'[]')::json) t
          WHERE t IN ('Crypto','Crypto Prices','Recurring','Bitcoin','Ethereum','Up or Down','5M','Daily','Weekly','Hide From New')) junk
  FROM graded_calls g JOIN alerts a ON a.id = g.alert_id)
SELECT to_char(created_at,'YYYY-MM'), count(*), avg(won::int), avg(return_pct),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY return_pct), avg(entry_price)
FROM j WHERE NOT junk GROUP BY 1 ORDER BY 1;
```

**Caveats**
- `evaluated_at` is overwritten on re-evaluation, and deferred or inconclusive alerts aren't cached, so the daily verdict counts are approximate.
- `graded_calls` grades only one alert per market. The Sep cohort is still resolving, and its recent graded markets skew toward short-dated events.
- Discarded alerts are never graded, so this is not a measure of GPT precision on the discarded side.
- Scripts and intermediate files are in the scratchpad: `item1c.py`, `item2.py`, `item3.py`, `item4.py`, `item4g.py`, `logparse.py`, `extract_prompts*.py`.
