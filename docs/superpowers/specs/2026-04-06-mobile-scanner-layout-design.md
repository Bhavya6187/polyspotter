# Mobile Scanner Layout — Design Spec

**Date:** 2026-04-06
**Goal:** Increase mobile information density (2-3x more alerts visible above the fold) and enhance quick-share engagement — all without login, and without changing the desktop experience.

---

## Principles

- **Mobile-only changes** — All modifications scoped to `< sm` (640px) breakpoint. Desktop layout untouched.
- **Scan speed over detail** — Default to compact, expand on demand.
- **No auth required** — Engagement features use localStorage and native browser APIs.
- **Follow existing patterns** — Use the project's existing CSS custom properties, `sm:` breakpoint conventions, and component structure.

---

## Section 1: Hero Compression

**Problem:** HeroSpotlight (~120px) + Ticker (~40px) + ResolvingSoonStrip (~100px) = ~260px before any alerts. Over 60% of the mobile viewport.

**Changes:**

### 1.1 Hide Ticker on mobile
- Add `hidden sm:block` to the Ticker section in `home-client.jsx`.
- Ticker data duplicates the alert feed; it's useful as ambient motion on desktop but wastes space on mobile.

### 1.2 Compact HeroSpotlight on mobile
- **File:** `HeroSpotlight.jsx` → `SpotlightSlide`
- Reduce padding: `px-5 py-5` → `px-4 py-3 sm:px-5 sm:py-5`
- Hide sparkline on mobile: add `hidden sm:block` to the sparkline container.
- Remove "Biggest move right now" label on mobile: wrap in `hidden sm:block`.
- Keep carousel dots and auto-rotation unchanged.

### 1.3 Compact ResolvingSoonStrip on mobile
- **File:** `ResolvingSoonStrip.jsx` → `ResolvingCard`
- Reduce padding: `px-4 py-3` → `px-3 py-2 sm:px-4 sm:py-3`
- Shrink countdown: `text-lg` → `text-sm sm:text-lg`
- Reduce `minWidth`: 200 → 160 on mobile (use inline style with a CSS variable or conditional)

**Result:** Hero area shrinks from ~260px to ~140px on mobile.

---

## Section 2: Compact Alert Cards (Home Feed)

**Problem:** Each `MarketGroupCard` is ~300-400px on mobile (headline, wallet badge, bullets, CTA, tags). Users see 1-2 cards on screen.

**Changes:**

### 2.1 Two-tier card display
- **File:** `AlertList.jsx` → `MarketGroupCard`
- Add `expanded` state to `MarketGroupCard`, default `false` on mobile, `true` on desktop.
- Use `useState` with a media query check: `window.matchMedia('(min-width: 640px)').matches` for initial value (wrapped in useEffect to avoid SSR mismatch — default to `false`, set to `true` on mount if desktop).

### 2.2 Compact view (collapsed state, ~70px)
- **Row 1 (existing header):** Market image (24px, down from 32px on mobile) + StrengthMeter + title (truncated) + resolution badge + relative time. Already exists — just keep as-is.
- **Row 2 (new compact summary):** Inside the card body area (`px-5 pb-4`), replace the full `AlertEntry` with a single-line summary:
  - WalletBadge (compact, inline) + bet summary text (`$7,259 on No at 89¢`) + PriceMovement + share icon button (far right)
  - All on one flex row with `items-center`, `text-sm`, truncation on the bet summary.
- **Expand indicator:** Small chevron (▸) or "details" text at the right edge of Row 2.

### 2.3 Expanded view (tap to toggle)
- Clicking the card body (not the header link) toggles `expanded`.
- When expanded, render the full `AlertEntry` content (bullets, CTA, payout) — identical to current behavior.
- Add `onClick` to the card body div with `e.stopPropagation()` awareness (don't interfere with header link or CTA).

### 2.4 Auto-expand first card
- If `index === 0 && rating >= 3` (current `isHero` logic), set initial `expanded` to `true` regardless of viewport.

### 2.5 Remove tag pills from card footer on mobile
- Wrap the footer tag section in `hidden sm:flex` to hide on mobile.
- "View market" link in footer stays visible.

**Result:** 5-6 cards visible on screen instead of 1-2.

---

## Section 3: Market Detail Page

**Problem:** Header takes ~250px (large thumbnail, separate mobile outcome row, description). Sidebar (chart, stats, holders) is buried below all alerts on mobile.

**Changes:**

### 3.1 Sticky outcome bar
- **File:** `market-page-client.jsx`
- Add an intersection observer on the header element.
- When the header scrolls out of view, show a sticky bar (`position: sticky; top: 0; z-index: 10`) containing:
  - Market title (truncated, `text-sm font-semibold`)
  - Outcome prices inline: `YES 17¢ / NO 84¢` (compact, `text-xs`)
  - Background: `var(--surface-0)` with bottom border
- Mobile only: wrap in `sm:hidden`.
- The bar disappears when the header re-enters the viewport.

### 3.2 Compact outcome pills on mobile
- Keep the separate mobile outcome row (`sm:hidden`) and desktop inline pills (`hidden sm:flex`).
- On the mobile outcome row, reduce pill text: `text-lg` → `text-base`.
- Reduce pill vertical padding: `py-1.5` → `py-1`.
- This saves ~15px while keeping the layout robust across screen widths.

### 3.3 Shrink thumbnail on mobile
- Change thumbnail dimensions: `w-[48px] h-[48px] sm:w-[72px] sm:h-[72px]`.
- Update the Image component's width/height props conditionally or use CSS sizing with `fill` + constrained container.

### 3.4 Reorder sidebar on mobile
- On mobile (below `lg:` breakpoint, where the grid becomes single column), render the `PriceChart` component between the header and the "Notable Trades" section.
- Use a pattern like:
  ```jsx
  {/* Mobile: chart before alerts */}
  <div className="lg:hidden mb-4">
    <PriceChart ... />
  </div>
  
  {/* Two-column grid */}
  <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
    <section>...</section>
    <aside>
      {/* Desktop: chart in sidebar */}
      <div className="hidden lg:block">
        <PriceChart ... />
      </div>
      <MarketStats ... />
      ...
    </aside>
  </div>
  ```
- PriceChart renders once on mobile (above alerts) and once on desktop (in sidebar). Only one is visible at a time via `hidden/block` classes.

**Result:** ~80px saved in header. Price chart visible immediately when evaluating trades.

---

## Section 4: Enhanced Quick-Share

**Problem:** Share button only copies URL to clipboard. No native share sheet. Only present on alert cards, not on market detail page.

**Changes:**

### 4.1 Native Web Share API
- **File:** `ShareButton.jsx`
- Check `navigator.share` availability.
- When available, call `navigator.share({ title, text, url })` instead of clipboard copy.
- Props change: add `title` and `text` props to `ShareButton`.
  - Alert card: `title="PolySpotter: {market_title}"`, `text="Sharp money alert: {betSummary}"`
  - Market page: `title="PolySpotter: {market_title}"`, `text="{outcome} at {price} — {signalCount} signals"`
- Fallback to current clipboard behavior when `navigator.share` is unavailable.
- Catch `AbortError` (user dismissed share sheet) silently.

### 4.2 Share on market detail page
- Add a `ShareButton` to the nav bar in `market-page-client.jsx`, between the back link and theme toggle.
- Icon-only on mobile (no "Share" text), with tooltip on desktop.
- Shares the market page URL.

### 4.3 Share on compact alert cards
- In the compact card view (Section 2.2, Row 2), place a share icon button at the far right.
- Icon-only, no label. Uses the same `ShareButton` with `compact` and a new `iconOnly` prop.
- `onClick` stops propagation to prevent card expansion.

### 4.4 Icon-only on mobile
- Add an `iconOnly` prop to `ShareButton`. When true, render only the share icon (no "Share"/"Copied" text).
- Compact cards and market page nav use `iconOnly` on mobile.
- Existing alert card share buttons in expanded view keep their current label.

---

## Section 5: Collapsible Filters with Memory

**Problem:** Three filter rows take ~120px. Topic row can wrap to 2+ lines. Users must re-select filters every visit.

**Changes:**

### 5.1 Collapsible on mobile
- **File:** `Filters.jsx`
- Add `collapsed` state, default `true` on mobile, `false` on desktop.
- Collapsed view: single row with a "Filters" button showing active count badge.
  - E.g., `Filters` (no active) or `Filters (2)` (2 active filters).
  - Tapping toggles the full filter panel.
- Expanded view: identical to current 3-row layout.
- Desktop (`sm:` and up): always expanded, collapse button hidden.

### 5.2 Active filter summary
- When collapsed and filters are active, show small inline pills summarizing the active selections.
- E.g., `< 6h · Strong+ · Sports` in `text-xs` next to the Filters button.
- Tapping any summary pill also expands the filter panel.

### 5.3 localStorage persistence
- On filter change, write to `localStorage.setItem('polyspotter_filters', JSON.stringify(filters))`.
- On mount (`useEffect`), read from localStorage and apply as initial filter state.
- **File:** `home-client.jsx` — update `useState` initializer for `filters` to read from localStorage.
- Key: `polyspotter_filters`, value: `{ tag: string, resolvesIn: string, minScore: string }`.
- Wrapped in try/catch for private browsing / storage-disabled environments.

---

## Files Modified

| File | Changes |
|------|---------|
| `home-client.jsx` | Hide ticker on mobile, localStorage filter init |
| `HeroSpotlight.jsx` | Compact padding, hide sparkline/label on mobile |
| `ResolvingSoonStrip.jsx` | Compact padding, smaller countdown on mobile |
| `AlertList.jsx` | Compact/expand card behavior, hide tags on mobile |
| `ShareButton.jsx` | Native share API, iconOnly prop, title/text props |
| `Filters.jsx` | Collapsible on mobile, active summary pills |
| `market-page-client.jsx` | Sticky outcome bar, compact pills, smaller thumb, chart reorder, share in nav |

## Files Not Modified

- No new files created (all changes are to existing components).
- No backend changes.
- No new dependencies.
- Desktop experience unchanged.

---

## Testing Plan

1. **Mobile viewport (375px, 390px, 414px):** Verify hero compression, compact cards, filter collapse, sticky bar, share sheet.
2. **Desktop viewport (1024px+):** Verify no visual changes from current state.
3. **Breakpoint boundary (640px):** Verify clean transition between mobile/desktop behaviors.
4. **localStorage:** Verify filter persistence survives page reload, works in private browsing (graceful fallback).
5. **Web Share API:** Test on iOS Safari, Android Chrome (native sheet). Test fallback on desktop Chrome/Firefox (clipboard copy).
6. **Card expand/collapse:** Verify tap targets don't conflict with header link, CTA button, or share button.
7. **Sticky bar:** Verify appears/disappears correctly on scroll, doesn't overlap content.
8. **SSR compatibility:** Verify no hydration mismatches from `window.matchMedia` or `localStorage` reads (use useEffect guards).
