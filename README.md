# Polybot

Polymarket Unusual Activity Scanner — monitors Polymarket trades in real-time and flags large bets ($3,000+) that match detection strategies for suspicious activity.

## How It Works

Polybot fetches recent trades from the Polymarket Data API, runs them through 9 detection strategies, and produces composite alerts ranking the most suspicious activity. A local SQLite database (`polybot.db`) tracks wallet history, P&L, price data, and other state across runs, allowing the system to build richer baselines over time.

```
Fetch trades ($3k+, last 1hr) → Per-trade strategies → Batch strategies → Composite alerts
```

## Detection Strategies

Strategies live in `detection_strategies/` and run in two phases. Order matters — later strategies depend on data written by earlier ones.

### Per-Trade Strategies

| # | Strategy | What It Detects | Key Thresholds | Severity |
|---|----------|----------------|----------------|----------|
| 1 | **Win Rate Tracking** | Wallets with suspiciously high historical win rates | ≥70% win rate on ≥3 resolved bets | 3.0–6.0 |
| 2 | **New Wallet Large Bet** | New/young wallets (<30 days) making large bets | Wallet age <30 days, escalates for repeat offenders | 1.5–7.0 |
| 3 | **Timing Relative Resolution** | Bets placed close to market resolution | Within 60 min of endDate; flags serial timers (≥3 historical) | 1.0–8.0 |
| 4 | **Low Activity Large Bet** | Large bets on thinly-traded markets | 24h volume <$5k or bet ≥50% of 24h volume | 2.0–4.0 |

### Batch Strategies

| # | Strategy | What It Detects | Key Thresholds | Severity |
|---|----------|----------------|----------------|----------|
| 5 | **Pre-Event Volume Spike** | Unusual volume surges in a market | Window volume ≥5x historical baseline | 2.0–4.0 |
| 6 | **Wallet Clustering** | Sybil clusters — multiple wallets funded by the same source | ≥2 wallets sharing a funder (via Etherscan) | 5.0–6.0 |
| 7 | **Concentrated One-Sided** | Coordinated one-sided betting by multiple wallets | ≥3 wallets, ≥$5k total, within 5-min window | 3.5–6.0 |
| 8 | **Price Impact** | Trades causing abnormal price movement | ≥15pp shift in window or ≥25pp from historical range | 2.0–5.0 |
| 9 | **Correlated Cross-Market** | Wallets betting across multiple markets in the same event | ≥2 markets, ≥$2k combined; flags serial cross-market traders | 2.5–4.0 |

### Strategy Dependencies

```
win_rate_tracking → populates wallet_pnl → used by new_wallet_large_bet, timing_relative_resolution
wallet_clustering → populates wallet_funders → used by concentrated_one_sided
```

## Project Structure

```
polybot.py                     # Main entry point — fetches trades, runs strategies, outputs alerts
db.py                          # SQLite database module (WAL mode) with all table definitions
gamma_cache.py                 # In-memory Gamma API market metadata cache
detection_strategies/          # All 9 detection strategy implementations
  __init__.py                  # Signal dataclass, DetectionStrategy base class, registry
  win_rate_tracking.py
  new_wallet_large_bet.py
  timing_relative_resolution.py
  low_activity_large_bet.py
  pre_event_volume_spike.py
  wallet_clustering.py
  concentrated_one_sided.py
  price_impact.py
  correlated_cross_market.py
test/                          # pytest test suite
```

## APIs Used

- **Polymarket Data API** (`data-api.polymarket.com`) — trade data, wallet positions and P&L
- **Gamma API** (`gamma-api.polymarket.com`) — market metadata, public profiles, resolution status
- **CLOB API** (`clob.polymarket.com`) — live price candles, order book depth
- **Etherscan API** (`api.etherscan.io`) — wallet funding history on Polygon (requires `ETHERSCAN_API_KEY`)

## Running

```bash
python polybot.py
```

Tests:

```bash
pytest
```

## Tech Stack

- Python 3.13
- SQLite (WAL mode)
- `requests` for HTTP
- `pytest` for testing
