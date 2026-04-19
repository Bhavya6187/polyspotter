# Detection Strategy Usage Report

**Window:** 2026-03-23 → 2026-04-19 (~28 days)
**Postgres:** Railway (alerts/alert_signals)
**SQLite:** local `polybot.db` (scan_runs, tracked_bets, etc.)

## Pipeline funnel

|              | Trades scanned | Raw signals | Alerts pushed | Conv. |
|--------------|---------------:|------------:|--------------:|------:|
| All-time     |        540,532 |     350,908 |        57,609 | 10.7% |
| Last 7 days  |        193,063 |     117,105 |        10,443 |  5.4% |

- **25,050 alerts** persisted to Postgres (de-dup'd; raw `alerts_pushed` is higher because of upsert/duplicate ingest).
- **64,651 alert_signals** total → **2.58 signals per alert on average.**
- Severity-of-strongest-signal per alert: `<3 → 1,095` · `3–5 → 16,578` · `5–7 → 5,742` · `7+ → 1,646`. **Two-thirds of alerts top out at moderate severity (3–5).** That's where the strategies are doing most of their work.

## Per-strategy volume (no strategy is dormant)

| Strategy                    | Signals | Alerts touched | Solo alerts | Times top severity | Median sev | p90 sev | p99 sev |
|-----------------------------|--------:|---------------:|------------:|-------------------:|-----------:|--------:|--------:|
| correlated_cross_market     |  21,304 |         17,646 |       3,598 |              9,532 |       4.00 |    4.00 |    6.00 |
| win_rate_tracking           |  10,255 |          9,866 |       1,370 |              4,825 |       4.00 |    4.00 |    5.00 |
| pre_event_volume_spike      |   9,885 |          9,857 |          84 |                493 |       2.13 |    3.25 |    4.00 |
| price_impact                |   7,037 |          6,091 |         166 |                315 |       1.80 |    3.00 |    3.50 |
| concentrated_one_sided      |   6,836 |          6,174 |          37 |              4,951 |       4.82 |    7.00 |    8.00 |
| new_wallet_large_bet        |   3,760 |          3,760 |         972 |              2,702 |       5.50 |    6.00 |    6.00 |
| low_activity_large_bet      |   2,828 |          2,197 |         225 |                272 |       1.00 |    3.00 |    3.16 |
| timing_relative_resolution  |   1,420 |          1,420 |         124 |                822 |       4.46 |    6.54 |    7.40 |
| wallet_clustering           |   1,326 |          1,308 |          62 |              1,149 |       7.58 |    8.00 |    8.00 |

**Headline finding:** every strategy fires. There are **no dormant strategies**. But the strategies fall into very different *roles* — some are discovery engines, some are amplifiers, and a few are mostly wallpaper.

---

## Roles by behaviour

### 1. Discovery engines (lots of solo alerts, lots of "top severity")

- **`correlated_cross_market`** — fires in **70%** of all alerts (17,646 of 25,050). Top severity in 9,532 alerts (the most). Stands alone in 3,598 alerts. **18,431 distinct headlines** out of 21,304 signals → almost every signal is unique.
  - Sub-pattern split: **17,949 "Serial cross-market trader"** vs **3,366 "N markets in same event"**. The serial-trader path is the primary driver; the same-event path (the original purpose of the strategy) only fires ~16% of the time.
  - This strategy is doing two jobs, and the wallet-tagging job dwarfs the thesis-detection job.

- **`win_rate_tracking`** — fires in 39% of alerts; solo in 1,370. Severity capped at 5 (4-line median) — it's a label, not an escalator.
  - Only 3,751 distinct headlines for 10,255 signals → same wallets re-flagged across many trades. The "X% win rate at avg odds Y%" template repeats.

- **`new_wallet_large_bet`** — solo in 972 alerts, top severity 2,702 times. **85% of signals are "REPEAT"** (3,199 of 3,760), only 15% are first-time flags. The strategy mainly catches *known repeat bettors*, not literally-new wallets — the genuinely-new tail is small.

### 2. Anchors (rarely fire, but when they do they dominate the alert)

- **`wallet_clustering`** — only 1,326 signals (smallest count) but is the **top-severity strategy in 87% of the alerts it touches** (1,149 of 1,326). p50 severity 7.58, p99 8.00 — pegged to its 8.0 ceiling.
  - When it fires it usually fires hard, and only 62 of those alerts are solo — clustering co-occurs with `concentrated_one_sided` (sensible: linked wallets buying together).
  - The cap means the strategy can't differentiate a 3-wallet ring from a 19-wallet sybil network in the score. Sample headlines show clusters of 19 wallets ($11,982 total) and 3 wallets ($16,110 total) both scoring near 8.

- **`concentrated_one_sided`** — fires in 25% of alerts. Top severity 4,951 times. Almost never solo (37 of 6,174). Cluster size distribution is heavily bottom-loaded:
  - 3 wallets: 2,356 · 4: 1,285 · 5: 777 · 6: 597 · 7: 432 · 8: 285 · 9+: ≤350 each.
  - **Half of all firings are at the bare minimum (3 wallets).** The threshold isn't filtering; the strategy is producing a long tail of barely-meeting-cutoff signals.

### 3. Wallpaper (fire often, severity floor, rarely change rankings)

- **`pre_event_volume_spike`** — fires in 39% of alerts, but is the top-severity signal only **5% of the time it appears** (493 of 9,857). Median severity 2.13. Co-occurs with `correlated_cross_market` (9,037×). Functionally a **modifier** that adds 2 points to scores.

- **`price_impact`** — top severity in 4.5% of appearances. Median 1.80. **63% of headlines are "rapid"** (4,415 of 7,037) and most are sports tickers — the same NBA team names recur (Clippers UP 11%, Suns UP 13%, Rockets UP 18%). The within-window/historical breakout path produces the more interesting signals but is the smaller half.

- **`low_activity_large_bet`** — top severity in 9.6% of appearances. **Median severity 1.00.** Headline split: 21 zero-vol, 1,672 low-vol, 2,151 ratio-based, 65 thin-book, 200 wide-spread. The ratio-based path dominates and is essentially noise — 21 cases of "24h vol $0" that fired identically suggests stale Gamma data, not informed trading.

### 4. Special: high-precision but narrow

- **`timing_relative_resolution`** — only 1,420 signals, but **84% are sports** (1,196) and **16% non-sports** (224). The non-sport tail is the *highest-quality* signal in the whole system: the BTC/ETH "Up or Down" serial-timer alerts cluster around 6–8 severity with `EDGE: +7%, $+177,835 P&L` headlines from one wallet, repeating across 70+ markets. **This narrow non-sport path is doing real work.** The sport path is mostly low-severity background.

---

## Co-occurrence (top pairs)

| Pair                                                  | Count |
|-------------------------------------------------------|------:|
| correlated_cross_market + win_rate_tracking           | 9,472 |
| correlated_cross_market + pre_event_volume_spike      | 9,037 |
| concentrated_one_sided + correlated_cross_market      | 8,200 |
| correlated_cross_market + price_impact                | 7,295 |
| concentrated_one_sided + pre_event_volume_spike       | 5,231 |
| concentrated_one_sided + price_impact                 | 4,234 |
| pre_event_volume_spike + price_impact                 | 3,949 |
| pre_event_volume_spike + win_rate_tracking            | 3,758 |
| concentrated_one_sided + win_rate_tracking            | 2,888 |
| price_impact + win_rate_tracking                      | 2,283 |

The high-volume strategies (`correlated_cross_market`, `pre_event_volume_spike`, `concentrated_one_sided`, `price_impact`) form a dense clique — they fire together on the same hot markets. `wallet_clustering` and `timing_relative_resolution` only join in when there's something special.

---

## Signals that look like problems

1. **`correlated_cross_market` is two strategies in one.** The "serial cross-market trader" branch outputs 5x as many signals as the original "N markets in same event" branch and dominates the dataset. Worth splitting them so we can tune them separately.
2. **`new_wallet_large_bet` is misnamed.** 85% of its volume is repeat-bettor escalation, not actual new-wallet detection. The literal-new path is a 561-signal trickle.
3. **`concentrated_one_sided` threshold is too loose.** 35% of clusters are at the floor (3 wallets) and almost all of those need other signals to clear the alert bar — pure 3-wallet clusters are co-occurring with `correlated_cross_market` to look meaningful.
4. **`low_activity_large_bet` is contributing almost nothing.** Median severity 1.0, top in 272 of 25,050 alerts (1.1%). The "24h vol $0" cluster (21 identical headlines) suggests Gamma stale data is leaking through. Either tighten significantly or retire.
5. **`wallet_clustering` saturation.** p50 = p99 = 8.0 means severity ceiling is doing all the discrimination work. A 19-wallet ring scores the same as a 3-wallet one — wasted ranking power on the highest-trust signal in the system.
6. **`price_impact` rapid path is mostly sports tickers.** Same headlines repeat 17–25 times each (one team's price moves predictably each game). The historical-breakout path is the smaller half but probably the more informative one.
7. **`pre_event_volume_spike` is a modifier, not a discoverer.** Solo only 84 times out of 9,857 firings. Fine — but recognise that its actual job is ranking-amplification, not detection.

## Signals that look healthy

- **`timing_relative_resolution` non-sport branch** (224 signals over 28 days) is finding genuinely informed trades — the BTC Up/Down serial-timer with +7% edge and $177k P&L is exactly the kind of bet a copy-trader would want flagged.
- **`wallet_clustering` rarely fires but anchors high-score alerts** when it does — top severity in 87% of its appearances. Co-occurrence with `concentrated_one_sided` reinforces both signals (the "share funder (linked)" boost in `concentrated_one_sided` is wired to the same data).
- **`concentrated_one_sided` is the second-most "top severity" strategy** despite firing 4x less than `correlated_cross_market`. Its severity scales sensibly with cluster size and gets boosted when `wallet_clustering` confirms shared funders.

## Numbers to feed back when proposing changes

- Total alerts: **25,050** · Total signals: **64,651** · Avg signals/alert: **2.58**
- Strategies that account for ≥30% of alert volume: `correlated_cross_market` (70%), `win_rate_tracking` (39%), `pre_event_volume_spike` (39%)
- Strategies with median severity ≤ 2: `low_activity_large_bet` (1.0), `price_impact` (1.8)
- Strategies pegged to their ceiling (p90 = p99): `wallet_clustering` (8.0), `new_wallet_large_bet` (6.0)
- Strategies with >80% headline reuse (low headline diversity): `timing_relative_resolution` (663 distinct of 1,420 = 47% diversity), `win_rate_tracking` (37% diversity)
- Strategies that are functionally never standalone: `concentrated_one_sided` (37 solo / 6,174 total = 0.6%), `wallet_clustering` (4.7%), `pre_event_volume_spike` (0.9%), `price_impact` (2.7%)
