# Market Detail Page Enrichment

Transform the market detail page from a flat list of alert cards into a data-rich intelligence dashboard with price context, market stats, wallet leaderboard, flow analysis, and cross-market theses — while keeping copy-trade CTAs prominent.

## Current State

The page has: breadcrumb nav, market title + metadata (resolution timer, USD tracked, signal count, tags), two outcome probability bars, and a vertical list of `AlertRow` components. Single column, text-heavy, no charts or market intelligence beyond the alerts themselves.

**File:** `frontend/src/app/market/[id]/market-page-client.jsx` (200 lines)

## New Sections (in page order)

### 1. Price History Chart

Full-width SVG chart inserted between the outcome bars and the notable trades section.

**Data source:** CLOB API `GET /prices-history?market={tokenId}&interval={interval}&fidelity={fidelity}`
- Token ID comes from the live market data (already fetched via `/api/market/{conditionId}/live`)
- Default to 7-day view; toggles for 24h, 7d, 30d, All

**Rendering:**
- Extend the existing `Sparkline.jsx` component or build a new `PriceChart.jsx` that uses native SVG (no charting library needed — the existing sparkline pattern works well)
- Gradient fill below the price line (matching current design tokens)
- Blue dot markers at timestamps where alerts in this market were placed (cross-reference `alert.scanned_at` with chart x-axis)
- Amber dot for highest-conviction alert (highest composite_score)
- Y-axis price labels, legend for marker colors
- Dashed horizontal grid lines for readability

**Time range toggle:** 4 buttons (24h / 7d / 30d / All) that re-fetch with different interval params. Active button gets highlighted background.

**Backend changes:** New endpoint `GET /api/market/{conditionId}/price-history?range=7d` that proxies to the CLOB `/prices-history` endpoint, mapping conditionId → tokenId via Gamma API, and selecting appropriate interval/fidelity params per range. Cache for 60 seconds.

### 2. Market Stats Bar

4-tile horizontal grid below the price chart.

**Tiles:**
- **24h Volume** — from Gamma API market data (`volume` or `volume24hr` field), already partially available in the live market response
- **Liquidity** — from Gamma API market data (`liquidity` field)
- **Spread** — from CLOB API `GET /spread?token_id={tokenId}`, shows bid-ask spread in cents
- **Smart Flow** — computed from alerts: sum of `total_usd` for each outcome side, show dominant direction as percentage (e.g., "87% No")

**Backend changes:** Extend the existing `/api/market/{conditionId}/live` response to include `volume_24h`, `liquidity`, and `spread` fields. Volume and liquidity already come from Gamma; spread requires a new CLOB call. Smart flow is computed client-side from the alerts data (no backend change).

### 3. Two-Column Layout

Below the stats bar, split into two columns on desktop (stack on mobile):
- **Left (wider, ~60%):** Notable Trades — the existing `AlertRow` list, unchanged
- **Right (~40%):** Top Holders Leaderboard + Market Pulse

### 4. Top Holders Leaderboard

Ranked list of the top wallets holding positions in this market.

**Data source:** Polymarket Data API `GET /holders?market={conditionId}` — returns wallet addresses and position sizes. Cross-reference with the `wallet_profiles` table in the backend DB for win_rate, total_pnl stats.

**Display per row:**
- Rank number
- Wallet address (truncated, linked to `/wallet/{address}`)
- Position size in USD
- Win rate badge (color-coded: green ≥80%, amber ≥65%, gray below)
- PnL badge
- Side indicator (which outcome they hold)

**Backend changes:** New endpoint `GET /api/market/{conditionId}/holders` that:
1. Calls Polymarket Data API `/holders?market={conditionId}`
2. Enriches each holder with wallet_profiles data from the DB (if available)
3. Returns top 10 holders sorted by position size
4. Cache for 5 minutes (holder data doesn't change rapidly)

### 5. Market Pulse

Small section below the Top Holders leaderboard.

**Flow bar:** Horizontal bar showing Yes vs No dollar flow from detected alerts. Computed client-side by summing `total_usd` per outcome side across all alerts for this market.

**Volume spike indicator:** Compare current 24h volume to 7-day average. If current volume > 2x average, show a lightning bolt + "Nx above 7-day average". This requires tracking recent volume — simplest approach: add a `volume_7d_avg` field to the live market endpoint by fetching recent volume data from Gamma.

### 6. Related Theses

Cards at the bottom showing cross-market positions from wallets active in this market.

**Data source:** Already available via `GET /api/theses` — filter by wallets that appear in this market's alerts. Each thesis shows the wallet, headline, related markets, and total USD.

**Backend changes:** New query parameter on `/api/theses`: `?wallet={address}` to filter theses by wallet. The frontend will call this for each unique wallet in the market's alerts (deduplicated, max 5 wallets) or batch them.

Better approach: New endpoint `GET /api/market/{conditionId}/theses` that returns theses from any wallet that has an alert in this market. Single call, backend does the wallet lookup.

**Display:** 2-column grid of thesis cards. Each card shows: thesis headline, wallet address, description, and tag chips for related markets.

## API Summary

| Endpoint | New/Modified | Source |
|---|---|---|
| `GET /api/market/{conditionId}/price-history?range=7d` | New | CLOB `/prices-history` |
| `GET /api/market/{conditionId}/live` | Modified — add spread | CLOB `/spread` |
| `GET /api/market/{conditionId}/holders` | New | Data API `/holders` + wallet_profiles DB |
| `GET /api/market/{conditionId}/theses` | New | wallet_theses DB table |

## Frontend Components

| Component | New/Modified | Purpose |
|---|---|---|
| `PriceChart.jsx` | New | SVG price history with alert markers and time toggles |
| `MarketStats.jsx` | New | 4-tile stats bar |
| `HoldersLeaderboard.jsx` | New | Ranked wallet list with badges |
| `MarketPulse.jsx` | New | Flow bar + volume spike indicator |
| `MarketTheses.jsx` | New | Related theses cards grid |
| `market-page-client.jsx` | Modified | Two-column layout, wire up new components |

## Responsive Behavior

- **Desktop (sm+):** Two-column layout for trades + holders
- **Mobile:** Single column, stacked: chart → stats → trades → holders → pulse → theses
- Stats bar: 4 columns on desktop, 2x2 grid on mobile
- Theses: 2 columns on desktop, single column on mobile

## Data Fetching Strategy

- **Server-side (page.jsx):** Fetch price history, holders, and theses in parallel alongside existing live market + alerts calls. All new endpoints get 60-second ISR revalidation.
- **Client-side polling:** Live market data continues polling every 30s (already implemented). Price chart does NOT poll — static after initial load. Holders refresh on page navigation only.
- **Caching:** All new backend endpoints cache upstream API responses (60s for prices, 5min for holders, 5min for theses).
