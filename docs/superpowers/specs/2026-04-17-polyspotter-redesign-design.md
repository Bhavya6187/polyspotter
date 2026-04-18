# PolySpotter Redesign — Design Spec

**Date:** 2026-04-17
**Branch:** `feat/polyspotter-redesign`
**Scope:** Replace the desktop `/` Home surface and ship three new mobile routes (`/signals`, `/discover`, `/watchlist`) implementing the [design_handoff_polyspotter](../../../design_handoff_polyspotter/) reference. Add supporting backend endpoints.

---

## 1. Goal

Ship the PolySpotter intelligence-dashboard redesign in the existing Next.js frontend and FastAPI backend. Match the reference design's visual fidelity and interaction behavior. Keep the backend's existing "alert" vocabulary intact but expose new signal-shaped endpoints that pre-join the data the new UI needs.

## 2. Scope

### In scope
- Full replacement of `frontend/src/app/home-client.jsx` with the new Home layout.
- Three new mobile-first routes: `/signals`, `/discover`, `/watchlist` (also rendered at desktop widths).
- Bottom tab bar (mobile only) navigating between the 4 routes with real `<Link>` changes.
- New FastAPI endpoints: `/api/signals`, `/api/signals/top`, `/api/markets/movers`, `/api/topics`, `/api/digest`, `/api/ticker/recent`. Existing `/api/wallets/top` reused.
- Design-token overhaul in `globals.css` (surface / border / text / accent / bullish / bearish / warning / info / violet — exact values from the reference).
- DM Sans + JetBrains Mono fonts via `next/font/google`.
- localStorage watchlist (CRUD via client-side `lib/watchlist.js` + `useWatchlist` hook).
- Signal card expand-on-click "Why" panel.
- Live polling of `/api/ticker/recent` (5s interval); client-side CSS animations for live feel.

### Out of scope (deferred)
- Tweaks panel (hero-variant / accent-color / density toggles).
- WebSocket `/ws/ticker`.
- Server-side watchlist persistence / auth.
- Deleting orphaned current components (will happen in a follow-up cleanup PR).
- Real Copy-trade execution UX — button opens Polymarket URL in a new tab (via `llm_copy_action.market_url`, falling back to `market_url`).
- Forward tab-tap scroll-position memory — we rely on Next's default back-button restoration only.

### Won't ship
- Light mode is not part of the spec (design explicitly says "dark is the hero experience"). Existing light theme stays functional but is not retuned to the new palette.

## 3. Architecture

### 3.1 Routing (Next.js App Router)

```
app/page.jsx          → server component → <HomeClient />
app/signals/page.jsx  → server component → <SignalsClient />
app/discover/page.jsx → server component → <DiscoverClient />
app/watchlist/page.jsx → server component → <WatchlistClient />
```

`AppShell` wraps every client component and renders:
- `TopNav` (hidden on `<md`)
- `MobileTabBar` (hidden on `≥md`)

Breakpoint: Tailwind default `md: 768px`. Mobile ≤767, desktop ≥768.

### 3.2 Component tree

```
<AppShell>
  <TopNav />                             {/* hidden md:flex */}
  <main>
    {page content}
  </main>
  <MobileTabBar />                       {/* md:hidden */}
</AppShell>

HomeClient (at /)
 ├─ DigestBanner
 ├─ Top3Hero                             {/* flex snap-x on mobile; grid-cols-3 on md+ */}
 │   └─ Top3Card × 3
 ├─ MoversStrip (horizontal scroll)
 │   └─ MoverCard
 ├─ TopicTiles                           {/* hidden on <md, grid on md+ */}
 │   └─ TopicTile
 ├─ TopicFilterChips                     {/* always visible, scrolls horizontally */}
 ├─ SignalFeed                           {/* topic-filtered */}
 │   └─ SignalCard
 └─ RightRail                            {/* hidden md:block */}
     ├─ DigestBlock
     ├─ SharpestWallets
     ├─ WatchlistBlock
     └─ LiveTicker

SignalsClient (at /signals)
 └─ SignalFeed (no filters or hero; header: "Signals · N · live stream")

DiscoverClient (at /discover)
 └─ TopicTiles (2-col mobile, 3-col md, 6-col xl)

WatchlistClient (at /watchlist)
 └─ WatchlistBlock (full-page variant with remove button per row)
```

### 3.3 New files

**Frontend**

```
frontend/src/app/signals/page.jsx
frontend/src/app/signals/signals-client.jsx
frontend/src/app/discover/page.jsx
frontend/src/app/discover/discover-client.jsx
frontend/src/app/watchlist/page.jsx
frontend/src/app/watchlist/watchlist-client.jsx

frontend/src/components/AppShell.jsx
frontend/src/components/TopNav.jsx
frontend/src/components/MobileTabBar.jsx
frontend/src/components/DigestBanner.jsx
frontend/src/components/Top3Hero.jsx
frontend/src/components/Top3Card.jsx
frontend/src/components/MoversStrip.jsx
frontend/src/components/MoverCard.jsx
frontend/src/components/TopicTiles.jsx
frontend/src/components/TopicTile.jsx
frontend/src/components/TopicFilterChips.jsx
frontend/src/components/SignalFeed.jsx
frontend/src/components/SignalCard.jsx
frontend/src/components/RightRail.jsx
frontend/src/components/DigestBlock.jsx
frontend/src/components/SharpestWallets.jsx
frontend/src/components/WatchlistBlock.jsx
frontend/src/components/LiveTicker.jsx

frontend/src/components/ui/Chip.jsx
frontend/src/components/ui/StrengthBars.jsx
frontend/src/components/ui/WalletAvatar.jsx
frontend/src/components/ui/CountdownText.jsx
frontend/src/components/ui/CopyButton.jsx
frontend/src/components/ui/BookmarkButton.jsx

frontend/src/lib/watchlist.js
frontend/src/lib/signalAdapter.js
frontend/src/lib/signalLabels.js      {/* SIGNAL_LABELS + TAG_TO_TOPIC maps */}

frontend/src/hooks/useWatchlist.js
frontend/src/hooks/useDigest.js
frontend/src/hooks/useSignalFeed.js
frontend/src/hooks/useLiveTicker.js
```

**Backend**

```
backend/signals.py        {/* Signal shape + Alert→Signal adapter + tier/color helpers */}
backend/topics.py         {/* TAG_TO_TOPIC map + topic activity aggregation */}
backend/digest.py         {/* since-last-visit summary builder */}
```

**Routes added to `backend/app.py`** (no existing routes modified):

```
GET  /api/signals
GET  /api/signals/top
GET  /api/markets/movers
GET  /api/topics
GET  /api/digest
GET  /api/ticker/recent
```

### 3.4 Files modified (replaced)

```
frontend/src/app/home-client.jsx         → rewritten
frontend/src/app/page.jsx                → loader tweaks for new initial fetches
frontend/src/app/layout.jsx              → DM Sans + JetBrains Mono fonts
frontend/src/app/globals.css             → design tokens added
frontend/src/lib/api.js                  → new fetchers for new endpoints
```

### 3.5 Files reused unchanged

`components/Sparkline.jsx`, `components/CommandPalette.jsx`, `components/ThemeToggle.jsx`, `hooks/useMediaQuery.js`, `hooks/useCountdown.js`, `lib/pseudonym.js`, `lib/slugify.js`, `lib/tiers.js`.

### 3.6 Orphaned files (not deleted in this PR)

Kept in-tree, marked `// TODO(cleanup): unused after polyspotter redesign 2026-04-17`:
`AlertTable.jsx`, `AlertList.jsx`, `AlertRow.jsx`, `Filters.jsx`, `Pagination.jsx`, `ResolvingSoonStrip.jsx`, `HeroSpotlight.jsx`, `TopicNav.jsx`, `Ticker.jsx`, `MarketPulse.jsx`. A follow-up PR deletes them once verified unused elsewhere.

## 4. Data contracts

### 4.1 Canonical `Signal` shape (server-generated)

Used by `/api/signals`, `/api/signals/top`, `/api/digest.topSignals`:

```ts
Signal {
  id: string                   // alerts.id, stringified
  createdAt: string            // iso8601
  market: {
    conditionId: string
    title: string
    topic: string              // e.g. "Politics", "Crypto"
    icon: string               // emoji, from TAG_TO_TOPIC
    endDate: string | null     // iso8601
    yesPrice: number
    priceChange24h: number
    volume24h: number
    candles: number[]          // 32 points
  }
  wallet: {
    addr: string
    alias: string              // from lib/pseudonym.js
    tier: "legend" | "sharp" | "prov"
    winRate: number            // 0..1
    pnl: number
    bets: number
    color: string              // #hex
  }
  side: "YES" | "NO" | null    // null if no trades joined
  entryPrice: number | null
  stakeUSD: number
  score: number                // composite_score
  rating: 1 | 2 | 3 | 4 | 5
  why: string                  // llm_summary → cluster_headline → llm_headline
  signals: string[]            // strategy names (keys in SIGNAL_LABELS)
  bullets: string[]            // llm_bullets; padded to length 3 if shorter
  priceAtAlert: number | null  // same as entryPrice
  priceNow: number | null
  returnPct: number            // YES: round((1-entry)/entry*100); NO: round(entry/(1-entry)*100)
}
```

### 4.2 Other response shapes

```ts
Mover {
  conditionId, title, topic, icon, yesPrice, priceChange24h, volume24h, candles
}

Topic {
  name, icon, signals: number, volume24h: number, trend: number, spark: number[]
}

TickerTrade {
  id, side: "BUY"|"SELL", amount: number, market: string, price: number,
  wallet: { alias, tier, color }, timestamp
}

Digest {
  since: string                // iso8601 echoed back
  newSignals: number
  strongSignals: number
  topSignals: Signal[]         // up to 3
  biggestMover: Mover | null
}
```

### 4.3 Server-side derivations

- **rating bucket** (on `composite_score`):
  - `≥25 → 5`  ·  `≥18 → 4`  ·  `≥12 → 3`  ·  `≥7 → 2`  ·  else `1`
- **tier**: `legend` if `winRate≥0.88 && pnl≥300_000`; `sharp` if `winRate≥0.72`; else `prov`
- **color**: deterministic hash of wallet address → one of `[#f59e0b, #00c26a, #8b5cf6, #3b82f6, #ec4899, #06b6d4]`
- **side / entryPrice**: from the earliest trade on the alert; if no trades joined, return `null` and the frontend renders `—`
- **topic + icon**: derived from `alerts.tags[0]` via `TAG_TO_TOPIC` map: `Politics→⚖️, Economics→📈, Crypto→Ξ, NBA→🏀, Geopolitics→🛢️, Science→🚀, Soccer→⚽`. Unmapped tags default to `{topic:"General", icon:"📈"}`.
- **returnPct**: see formulae in shape above. If `entryPrice` is null, return `0` and the frontend hides the `+X%` suffix.
- **candles**: 32-point array from `price_history` table; if fewer points, pad from oldest with the first value.
- **why**: `llm_summary` preferred; fallback `cluster_headline`; final fallback `llm_headline`.

### 4.4 Endpoint query params

| Endpoint | Query params |
|---|---|
| `/api/signals` | `topic?:str, limit?=20, offset?=0, min_rating?:1..5, resolves_within?:6h\|24h\|7d` |
| `/api/signals/top` | none — always returns 3 |
| `/api/markets/movers` | `limit?=6` |
| `/api/topics` | none |
| `/api/digest` | `since:iso8601` (required) |
| `/api/ticker/recent` | `limit?=20` |

## 5. State & interactions

### 5.1 Component-local state

| Component | State |
|---|---|
| `SignalCard` | `expanded: boolean` (Why panel) |
| `SignalFeed` | `topicFilter: "All"\|<name>`, `ratingFilter: "all"\|"strong+"\|"resolving-soon"` |
| `Top3Hero` | none |
| `MoversStrip` | none (CSS-only pulse animation) |
| `DigestBanner` | reads `useDigest()` |
| `WatchlistBlock` | reads `useWatchlist()` → fetches each `/api/market/{id}/live` |
| `LiveTicker` | reads `useLiveTicker()` (polls every 5s) |
| `CountdownText` | reads `useCountdown()` (re-ticks every 30s) |

### 5.2 URL state

- `/?topic=<name>` → preselects the topic filter.
- `/signals?topic=<name>` → same.
- No URL state on `/discover` or `/watchlist`.

### 5.3 Click behaviors

| Action | Behavior |
|---|---|
| Tap topic chip | `setTopicFilter`, push `?topic=<name>`, refetch feed |
| Tap Why panel | Toggle `expanded`; `max-height` + opacity transition 200ms ease-out |
| Tap bookmark icon | `useWatchlist().toggle(conditionId)`; scale+glow animation; optimistic watchlist update |
| Tap Copy trade | Opens `llm_copy_action.market_url` (fallback `market_url`) in new tab; flashes copy toast |
| Tap feed card (not button/link) | Navigates to `/alert/{id}` |
| Tap mobile tab | Real `<Link>` navigation — Next handles scroll |

### 5.4 Live flourishes (client-side only)

- **Mover pulse** — CSS `@keyframes mover-pulse` on last-candle circle; staggered `animation-delay` per card; 400ms opacity 0.4→1; infinite loop, 6–10s period.
- **Digest dot** — reuses existing `.animate-pulse-live` (1.6s scale + opacity).
- **Countdown** — `useCountdown` re-renders at 30s; turns `--bearish` red when `<1h`.
- **Top 3 #1 glow** — static `box-shadow: 0 0 20px rgba(0,194,106,0.2), 0 0 40px rgba(0,194,106,0.05)`.
- **Ticker new-trade fade-in** — `fade-up` keyframe applied to newly-prepended rows.

## 6. Design tokens

Added to `frontend/src/app/globals.css` under `:root, :root.dark`:

```css
--surface-0:      #05080f;
--surface-1:      #0a0f1c;
--surface-2:      #111827;
--surface-card:   #0f1624;
--surface-card-hover: #141c2e;
--border:         rgba(255,255,255,0.08);
--border-subtle:  rgba(255,255,255,0.05);
--border-strong:  rgba(255,255,255,0.14);
--text-primary:   #f5f7fa;
--text-secondary: rgba(235,235,245,0.6);
--text-muted:     rgba(235,235,245,0.38);
--accent:         #00c26a;
--accent-hover:   #00a85c;
--accent-subtle:  rgba(0,194,106,0.14);
--accent-glow:    rgba(0,194,106,0.25);
--bullish:        #00c26a;
--bearish:        #ef4444;
--warning:        #f59e0b;
--info:           #3b82f6;
--violet:         #8b5cf6;
--radius-sm: 6px;
--radius:    10px;
--radius-lg: 14px;
--radius-xl: 20px;
--shadow-card: 0 4px 14px rgba(0,0,0,0.25);
--shadow-glow: 0 0 20px rgba(0,194,106,0.2), 0 0 40px rgba(0,194,106,0.05);
--font-body:  "DM Sans", system-ui, sans-serif;
--font-mono:  "JetBrains Mono", ui-monospace, monospace;
```

Body background:
```css
body {
  background:
    radial-gradient(ellipse at 20% 0%, rgba(0,194,106,0.08), transparent 55%),
    radial-gradient(ellipse at 80% 60%, rgba(59,130,246,0.06), transparent 55%),
    var(--surface-0);
}
```

Tailwind 4 integration via `@theme` block in `globals.css` maps CSS vars to utility classes (`bg-surface-card`, `text-accent`, etc.). Inline `var(--...)` usage also remains valid.

Fonts loaded via `next/font/google` in `app/layout.jsx` with `DM_Sans` and `JetBrains_Mono` — self-hosted by Next, no runtime external request.

Light-mode values are not retuned in this pass. Existing light theme continues to work with its current palette.

## 7. Accessibility

- Every icon-only button has `aria-label`.
- Bookmark button announces state via `aria-pressed`.
- Why panel uses `aria-expanded` + `aria-controls` pointing at the bullets list.
- Strength bars wrap with `role="meter"` + `aria-valuenow` + `aria-valuemin=1` + `aria-valuemax=5`.
- Up/down price direction uses `▲` / `▼` glyphs in addition to color.
- Tab bar is a `<nav aria-label="Main">`.
- Live ticker uses `aria-live="polite"` so new rows announce without stealing focus.
- Color contrast: `--text-secondary` on `--surface-card` must pass WCAG AA (verify once theme is wired; if it fails, bump to `rgba(235,235,245,0.72)`).

## 8. Testing

### 8.1 Backend (`backend/test_endpoints.py`)

- `/api/signals` returns proper `Signal` shape; rating bucketing respects the table; YES/NO `returnPct` computed correctly; topic filter works.
- `/api/signals/top` always returns exactly 3.
- `/api/markets/movers` excludes expired markets; picks by `abs(priceChange24h)`; falls back to volume-order when fewer than `limit` markets have non-null price change.
- `/api/topics` returns the 6 canonical topics with non-null `signals` counts.
- `/api/digest?since=<past>` returns `newSignals > 0`; `since=<future>` returns `0`.
- `/api/ticker/recent` returns ordered trades, newest first.

### 8.2 Frontend

- `cd frontend && npm run lint` — must pass.
- Manual verification checklist (pass/fail, evidence = screenshot):
  - [ ] `/` renders desktop layout at 1440px matching `screenshots/desktop-home.png` + `screenshots/desktop-feed.png`.
  - [ ] `/` at 390px renders mobile Home matching `screenshots/mobile-overview.png` phone #1.
  - [ ] `/signals` at 390px matches mobile phone #2.
  - [ ] `/discover` at 390px matches mobile phone #3.
  - [ ] Mobile tab bar switches between 4 routes with scroll preserved on back nav.
  - [ ] Top 3 carousel snaps at 290px widths on mobile.
  - [ ] Topic filter chip → feed refetches with correct query.
  - [ ] Why panel expand/collapse animates.
  - [ ] Bookmark toggle persists across reload (localStorage).
  - [ ] Countdown turns red under 1h.
  - [ ] Digest banner shows correct count on visit after a delay.
  - [ ] LiveTicker new-trade fade-in visible when new trades arrive during 5s polling.

No new unit-test framework for frontend components; if it becomes necessary, it's a follow-up.

## 9. Risks

1. **Alert→Signal mapping fragility.** Alerts without joined trades have `side=null, entryPrice=null`. Frontend renders `—`; card still shows. Covered.
2. **Stale priceNow.** `/api/signals` pre-joins from the live cache. If cache is stale, `+Xc` delta on cards is stale. Acceptable for v1.
3. **Movers fallback.** If fewer than `limit` markets have non-null `priceChange24h`, endpoint falls back to most-recently-active markets by `volume24h`.
4. **First visit digest.** No `lastVisitTs` → treat as "last 24h" window.
5. **iOS Safari bottom toolbar** overlaps fixed tab bar. Use `padding-bottom: env(safe-area-inset-bottom)` on `MobileTabBar`.
6. **Signal vs Alert vocabulary drift.** `backend/signals.py` module docstring documents the Alert→Signal mapping in one place; future changes update both together.
7. **Scroll restoration across tab navigation.** Next's default back-button restoration is the only guarantee; forward tab-tap goes to top. Acceptable for v1.
8. **Tailwind 4 `@theme` maturity.** If unexpected issues arise with `@theme` var mapping, fall back to `bg-[var(--surface-card)]` arbitrary values. Plan A is `@theme`; Plan B is arbitrary values. Either ships.

## 10. Rollout

- Single PR on `feat/polyspotter-redesign` branch (full replacement; no half-state).
- PR description includes before/after screenshots at desktop 1440px and mobile 390px.
- Orphaned components kept in-tree with `TODO(cleanup)` comments; deleted in a follow-up PR.
- No feature flag. No database migration beyond what's already in `backend/schema.sql` (all new endpoints are read-only aggregations of existing tables).

## 11. Open questions (none blocking)

All major decisions are locked via the Q&A:
- Q1: Full replacement of Home → **A**
- Q2: Dedicated mobile routes → **B**
- Q3: Server-side signal-shaped endpoints → **B**
- Q4: localStorage-only watchlist → **B**
- Q5: Polling ticker only → **A**
- Q6a: Skip Tweaks panel → **A**
- Q6b: Leave orphaned components in place → **B**
