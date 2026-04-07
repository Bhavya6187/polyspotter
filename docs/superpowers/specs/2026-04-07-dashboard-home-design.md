# Dashboard Home Redesign — "Smart Money Command Center"

**Date:** 2026-04-07
**Goal:** Increase return visits and session depth for active Polymarket traders by transforming the home page from a chronological alert feed into an information-dense trading dashboard.

**Target user:** Active Polymarket traders — already have accounts, bet regularly, want edge from smart money signals.

**Core problems solved:**
1. Users see the home feed but rarely click into market detail pages
2. Users visit once but don't come back — no hook for return visits

**No auth required.** All personalization via localStorage.

---

## Architecture: Two-Column Dashboard

The home page becomes a three-layer layout:

```
┌──────────────────────────────────────────────────────┐
│                   BRIEFING BANNER                     │
│  Stats │ Biggest Move │ Hot Wallet │ P&L Streak       │
│  Just Resolved results                                │
└──────────────────────────────────────────────────────┘
┌──────────────────────────────┐ ┌────────────────────┐
│                              │ │  RESOLVING SOON    │
│       SIGNAL FEED            │ │  countdown cards   │
│                              │ ├────────────────────┤
│  Smart sort (urgency x       │ │  LIVE FLOW         │
│  score x recency)            │ │  volume spikes     │
│                              │ │  active wallets    │
│  Enhanced cards with         │ ├────────────────────┤
│  inline sparklines,          │ │  TOP MOVERS        │
│  urgency borders,            │ │  24h price changes │
│  market stats                │ │                    │
│                              │ │                    │
└──────────────────────────────┘ └────────────────────┘
         ~65% width                   ~35% width
```

**Mobile:** Sidebar collapses to horizontal scrollable strips above the feed. Briefing banner stacks vertically.

---

## Section 1: Briefing Banner

Full-width banner at the top. Answers "what did I miss?" personalized to the user's last visit.

### Time Window
- Uses `localStorage` to store timestamp of last visit
- Briefing covers the period since that timestamp
- First-time visitors see last 6 hours
- Updates `localStorage` timestamp on each page load

### Content — Two Rows

**Row 1 (horizontal, flex layout):**

- **Stat cluster:** New signals count (since last visit), Signal P&L (hypothetical P&L if you'd copied all resolved signals), Resolved count, Win count (e.g., "2/2 Won")
- **Vertical divider**
- **Biggest move:** Market with the largest smart money flow since last visit. Shows market icon, title, flow amount, wallet count, and price change percentage.
- **Vertical divider**
- **Hot wallet:** Most active sharp wallet since last visit. Shows badge tier, name, win rate, and trade count.

**Row 2 (below row 1, separated by horizontal divider):**

- **Signal P&L Streak:** Running track record — "Last 7 days: 14/18 signals won (78%) — +$12.4K hypothetical P&L." Computed server-side from resolved markets and their signal history. Same for all users (no per-user state). This is the primary return-visit hook: users come back to check "did yesterday's signals hit?"
- **Just Resolved results:** Compact horizontal list of recently resolved markets that had signals. Each shows: market title, outcome, signal was right/wrong (green check / red X), hypothetical P&L. Scannable scorecard format. Creates a daily habit of checking results.

### Behavior
- Dismissable via X button (localStorage flag, reappears on next visit)
- Auto-refreshes when page regains focus (visibilitychange event)

---

## Section 2: Sidebar — "Right Now" Panel

Persistent right column (~35% width), sticky on scroll. Three stacked modules.

### 2a. Resolving Soon

Markets with smart money signals that resolve within hours/days.

- Sorted by time remaining (soonest first)
- Color-coded left border: **red** = under 6h, **amber** = under 24h
- Each card shows:
  - Market title (truncated)
  - Countdown timer (updates every 10s, matching existing tick interval)
  - Smart money amount and which side
  - Topic tag pill
- Clicking a card navigates to market detail page
- Data source: existing `/api/resolving-soon` endpoint

### 2b. Live Flow

Two sub-sections showing real-time market activity. Auto-refreshes every 30 seconds.

**Volume Spikes:**
- Markets with abnormal trade velocity right now
- Shown as multipliers of average volume (e.g., "4.2x")
- Progress bar showing relative intensity
- Sorted by spike magnitude
- Surfaces "something is happening" before it becomes a signal
- Data source: new endpoint needed — computes current volume vs trailing average

**Active Sharp Wallets:**
- Wallets with high win rates that have placed multiple trades in the last few hours
- Shows: badge tier (Diamond/Gold/Silver/Bronze), wallet name, trade count
- Clicking navigates to wallet profile page
- Data source: new endpoint needed — aggregates recent trades by wallet, filters by win rate

### 2c. Top Movers

Biggest price changes in the last 24 hours across all tracked markets.

- Simple list: market title + percentage change (green positive / red negative)
- 4-6 items shown
- Clicking navigates to market detail page
- Data source: new endpoint needed — computes 24h price delta per market from price history

### Mobile Behavior
- Resolving Soon → horizontal scrollable strip (existing `ResolvingSoonStrip` component pattern)
- Live Flow → compact ticker-style display
- Top Movers → horizontal scrollable cards
- All appear above the main feed, below the briefing banner

---

## Section 3: Enhanced Signal Feed

The existing alert feed in the main column (~65% width), with four enhancements.

### 3a. Smart Default Sort

New default sort: **urgency x score x recency.**

Formula concept: `sort_score = composite_score * urgency_multiplier * recency_factor`

- `urgency_multiplier`: based on time to resolution. Markets resolving in <6h get highest weight, >30d get lowest.
  - < 1h: 5x
  - < 6h: 3x
  - < 24h: 2x
  - < 7d: 1.5x
  - > 7d: 1x
- `recency_factor`: decays with age of signal. Fresh signals rank higher.
  - < 1h: 1.0
  - 1-6h: 0.9
  - 6-24h: 0.7
  - > 24h: 0.5

Sort options available: **Smart** (default), Newest, Biggest $, Closing Soon.

Active sort stored in `localStorage`.

**Implementation:** Computed client-side from existing alert data (composite_score, end_date, scanned_at). No backend changes needed.

### 3b. Inline Sparkline + Market Stats

Each signal card includes a compact row showing:

- **Mini price chart** (24h sparkline) — reuses existing `Sparkline` component
- **Spread** — current bid/ask spread (tight = easy to follow)
- **24h volume** — market liquidity indicator

These three data points answer "can I actually trade this?" without clicking into the market page. Reduces the decision cost of going deeper.

**Data source:** Existing `/api/market/{conditionId}/live` endpoint already returns price data. Spread and volume may need to be added to the live endpoint response or fetched from price history.

### 3c. Urgency & Type Borders

Left border color on each card:

- **Red (#f85149):** Market resolves in <6h — "act now"
- **Purple (#bc8cff):** Coordinated/cluster flow alert — unusual pattern
- **No border:** Standard signal

Applied via CSS based on `end_date` proximity and `alert_type === "cluster"`.

### 3d. "View market" Link

Separate from the Copy Trade CTA button. Appears as a subtle text link at the right end of the CTA row: "View market →"

- Copy Trade → opens Polymarket (external)
- View market → navigates to PolySpotter market detail page (internal)

This creates the **session depth funnel**: Feed → Market detail → Top holders → Wallet profile → Other signals by this wallet. The rabbit hole that keeps users in-app.

---

## Return-Visit Hooks

Three mechanisms to drive repeat visits, all without auth:

### Signal P&L Streak
- Server-side computation: for all signals in the last 7 days where the market has resolved, compute win/loss and hypothetical P&L (based on entry price from signal vs resolution at $1.00 or $0.00)
- Displayed in the Briefing Banner
- New backend endpoint: `GET /api/signals/track-record?days=7`
- Response: `{ wins, losses, total, win_rate, hypothetical_pnl }`

### Just Resolved Results
- Recently resolved markets that had signals, with outcomes
- New backend endpoint: `GET /api/signals/resolved?limit=5`
- Response: list of `{ market_title, outcome, signal_side, signal_was_correct, entry_price, pnl_per_share }`
- Displayed in the Briefing Banner below the stat cluster

### Persistent Filter Preferences
- All filter state saved to `localStorage`:
  - Sort order (smart/newest/biggest/closing)
  - Severity filter (all/medium+/strong+/very strong)
  - Topic filter (all/specific tag)
  - Resolution window (any/6h/24h/7d)
- Restored on page load
- Partially implemented already — extend to cover new sort options

---

## New Backend Endpoints Needed

| Endpoint | Purpose | Complexity |
|----------|---------|------------|
| `GET /api/signals/track-record?days=7` | Win/loss/P&L of resolved signals | Medium — join signals with market resolutions |
| `GET /api/signals/resolved?limit=5` | Recently resolved signals with outcomes | Medium — similar join, limited results |
| `GET /api/flow/volume-spikes` | Markets with above-average current volume | Medium — compare current vs trailing volume |
| `GET /api/flow/active-wallets` | Sharp wallets with recent multi-trade activity | Low — aggregate recent trades, filter by WR |
| `GET /api/markets/top-movers?period=24h` | Biggest 24h price changes | Low — compute from price history |

Existing endpoints that can be reused:
- `/api/resolving-soon` — already exists for Resolving Soon sidebar
- `/api/spotlight` — may overlap with Briefing "biggest move"
- `/api/market/{id}/live` — for inline sparklines (already used)

---

## Out of Scope

- User accounts / authentication
- Push notifications / service workers
- Bookmarked/watchlist markets
- Social features (comments, sharing beyond current share button)
- News junkie / observer persona features
- Mobile app

---

## Dependencies & Risks

- **Signal P&L computation** requires reliable market resolution data. Verify that the backend tracks resolution outcomes consistently.
- **Volume spike detection** needs a baseline. Options: trailing 7-day average, or use the existing `pre_event_volume_spike` strategy's logic.
- **Inline sparklines on every card** means more API calls on the home page. Consider batch-fetching live data for all visible markets, or including sparkline data in the alerts response.
- **Smart sort is client-side** — this means all alerts for the current page need end_date and scanned_at in the response (already present in alert objects).
