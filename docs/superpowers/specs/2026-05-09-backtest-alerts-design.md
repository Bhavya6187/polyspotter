# Backtest Alerts Script — Design

## Goal

Backtest the most recent 1000 polybot-generated alerts that hit *resolved* markets,
and dump per-alert metrics + raw debugging context to a JSONL file so we can
analyze which detection strategies, signal combinations, wallet profiles, and LLM
verdicts produced winning vs. losing alerts.

The output is consumed offline (jq, pandas, ad-hoc grep) — there is no UI or
ingestion path. The script is a one-shot diagnostic tool, not a long-running
service.

## Inputs

- **Alert source:** Hosted backend at `https://api.polyspotter.com` (override via
  `BACKTEST_API_BASE` env var). We page through `/api/alerts?limit=...&offset=...`
  newest-first, then fetch full detail per alert via `/api/alerts/{id}`.
- **Wallet profiles:** `/api/wallets/{wallet}` — included only for composite alerts
  (cluster alerts have no single wallet).
- **Market resolution state:** Gamma API via the existing `gamma_cache` module
  (`get_market_by_condition`). Re-using the cache avoids re-implementing the
  retry/cache/rate-limit logic.

## Resolution criterion

A market is considered resolved (and therefore included in the backtest) iff
either:
- `closed == true` in the Gamma market record, **OR**
- any value in `outcomePrices` is `>= 0.99`.

Trades on unresolved markets are skipped entirely.

## Per-trade metrics

For each trade in an alert we look up the final price of the *held* outcome (the
trade's `outcome` field, matched by name against the Gamma `outcomes` /
`outcomePrices` arrays). Then:

- `final_price` — Gamma's current outcomePrice for the held outcome.
- `won` — `True` iff `(side == "BUY" and final_price >= 0.99)` or
  `(side == "SELL" and final_price <= 0.01)`. Values strictly between are
  reported as `won = None` (market closed at intermediate price — rare but
  possible for canceled markets).
- `pnl_usd` — for BUY: `size * (final_price - price)`; for SELL: `size *
  (price - final_price)`.
- `roi` — `pnl_usd / usd_value` (the dollars actually put at risk on this
  trade — for BUY this is what was paid; for SELL it's the symmetric
  short-side stake).
- `direction_match` — `True` iff `(side == "BUY" and final_price > price)` or
  `(side == "SELL" and final_price < price)`. Looser than `won` — captures
  whether the price moved the right way even on partial-resolution edge cases.

## Alert-level rollups

- `trades_won_pct` — fraction of trades with `won == True` (excludes `None`).
- `copy_trade_pnl_usd` — sum of per-trade `pnl_usd`.
- `copy_trade_roi` — `copy_trade_pnl_usd / sum(usd_value)`.
- `price_direction_match_pct` — fraction with `direction_match == True`.
- `per_trade_results[]` — full per-trade detail (entry, final, won, pnl, roi,
  direction_match) so callers can re-aggregate by strategy or wallet.

## JSONL line schema

One alert per line:

```
{
  "alert_id":          int,
  "alert_type":        "composite" | "cluster",
  "scanned_at":        iso8601,
  "composite_score":   float,
  "tags":              [str, ...],
  "market_title":      str,
  "condition_id":      str,
  "event_slug":        str,
  "end_date":          iso8601 | null,
  "wallet":            str | null,            # null for cluster
  "total_usd":         float,
  "trade_count":       int,
  "cluster_headline":  str | null,

  "signals":  [{"strategy": str, "severity": float, "headline": str}, ...],
  "trades":   [{
                  "transaction_hash": str, "wallet": str,
                  "outcome": str, "side": "BUY" | "SELL",
                  "price": float, "size": float, "usd_value": float,
                  "trade_timestamp": iso8601
              }, ...],

  "llm": {
      "headline":     str | null,
      "summary":      str | null,
      "bullets":      [str, ...],
      "copy_action":  {"outcome": str, "side": str,
                       "entry_price": float, "max_price": float} | {}
  },

  "wallet_profile": {
      "win_rate":         float | null,
      "closed_positions": int,
      "wins":             int,
      "losses":           int,
      "total_pnl":        float,
      "total_invested":   float,
      "avg_win_price":    float | null,
      "current_streak":   int,
      "times_flagged":    int
  } | null,

  "market_state": {
      "closed":          bool,
      "outcomes":        [str, ...],
      "final_prices":    [float, ...],
      "winning_outcome": str | null     # outcome whose final price >= 0.99
  },

  "backtest": {
      "trades_won_pct":             float,
      "copy_trade_pnl_usd":         float,
      "copy_trade_roi":             float,
      "price_direction_match_pct":  float,
      "per_trade_results": [{
          "transaction_hash": str,
          "outcome":          str,
          "side":             str,
          "entry_price":      float,
          "final_price":      float,
          "won":              bool | null,
          "pnl_usd":          float,
          "roi":              float,
          "direction_match":  bool
      }, ...]
  }
}
```

## CLI

```
python backtest_alerts.py [--limit 1000] [--scan-cap 5000] [--out backtest_alerts.jsonl]
```

- `--limit` — target number of *resolved* alerts to write (default 1000).
- `--scan-cap` — maximum alerts to scan from the backend before giving up
  (default 5000). Prevents runaway scans when most recent alerts are still open.
- `--out` — output path (default `backtest_alerts.jsonl` in CWD).

Progress is printed every N alerts: `Scanned X | Resolved Y | Skipped Z`.
A summary block prints to stdout at the end with:
- Counts: scanned, resolved (kept), skipped (unresolved), errored.
- Aggregate: total copy-trade PnL, mean ROI, mean win rate, breakdown by
  strategy (which strategies appear in winning vs. losing alerts).

## Networking & robustness

- Single `requests.Session` for connection reuse.
- 3-attempt retry with exponential backoff (1s, 2s, 4s) on transient errors
  (`5xx`, `RequestException`); fail-fast on `4xx` other than 429.
- 10s connect / 30s read timeout per call.
- Gamma lookups go through `gamma_cache.get_market_by_condition`, which already
  handles caching and retries.
- Errors on a single alert are logged and counted; the script continues with
  the next alert rather than aborting.

## Out of scope

- No re-running of detection strategies on historical trades (alerts are taken
  as-is from the backend, including their LLM verdicts).
- No write-back to the DB or backend.
- No CLOB candle fetches for time-windowed price snapshots (`+1h`, `+24h`, etc.).
- No Polymarket API authentication beyond what `gamma_cache` already does.
