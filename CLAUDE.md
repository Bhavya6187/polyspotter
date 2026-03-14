# Polybot

Polymarket Notable Trade Scanner — monitors Polymarket trades and surfaces large bets ($3,000+) that show signals of informed edge: sharp bettors, coordinated flow, and high-conviction positioning.

## What This Project Does

Polybot fetches recent trades from the Polymarket Data API, runs them through 9 detection strategies, and produces composite alerts ranking the most interesting trades — copy-worthy bets from sharp bettors, informed wallets, and coordinated flow. It uses a local SQLite database (`polybot.db`) to track wallet history, P&L, price data, and other state across runs.

### Detection Strategies

Strategies live in `detection_strategies/` and fall into two phases:

**Per-trade** (run on each trade individually, in order):
1. `win_rate_tracking` — fetches wallet P&L from Data API, populates `wallet_pnl` table
2. `new_wallet_large_bet` — surfaces new wallets making large, confident bets (reads `wallet_pnl`)
3. `timing_relative_resolution` — surfaces bets placed close to market resolution (reads `wallet_pnl`)
4. `low_activity_large_bet` — surfaces large bets on quiet markets

**Batch** (run once across all trades, in order):
5. `pre_event_volume_spike` — detects volume surges signaling informed positioning
6. `wallet_clustering` — identifies linked wallets via shared funders (writes `wallet_funders`)
7. `concentrated_one_sided` — surfaces coordinated one-sided flow (reads `wallet_funders`)
8. `price_impact` — detects trades causing significant price movement
9. `correlated_cross_market` — surfaces wallets expressing a thesis across related markets

Order matters — some strategies depend on data written by earlier ones.

## Project Structure

- `polybot.py` — main entry point, orchestrates fetching trades and running strategies
- `detection_strategies/` — all detection strategy implementations
- `detection_strategies/__init__.py` — `Signal` dataclass, `DetectionStrategy` base class, strategy registry
- `db.py` — centralized SQLite database module with all table definitions and query helpers
- `gamma_cache.py` — shared Gamma API market metadata cache
- `test/` — pytest test suite for individual strategies

## Running

```bash
python polybot.py
```

Tests:
```bash
pytest
```

## Key APIs

- **Polymarket Data API**: `https://data-api.polymarket.com` — trade data, wallet positions
- **Gamma API**: `https://gamma-api.polymarket.com` — market metadata
- **Etherscan API** — used for wallet funding/age lookups in clustering strategies

## API Documentation References

When working with Polymarket APIs (CLOB, Gamma, Data API), refer to the official docs:
- Polymarket API docs: https://docs.polymarket.com/llms-full.txt

When working with Etherscan API (wallet lookups, transaction history, funder tracing):
- Etherscan API docs: https://docs.etherscan.io/llms-full.txt

## Tech Stack

- Python 3.13
- SQLite (WAL mode) via `db.py`
- `requests` for HTTP
- `pytest` for testing
- Virtual env in `venv/`
