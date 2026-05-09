# Polybot

Polymarket Notable Trade Scanner — monitors Polymarket trades and surfaces large bets ($1,000+) that show signals of informed edge: sharp bettors, coordinated flow, and high-conviction positioning.

## What This Project Does

Polybot fetches recent trades from the Polymarket Data API, runs them through 9 detection strategies, and produces composite alerts ranking the most interesting trades — copy-worthy bets from sharp bettors, informed wallets, and coordinated flow. An LLM filter (GPT-5.4 via Azure OpenAI) evaluates each alert and generates a headline, summary, bullets, and a structured "copy action"; an SEO generator adds titles/descriptions/FAQs for market pages. Uses a local SQLite database (`polybot.db`) to track wallet history, P&L, price data, and other state across runs.

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
- `llm_filter.py` — GPT-5.4 alert evaluation and structured output generation
- `seeder.py` / `reset_alerts.py` / `backfill.py` — ingest, reset, and backfill utilities
- `test/` — pytest test suite for individual strategies and the seeder
- `backend/` — FastAPI REST API serving alerts, wallets, strategies, and market data
  - `backend/app.py` — API endpoints (ingest, alerts, wallets, strategies, markets, live, sports, health)
  - `backend/database.py` — PostgreSQL connection via psycopg2 (reads `DATABASE_URL`)
  - `backend/schema.sql` — Postgres schema (alerts, trades, signals, profiles, candles, theses)
  - `backend/models.py` — Pydantic models for request/response schemas
  - `backend/sports/` — sport-overlay plugin framework: `base.py` (SportOverlay ABC + OverlayResponse envelope), `basketball.py`, `cricket.py` (each self-registers on import). New sports register here.
  - `backend/seo_generator.py` — LLM-generated SEO content for market pages
  - `backend/test_endpoints.py` / `backend/test_basketball.py` / `backend/test_sports_registry.py` — backend tests
- `frontend/` — Next.js 15 web app (React 19, Tailwind CSS 4)
  - `frontend/src/app/` — App Router pages (home, alert, market, wallet, tag, thesis) + `sitemap.js`, `robots.js`, `api/og` dynamic OG images
  - `frontend/src/components/` — UI components (AlertTable, MarketCard, PriceChart, HeroSpotlight, SearchBar, CommandPalette, basketball & cricket overlays, etc.)
  - `frontend/src/sports/` — frontend sport-overlay registry: `registry.js`, `index.js`, and per-sport plugin files registering `{ Banner, Header?, Sidebar }` slot components
  - `frontend/src/hooks/` — custom React hooks (useLiveMarket, useSportOverlay, useSpotlight, useCountdown, useMediaQuery)
  - `frontend/src/lib/` — `api.js` (API client), `pseudonym.js`, `slugify.js`, `tiers.js`

## Environment Setup

- **Python virtual environment**: Always use the venv at `venv/`. Activate it before running any Python commands: `source venv/bin/activate`
- **Environment variables**: Load from `.env` in the project root. This file contains API keys and other secrets — never commit it.

## Running

Scanner:
```bash
source venv/bin/activate
python polybot.py
```

Backend API:
```bash
source venv/bin/activate
cd backend && uvicorn app:app --reload
```

Frontend:
```bash
cd frontend && npm run dev
```

Articlebot (daily PolySpotter article + teaser tweet):
```bash
source venv/bin/activate
python storybot/articlebot.py        # writes a draft to articles table + .md to storybot/articles/
DRY_RUN=true python storybot/articlebot.py   # writes to storybot/dry_runs/

# After reviewing the draft (storybot/articles/<run_id>.md):
python storybot/publish_article.py <run_id>          # prints teaser tweet for manual posting, then flips draft → published
DRY_RUN=true python storybot/publish_article.py <run_id>   # preview only, no DB update
```

Cron: once daily at 13:00 UTC (9am ET) recommended for `articlebot.py`.
`publish_article.py` is run manually after human review.

Tests:
```bash
source venv/bin/activate
pytest                          # scanner tests
cd backend && pytest            # backend tests
cd frontend && npm run lint     # frontend lint
```

## Hosted Backend API

The backend is hosted at `https://api.polyspotter.com`. When working on the frontend, feel free to use it instead of running the backend locally. The frontend API client (`frontend/src/lib/api.js`) can be pointed at this URL.

## Key APIs

- **Polymarket Data API**: `https://data-api.polymarket.com` — trade data, wallet positions
- **Gamma API**: `https://gamma-api.polymarket.com` — market metadata
- **Etherscan API** — used for wallet funding/age lookups in clustering strategies
- **Polybot Backend API**: `https://api.polyspotter.com` — hosted backend serving alerts, wallets, markets

## API Documentation References

When working with Polymarket APIs (CLOB, Gamma, Data API), refer to the official docs:
- Polymarket API docs: https://docs.polymarket.com/llms-full.txt

When working with Etherscan API (wallet lookups, transaction history, funder tracing):
- Etherscan API docs: https://docs.etherscan.io/llms-full.txt

## Tech Stack

**Scanner:**
- Python 3.13
- SQLite (WAL mode) via `db.py`
- `requests` for HTTP
- `pytest` for testing
- Virtual env in `venv/`

**Backend:**
- Python 3.13 + FastAPI
- PostgreSQL via psycopg2
- Pydantic for data validation

**Frontend:**
- Next.js 15 (App Router)
- React 19
- Tailwind CSS 4
