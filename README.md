# Polybot

Polymarket Notable Trade Scanner — monitors Polymarket trades and surfaces large bets ($3,000+) that show signals of informed edge: sharp bettors, coordinated flow, and high-conviction positioning.

## How It Works

Polybot fetches recent trades from the Polymarket Data API, runs them through 9 detection strategies, and produces composite alerts ranking the most interesting trades. An LLM filter (GPT-5.4) evaluates each alert for interestingness before pushing it to the web dashboard. A local SQLite database (`polybot.db`) tracks wallet history, P&L, price data, and other state across runs, building richer baselines over time.

```
Fetch trades ($3k+) → Filter (duration, odds, resolved) → Per-trade strategies → Batch strategies → LLM filter → Push to backend
```

### Trade Filters

Before strategies run, trades are filtered to remove noise:

- **Short-duration markets** — markets lasting < 1 hour
- **Penny-collecting** — trades at extreme odds (> 0.90 or < 0.10)
- **Resolved markets** — outcome price >= 0.95

## Detection Strategies

Strategies live in `detection_strategies/` and run in two phases. Order matters — later strategies depend on data written by earlier ones.

### Per-Trade Strategies

| # | Strategy | What It Detects | Key Thresholds | Severity |
|---|----------|----------------|----------------|----------|
| 1 | **Win Rate Tracking** | Wallets with notably high historical win rates | >= 75% win rate on >= 10 resolved bets | 1.0-6.0 |
| 2 | **New Wallet Large Bet** | New/young wallets (< 30 days) making large bets | Wallet age < 30 days, escalates for repeat offenders | 1.0-7.0 |
| 3 | **Timing Relative Resolution** | Bets placed close to market resolution | Within 60 min of endDate; flags serial timers (>= 3 historical) | 1.0-8.0 |
| 4 | **Low Activity Large Bet** | Large bets on thinly-traded markets | 24h volume < $5k or bet >= 50% of 24h volume | 0.5-4.0 |

### Batch Strategies

| # | Strategy | What It Detects | Key Thresholds | Severity |
|---|----------|----------------|----------------|----------|
| 5 | **Pre-Event Volume Spike** | Unusual volume surges in a market | Window volume >= 10x historical baseline, >= $25k | 1.0-4.0 |
| 6 | **Wallet Clustering** | Linked wallets funded by the same source | >= 2 wallets sharing a funder (via Etherscan) | 5.0-8.0 |
| 7 | **Concentrated One-Sided** | Coordinated one-sided betting by multiple wallets | >= 3 wallets, >= $5k total | 3.5-8.0 |
| 8 | **Price Impact** | Trades causing abnormal price movement | >= 15pp shift in window or >= 25pp from historical range | 1.0-5.0 |
| 9 | **Correlated Cross-Market** | Wallets betting across multiple markets in the same event | >= 2 markets, >= $5k combined; flags serial cross-market traders | 1.5-4.0 |

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
config.py                      # Shared runtime configuration (--verbose flag)
llm_filter.py                  # GPT-5.4 alert evaluation and filtering
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
backend/                       # Web API (FastAPI + PostgreSQL)
  app.py                       # API endpoints
  database.py                  # PostgreSQL connection
  schema.sql                   # Database schema
  models.py                    # Pydantic request/response models
  basketball.py                # Basketball game data integration
frontend/                      # Web dashboard (Next.js 15 + Tailwind CSS 4)
  src/app/                     # Pages: home, alert, market, wallet, tag, thesis
  src/components/              # UI: AlertTable, MarketCard, PriceChart, HeroSpotlight, etc.
  src/hooks/                   # useLiveMarket, useCountdown, useSpotlight
  src/lib/api.js               # API client
seeder.py                      # Pushes alerts from scanner to backend API
reset_alerts.py                # Clears alerts from both Postgres and local SQLite cache
backfill.py                    # Backfills historical trade data (default 30 days)
```

## Setup

### Environment Variables

Create a `.env` file in the repo root:

```bash
# Required
ETHERSCAN_API_KEY=<your-etherscan-api-key>    # Polygon wallet funding lookups
AZURE_OPENAI_API_KEY=<your-azure-openai-api-key>  # Azure OpenAI GPT-5.4 LLM filtering
POLYBOT_BACKEND_URL=<your-backend-url>        # Backend API for alert ingestion
DATABASE_URL=<postgres-connection-string>     # PostgreSQL (backend only)

# Optional
NEXT_PUBLIC_API_URL=<backend-url>             # Frontend API target (default: http://localhost:8000)
```

### Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For the backend:

```bash
cd backend
pip install -r requirements.txt
```

For the frontend:

```bash
cd frontend
npm install
```

## Running

### Scanner

Continuous mode (scans every 60 seconds):

```bash
python polybot.py
```

Single scan:

```bash
python polybot.py --once
```

Verbose logging (shows per-trade detail, cache hits, cluster lines):

```bash
python polybot.py -v
```

### Backend

```bash
cd backend
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm run dev       # Development (http://localhost:3000)
npm run build     # Production build
npm run start     # Production server
```

### Tests

```bash
pytest
```

## Utilities

| Script | Purpose | Usage |
|--------|---------|-------|
| `backfill.py` | Backfill historical trade data into local SQLite | `python backfill.py [--days 30] [--threshold 3000] [--skip-etherscan] [--skip-profiles]` |
| `seeder.py` | Push alerts from scanner to backend API | Called automatically by `polybot.py` |
| `reset_alerts.py` | Clear all alerts from Postgres + local LLM cache | `python reset_alerts.py` |
| `compare_models.py` | Compare LLM model outputs for alert evaluation | `python compare_models.py` |
| `debug_llm.py` | Debug LLM filter responses | `python debug_llm.py` |
| `backtest_iran.py` | Backtesting script for Iran-related markets | `python backtest_iran.py` |

## Backend API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ingest` | Bulk ingest alerts from scanner |
| `GET` | `/api/alerts` | List alerts (paginated, filterable) |
| `GET` | `/api/alerts/{id}` | Single alert with trades + signals |
| `GET` | `/api/alerts/by-market` | Alerts grouped by market |
| `GET` | `/api/wallets/{addr}` | Wallet profile with recent alerts and bets |
| `GET` | `/api/strategies` | List all strategies seen |
| `GET` | `/api/tags` | List all market tags |
| `GET` | `/api/spotlight` | Featured/hero alert for dashboard |
| `GET` | `/api/resolving-soon` | Markets resolving soon |
| `GET` | `/api/theses` | List cross-market theses (paginated) |
| `GET` | `/api/theses/{id}` | Single thesis detail |
| `GET` | `/api/market/{id}/live` | Live market data (prices, holders) |
| `GET` | `/api/market/{id}/basketball` | Basketball-specific game data |
| `GET` | `/api/market/{id}/price-history` | Price candle history |
| `GET` | `/api/market/{id}/holders` | Market holders/positions leaderboard |
| `GET` | `/api/market/{id}/theses` | Theses for a specific market |
| `GET` | `/api/market/resolve/{partial}` | Resolve partial condition ID to full ID |
| `GET` | `/api/health` | Health check |

## APIs Used

| API | Base URL | Purpose |
|-----|----------|---------|
| Polymarket Data API | `data-api.polymarket.com` | Trade data, wallet positions, P&L |
| Gamma API | `gamma-api.polymarket.com` | Market metadata, profiles, resolution status |
| CLOB API | `clob.polymarket.com` | Live price candles, order book depth |
| Etherscan API | `api.etherscan.io` | Wallet funding history on Polygon |
| OpenAI API | `api.openai.com` | GPT-5.4 alert evaluation |

## Database

### Local SQLite (`polybot.db`)

| Table | Strategy / Module | Purpose |
|-------|-------------------|---------|
| `tracked_bets` | win_rate_tracking | Win/loss tracking for flagged wallets |
| `wallet_pnl` | win_rate_tracking | Wallet P&L from closed + open positions |
| `flagged_wallets` | new_wallet_large_bet | Repeat-flag counts per wallet |
| `flagged_trade_events` | new_wallet_large_bet | Per-trade flag entries for dedup |
| `timing_flags` | timing_relative_resolution | Wallets flagged for betting near resolution |
| `market_volume_snapshots` | pre_event_volume_spike | Periodic 24h volume snapshots |
| `wallet_funders` | wallet_clustering | Cached wallet-to-funder mappings |
| `price_history` | price_impact | Per-outcome price observations |
| `wallet_event_history` | correlated_cross_market | Cross-run wallet/event trade records |
| `price_candles` | backfill | CLOB historical price time-series |
| `orderbook_snapshots` | backfill | CLOB order book depth |
| `llm_evaluations` | llm_filter | Cached LLM verdicts by dedup key |
| `scan_runs` | polybot | Continuous mode scan metadata |

### Backend PostgreSQL

| Table | Purpose |
|-------|---------|
| `alerts` | Main alert records |
| `alert_trades` | Trades associated with alerts |
| `alert_signals` | Detection signals per alert |
| `wallet_profiles` | Cached wallet P&L and statistics |
| `price_candles` | Price candle data for sparklines |
| `wallet_theses` | Cross-market thesis groupings |

## Tech Stack

- **Scanner**: Python 3.13, SQLite (WAL mode), requests, python-dotenv, openai
- **Backend**: FastAPI, Uvicorn, PostgreSQL, Pydantic
- **Frontend**: Next.js 15, React 19, Tailwind CSS 4
- **Testing**: pytest
