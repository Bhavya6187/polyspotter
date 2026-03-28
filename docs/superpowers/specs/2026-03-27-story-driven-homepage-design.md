# Story-Driven Homepage Engagement Redesign

**Date:** 2026-03-27
**Goal:** Transform the PolySpotter homepage from a passive alert feed into a story-driven experience that increases time on site, return visits, viral sharing, and copy trade conversions for casual browsers.

**Approach:** Story-Driven Feed — every signal becomes a narrative moment worth sharing. We add 5 new engagement surfaces around the existing alert feed without replacing the current alert card design.

---

## Homepage Layout (top to bottom)

| Position | Section | Status |
|----------|---------|--------|
| Top | Header (existing) + Stats bar (existing) | No changes |
| Below header | **Hero: Market Spotlight** | NEW |
| Below hero | Ticker (existing) | No changes |
| Below ticker | **Resolving Soon** strip | NEW |
| Below resolving | Filters (existing) | No changes |
| Main feed | Alert cards (existing) with **wallet tier badges** + **share buttons** injected | MODIFIED |
| Interspersed in feed | **Cross-Market Thesis cards** | NEW (special card type) |
| Below feed | **Recently Resolved** scorecard | NEW |
| Bottom | Pagination (existing) | No changes |

---

## Feature 1: Hero Market Spotlight

### What it shows
The single most interesting unresolved story right now (highest composite score), auto-rotating through the top 3.

### Data sources
- `alerts`: `composite_score`, `market_title`, `total_usd`, `end_date`, `llm_headline`
- `wallet_profiles`: `win_rate`, `total_pnl`
- Live market API: current price + recent price change
- `alert_signals`: count of distinct wallets per market
- `price_candles`: last 24h of price data for mini sparkline (currently local SQLite only)

### New backend endpoint
`GET /api/spotlight` — returns top 3 alerts by composite score where market is unresolved, enriched with:
- Live price + 24h price change (from CLOB API, cached 30s)
- Wallet count (distinct wallets across alert_trades for that condition_id)
- Price candle data for sparkline (last 24h, downsampled to ~50 points)

### New backend data pipeline
- `price_candles` data must be pushed from local SQLite to backend PostgreSQL
- New backend table: `price_candles` — `condition_id`, `token_id`, `outcome`, `t` (timestamp), `p` (price)
- Seeder pushes candle data alongside alerts during ingestion

### Frontend behavior
- Auto-rotates every 8 seconds with crossfade transition
- Dot indicators at bottom (carousel-style)
- Pauses rotation on hover/touch
- Manual swipe on mobile
- Mini price chart: lightweight SVG sparkline (no charting library), green dot marking entry point
- Displays: market title, total smart money flow, wallet count, win rate of best wallet, resolution countdown, price change

---

## Feature 2: Cross-Market Thesis Cards

### What it shows
When the `correlated_cross_market` strategy detects a wallet betting across 2+ markets in the same event, render a special card type with purple accent — distinct from regular alert cards.

### Data sources
- `wallet_event_history` table (currently local SQLite only)
- `alerts` grouped by `event_slug` + `wallet`
- `wallet_profiles` for tier badge

### New backend work

**New table: `wallet_theses`**
```sql
CREATE TABLE wallet_theses (
    id SERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    event_slug TEXT NOT NULL,
    thesis_headline TEXT,          -- LLM-generated (e.g., "Iran talks will collapse")
    markets JSONB NOT NULL,        -- [{condition_id, market_title, outcome, side, usd_value, entry_price}]
    total_usd NUMERIC NOT NULL,
    composite_score NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(wallet, event_slug)
);
```

**Seeder changes:**
- When `correlated_cross_market` signals fire, group by (wallet, event_slug) and upsert into `wallet_theses`
- LLM generates a thesis headline from the combination of market titles + bet directions
- Updates existing thesis if new markets are added to the position

**New endpoint:**
`GET /api/theses?page=1&per_page=5` — returns active (unresolved) thesis cards, sorted by composite_score DESC

### Frontend behavior
- Interspersed in the main alert feed after every ~4 regular alert cards
- Visually distinct: purple left border, "Cross-Market Thesis" label
- Card content: thesis headline, wallet mini-profile with tier badge, list of markets with position size and entry price, total position size, share button
- Clicking expands to show individual market details

---

## Feature 3: Resolution Countdown & Outcome Tracker

### 3a: "Resolving Soon" strip (top of page, below ticker)

**What it shows:** Horizontal scrollable strip of markets resolving within 6 hours that have smart money alerts.

**Data sources (all available today):**
- `alerts.end_date` filtered to next 6 hours
- `alerts.total_usd` and `llm_copy_action` for bet direction
- Live price from existing market API

**New endpoint:**
`GET /api/resolving-soon` — returns alerts where `end_date` is within next 6h, sorted by `end_date` ASC. Fields: `market_title`, `end_date`, `total_usd`, `dominant_side`, `condition_id`.

**Frontend behavior:**
- Horizontal scrollable strip (like existing ticker)
- Each card: market title, live countdown timer, total smart money amount, dominant bet direction
- Color coding: amber for >1h, red pulsing for <1h (reuses existing `urgency-pulse` keyframe)
- Clicking navigates to market detail page
- Hidden when no markets resolve within 6h

### 3b: "Recently Resolved" section (bottom of page, above pagination)

**What it shows:** Grid of resolved markets from last 24 hours showing whether smart money won or lost.

**New backend data pipeline:**
- Currently `tracked_bets` records resolution in local SQLite but never pushes to backend
- New backend table:

```sql
CREATE TABLE alert_outcomes (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id),
    condition_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    won BOOLEAN NOT NULL,
    entry_price NUMERIC,
    resolution_price NUMERIC,
    pnl_usd NUMERIC,
    resolved_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

- Seeder needs a new resolution-checking step: after each scan, check if any alerted markets have resolved, compute outcomes, push to `alert_outcomes`
- Resolution detection: query Gamma API for market status, or check if any outcome price >= 0.95

**New endpoint:**
`GET /api/resolved?hours=24` — returns recently resolved alerts with outcome data, sorted by `resolved_at` DESC.

**Aggregate stats header:**
- "Smart money win rate this week: 73% (41/56)" displayed above the resolved grid
- Computed from `alert_outcomes` for the trailing 7 days

**Frontend behavior:**
- 2-column grid of resolved cards
- Each card: market title, WIN (green) or LOSS (red) badge, entry price vs resolution price, P&L amount
- Collapsed by default with "Show resolved (12)" toggle to avoid cluttering the page
- Auto-refreshes alongside the main feed (5-minute interval)

---

## Feature 4: One-Click Share Cards

### Share button UX
- Added to every alert card and thesis card — icon button next to "Copy trade" CTA
- On click: copies shareable URL to clipboard + shows toast confirmation ("Link copied!")
- URL format: `polyspotter.com/alert/{alert_id}` for alerts, `polyspotter.com/thesis/{thesis_id}` for thesis cards

### OG image generation

**New backend endpoint:**
`GET /api/og/{alert_id}.png` — returns a 1200x630 PNG image card.

**Implementation approach:**
- Use Next.js `ImageResponse` (built on `satori`) in a route handler at `app/api/og/[alertId]/route.jsx`
- This runs natively in the existing Next.js frontend — no separate service needed
- Returns a JSX-to-PNG response with the card layout
- Cached aggressively via `Cache-Control: public, max-age=31536000, immutable` — alert content doesn't change after creation

**Standard alert card content:**
- PolySpotter logo + branding bar
- Market title
- Bet amount + direction + entry price
- Wallet tier badge + win rate
- Win rate progress bar
- `polyspotter.com` watermark

**Thesis card variant:**
- Thesis headline
- List of markets with positions (up to 4)
- Total position size
- Wallet tier badge

### Meta tags
Alert detail pages and thesis pages need:
- `og:image` → `/api/og/{alert_id}.png`
- `og:title` → `llm_headline`
- `og:description` → `llm_summary`
- `twitter:card` → `summary_large_image`

These are set via Next.js `generateMetadata` on the server component.

---

## Feature 5: Wallet Mini-Profiles with Tier Badges

### Tier system

| Tier | Win Rate | Volume Required | Badge Color | Pseudonym Prefix |
|------|----------|-----------------|-------------|-----------------|
| Bronze | 50-65% | any | Brown/copper | "Wallet" |
| Silver | 65-75% | $10k+ invested | Silver/gray | "Trader" |
| Gold | 75-85% | $50k+ invested | Amber/gold | "Sharp" |
| Diamond | 85%+ | $100k+ invested | Purple/sparkle | "Whale" |

Both win rate AND volume thresholds must be met. Win rate alone is not sufficient.

### Wallet pseudonyms
- Deterministic from wallet address: `{TierPrefix}_{first 5 hex chars}`
- Examples: `Whale_0xc3a`, `Sharp_0x7f2`, `Trader_0xb91`
- Computed client-side from wallet address + tier

### Where badges appear
- Every alert card: replaces plain "78% win rate" text with compact badge row
- Compact format: colored avatar circle + pseudonym + tier pill + win rate pill
- Thesis cards: next to wallet identity
- Hero spotlight: featured wallet identity

### Clickable wallet profiles
- Clicking a wallet badge navigates to a dedicated wallet page at `/wallet/{address}`
- Panel shows: P&L, win rate, total markets, current streak, flagged count, recent alerts from that wallet
- Uses existing `GET /api/wallets/{address}` endpoint, extended with new fields

### Backend changes

**Extend `wallet_profiles` table:**
```sql
ALTER TABLE wallet_profiles ADD COLUMN total_invested NUMERIC DEFAULT 0;
ALTER TABLE wallet_profiles ADD COLUMN current_streak INTEGER DEFAULT 0;
```

- `total_invested`: sum of `usd_value` from `tracked_bets` for this wallet. Already available in local `wallet_pnl`; needs to be included in seeder push.
- `current_streak`: count consecutive `won=1` from most recent resolved bet backward. Computed during seeder wallet profile step from `tracked_bets` ordered by resolution time DESC.

**Extend `GET /api/wallets/{address}` response:**
- Add `total_invested`, `current_streak` fields
- Add `recent_alerts`: list of last 5 alerts involving this wallet (query `alert_trades` joined to `alerts`)

**Tier computation:**
- Computed client-side from `win_rate` + `total_invested` using the tier table above
- No backend tier field needed — keeps logic in one place and avoids sync issues

---

## New Backend Tables Summary

| Table | Purpose | Populated by |
|-------|---------|-------------|
| `price_candles` (PostgreSQL) | Price sparkline data for hero + future charts | Seeder pushes from local SQLite |
| `wallet_theses` | Cross-market thesis groupings | Seeder when `correlated_cross_market` fires |
| `alert_outcomes` | Resolved alert win/loss results | New seeder resolution-check step |

## New Backend Endpoints Summary

| Endpoint | Returns | Used by |
|----------|---------|---------|
| `GET /api/spotlight` | Top 3 unresolved alerts with live prices + sparkline data | Hero spotlight |
| `GET /api/theses` | Active cross-market thesis cards | Feed (interspersed) |
| `GET /api/resolving-soon` | Alerts resolving within 6h | Resolving soon strip |
| `GET /api/resolved?hours=24` | Recently resolved alerts with outcomes | Resolved section |
| `GET /api/og/{alertId}` (Next.js route) | OG image card as PNG via `ImageResponse` | Social sharing unfurls |

## Modified Backend Endpoints

| Endpoint | Change |
|----------|--------|
| `GET /api/wallets/{address}` | Add `total_invested`, `current_streak`, `recent_alerts` |
| `POST /api/ingest` | Accept `price_candles`, `wallet_theses`, `alert_outcomes`, extended `wallet_profiles` |

## Seeder Pipeline Changes

1. **Price candle push** — after each scan, push `price_candles` data for alerted markets to backend
2. **Thesis generation** — when `correlated_cross_market` signals fire, group into theses, LLM-generate headline, push to backend
3. **Resolution checking** — new step after main scan: check if any previously-alerted markets have resolved, compute win/loss, push `alert_outcomes`
4. **Extended wallet profiles** — include `total_invested` and `current_streak` in wallet profile push

---

## Frontend Component Changes

### New components
- `HeroSpotlight.jsx` — rotating hero carousel with sparkline
- `ResolvingSoonStrip.jsx` — horizontal scrollable countdown strip
- `ThesisCard.jsx` — purple-accented cross-market thesis card
- `ResolvedSection.jsx` — grid of resolved outcomes with aggregate stats
- `WalletBadge.jsx` — reusable tier badge component (avatar + pseudonym + pills)
- `ShareButton.jsx` — copy-to-clipboard share button with toast
- `Sparkline.jsx` — lightweight SVG sparkline component

### Modified components
- `home-client.jsx` — new layout incorporating all sections
- `AlertRow.jsx` — add `WalletBadge` and `ShareButton`
- `AlertDetail.jsx` — add OG meta tags via page-level `generateMetadata`

### New hooks
- `useCountdown.js` — live-updating countdown timer for resolving-soon cards
- `useSpotlight.js` — polls `/api/spotlight` every 60s

### New lib
- `tiers.js` — tier computation logic (win_rate + total_invested → tier name, color, prefix)
- `pseudonym.js` — deterministic wallet pseudonym from address + tier
