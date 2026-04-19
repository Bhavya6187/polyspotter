# Today's Top 3 — Design Spec

**Date:** 2026-04-18
**Status:** Approved

## Summary

Replace the auto-rotating `HeroSpotlight` on the home page with a static "Today's top 3" grid. Each slot highlights a different angle on the top alerts: a sharp-wallet **Highest Conviction** pick, a **Coordinated Flow** pick (linked wallets), and a **Timing Edge** pick (resolution imminent). `TopicNav` is untouched; the richer "browse by topic" block from the mockup is out of scope for this iteration.

## Goals

- Surface three complementary, copy-worthy setups at a glance.
- Make the selection rule explicit (category per card) rather than a single score ranking.
- Keep the visual density and polish of the supplied mockup.
- Change the backend where it simplifies the frontend — we own both sides.

## Non-goals

- No replacement for `TopicNav` or a new per-tag analytics strip.
- No change to how `llm_filter.py` scores or generates copy actions.
- `Copy YES / NO` button is a visual affordance that links to the alert detail page — no deep link to Polymarket, no modal.
- `HeroSpotlight` and `useSpotlight` stay in the codebase; we just stop mounting them on the home page.

## Architecture

**Backend**

- New endpoint `GET /api/top3` in [backend/app.py](../../backend/app.py) that returns exactly 3 categorized alerts (or fewer only if no qualifying alerts exist at all in the last 24h — see Fallbacks).
- Tests in [backend/test_endpoints.py](../../backend/test_endpoints.py).

**Frontend**

- New component `TopThree.jsx` in [frontend/src/components/](../../frontend/src/components/).
- New hook `useTopThree.js` in [frontend/src/hooks/](../../frontend/src/hooks/), modeled on `useSpotlight` (polls every 60s, tracks `lastUpdated`).
- New `fetchTopThree()` helper in [frontend/src/lib/api.js](../../frontend/src/lib/api.js).
- In [frontend/src/app/home-client.jsx](../../frontend/src/app/home-client.jsx), replace `<HeroSpotlight />` with `<TopThree />`. Imports of `HeroSpotlight` / `useSpotlight` are removed from the home page but the files remain.

**Data flow**

```
home page SSR
  → renders <TopThree />
    → useTopThree polls GET /api/top3 (on mount, then every 60s)
    → renders 3 cards in a grid + header + "how we pick these" popover
```

## Backend: `GET /api/top3`

### Candidate pool

Unresolved alerts meeting all of:

- `end_date IS NOT NULL AND end_date > NOW()`
- `created_at > NOW() - INTERVAL '1 day'`
- latest `price_candles.p` is either NULL or strictly between 0.03 and 0.97 (not effectively settled)

Same exclusion rules as the existing `/api/spotlight` endpoint to stay consistent with other surfaces.

### Per-alert enrichment

For each candidate alert we need:

- `composite_score`, `total_usd`, `end_date`, `market_title`, `condition_id`, `event_slug`, `market_image`
- `llm_summary`, `llm_copy_action` (parsed JSON)
- Leading wallet address + `wallet_profiles.win_rate` + `wallet_profiles.total_pnl` + `wallet_profiles.total_invested` (the tier util on the frontend needs `total_invested`, not `total_pnl`)
- Distinct wallet count on the alert (`COUNT(DISTINCT at2.wallet) FROM alert_trades at2 WHERE at2.alert_id = a.id`)
- Latest `price_candles.p` (current price)
- Set of signal types on the alert (`SELECT DISTINCT strategy FROM signals WHERE alert_id = a.id`)
- First market tag (for the pill label) — read the `alerts.tags` TEXT column (JSON array, e.g. `'["Sports","NBA"]'`), parse, take index 0. Return `null` if array is empty or missing.

### Category scoring

For each candidate we compute three optional scores. A score is `NULL` if the alert doesn't qualify for that category.

- `timing_edge_score = composite_score` if the alert has a `timing_relative_resolution` signal **OR** `end_date <= NOW() + INTERVAL '6 hours'`.
- `coordinated_score = composite_score` if the alert has a `wallet_clustering` **OR** `concentrated_one_sided` signal **OR** `wallet_count >= 2`.
- `conviction_score = composite_score` if leading wallet's `win_rate >= 0.7` **AND** `total_pnl >= 50000`.

### Selection

In order, without duplicates:

1. **TIMING_EDGE** = alert with highest non-null `timing_edge_score`.
2. **COORDINATED_FLOW** = alert with highest non-null `coordinated_score` among remaining.
3. **HIGHEST_CONVICTION** = alert with highest non-null `conviction_score` among remaining.

**Fallbacks.** For any bucket still empty after step 1–3, fill from remaining candidates ordered by `composite_score DESC`. The card keeps its bucket label (e.g., even a fallback into the `HIGHEST_CONVICTION` slot is labeled `HIGHEST_CONVICTION`). If the candidate pool is fully exhausted, return fewer than 3; frontend hides empty slots.

### Response shape

Array of up to 3 objects, ordered `HIGHEST_CONVICTION`, `COORDINATED_FLOW`, `TIMING_EDGE` (stable display order regardless of selection order):

```json
{
  "category": "HIGHEST_CONVICTION",
  "rank": 1,
  "strength": 4,
  "id": 123,
  "market_title": "Will Iran close the Strait of Hormuz before May 1?",
  "condition_id": "0x...",
  "event_slug": "iran-hormuz-may-1",
  "market_image": "https://.../img.png",
  "primary_tag": "Geopolitics",
  "end_date": "2026-04-18T21:16:00Z",
  "llm_summary": "92% win-rate wallet stacked $48k on YES…",
  "llm_copy_action": { "outcome": "YES", "entry_price": 0.18 },
  "total_usd": 48000,
  "latest_price": 0.26,
  "wallet": {
    "address": "0x...",
    "win_rate": 0.92,
    "total_pnl": 482000,
    "total_invested": 520000
  }
}
```

- `rank` is 1/2/3 matching display order.
- `strength` is `min(4, floor(composite_score / 25) + 1)` — 4 bars filled at `composite_score >= 75`.
- Pseudonym is **not** returned by the backend. The frontend computes it via existing `computeTier(win_rate, total_invested)` + `walletPseudonym(address, tier)` in [frontend/src/lib/tiers.js](../../frontend/src/lib/tiers.js) / [frontend/src/lib/pseudonym.js](../../frontend/src/lib/pseudonym.js) so the card label matches how wallets are rendered elsewhere (e.g. `Sharp_0xabc12`). The mockup's single-word labels (`RHINO`, `ORACLE`, `CICADA`) are illustrative only.

### No server timestamp

Frontend tracks its own `lastUpdated` from the last successful fetch. No `refreshed_at` field in the response.

## Frontend: `<TopThree />`

### Section header

- Left: `<h2>Today's top 3</h2>` in bold + muted `refreshed H:MM PM` (relative-formatted from hook's `lastUpdated`).
- Right: muted button `HOW WE PICK THESE →` that toggles a small popover (see below).
- Subtitle line below header: muted `The three most convincing setups right now — scored by edge, urgency, and wallet quality.`

### Grid

- Desktop: `grid md:grid-cols-3 gap-4`.
- Mobile: single column stack.
- Loading: 3 skeleton cards with the same footprint.
- Empty (API returned `[]`): hide the entire section.

### Card anatomy

Entire card is a `<Link>` to the alert detail page (same route used elsewhere). The `Copy YES / NO` button is part of the link — it does not `stopPropagation`, so clicking it just navigates. Q5 approved = option A.

1. **Header row**
   - Category pill: emoji + label + color.
     - `⚡ HIGHEST CONVICTION` — green (`var(--category-conviction)` = `var(--accent)`)
     - `🎯 COORDINATED FLOW` — purple (`var(--category-coordinated)` = new var `#a78bfa`)
     - `⏱ TIMING EDGE` — blue (`var(--category-timing)` = new var `#60a5fa`)
   - 4-bar signal-strength icon colored by category (filled bars = `strength`).
   - Circled rank number on the right (outline color = category color).

2. **Title row**
   - 40×40 rounded market image (fallback to an empty rounded tile if missing).
   - Market title, 2-line clamp.
   - Primary tag pill (muted outline).
   - `Resolves in Xd Yh` via `useCountdown(alert.end_date)`. When countdown < 6h, color `var(--danger)` (red); < 24h, `var(--warning)` (amber); else `var(--text-muted)`.

3. **Summary line**
   - `llm_summary`, 3-line clamp, muted body color.

4. **Stats row** (3 columns with vertical dividers)
   - `SMART MONEY` — `$48k` (compact format: `k` / `M`).
   - `ENTRY / NOW` — `18¢ → 26¢` (entry from `llm_copy_action.entry_price`, now from `latest_price`; both rendered as integer cents; arrow respects direction).
   - `IF RESOLVES YES` — `+285%` computed as `(1 / entry_price - 1) * 100`, rounded to nearest integer percent. When `llm_copy_action.outcome === "NO"` show `IF RESOLVES NO` and compute as `(1 / (1 - entry_price) - 1) * 100`.

5. **Footer row**
   - Wallet avatar: a colored circle with the first letter of `pseudonym`; color seeded from the address (reuse existing pseudonym util).
   - `pseudonym` (bold).
   - Muted `{win_rate}% · ${pnl_compact} PnL`.
   - `Copy YES →` (or `Copy NO →`) bright-green pill button, right-aligned.

6. **Rank-1 accent**
   - If `rank === 1`, wrap the card with a 1px outer glow in the rank-1 category's color (CSS `box-shadow: 0 0 0 1px var(--category-…) inset`).

### Loading state

3 skeleton cards with matching height and the same grid. Skeletons shimmer via existing shimmer utilities if present; otherwise a simple opacity pulse.

### CSS additions

Add to [frontend/src/app/globals.css](../../frontend/src/app/globals.css) (or wherever theme vars live):

```css
:root {
  --category-conviction: var(--accent);
  --category-coordinated: #a78bfa;
  --category-timing: #60a5fa;
}
```

## "How we pick these" popover

Lightweight click-to-open popover anchored to the `HOW WE PICK THESE →` button.

- Click button → popover opens.
- Click outside or press Escape → popover closes.
- Not a hover tooltip (mobile-friendly).
- No portal — position `absolute` below the button.

Copy:

> **How we pick these**
>
> We rank every notable trade by edge, urgency, and wallet quality. The top 3 always span three angles: a sharp-wallet conviction bet, coordinated flow across multiple wallets, and a timing edge near resolution.

## Refresh cadence

- Hook polls `/api/top3` on mount, then every 60 seconds.
- Hook also exposes a `refresh()` function and a `lastUpdated` Date so the section header can show `refreshed H:MM PM`.
- Silent failure on network error (keep last-good data, don't flash empty).

## Testing

**Backend** — extend [backend/test_endpoints.py](../../backend/test_endpoints.py):

1. Happy path: seed 3+ alerts that qualify for each of the three buckets; assert each category appears exactly once with expected shape.
2. Empty-bucket fallback: seed alerts that only qualify for `COORDINATED_FLOW`; assert the other two slots are filled by next-best composite_score alerts and labeled correctly.
3. Settled-market exclusion: seed an otherwise-qualifying alert whose latest candle is `0.02`; assert excluded.
4. Empty pool: with no qualifying alerts in 24h, assert `[]`.
5. Rank field: assert the 3 returned rows have `rank` 1, 2, 3 in response order.
6. Strength mapping: spot-check `composite_score=10 → strength=1`, `50 → 3`, `75 → 4`, `200 → 4`.

**Frontend** — manual smoke:

- Load `/` and verify 3 cards render with distinct categories.
- Click each card → lands on the alert detail page.
- Click `Copy YES` → same navigation (no popup).
- Click `HOW WE PICK THESE` → popover opens; Esc closes; outside click closes.
- Verify `lastUpdated` updates after 60s wait or manual refresh.
- Verify mobile width stacks to single column.
- Verify `npm run lint` passes.

## Out of scope (for this spec)

- Replacing or enriching `TopicNav` (mockup's "Browse by topic" card strip).
- Linking the `Copy YES` button to Polymarket with a pre-selected outcome.
- A dedicated `/about/scoring` page.
- Removing `HeroSpotlight.jsx` or `useSpotlight.js` from the codebase.

## Open questions / risks

- Wallet avatar circle color in the card footer. Existing tier utility exposes `tier.color`; we use that. If `computeTier` returns `null` (win_rate < 0.5), fall back to a neutral muted color — but the selection rule for `HIGHEST_CONVICTION` already requires `win_rate >= 0.7`, so this only matters for fallback fills.
- Strength banding (`floor(composite_score / 25) + 1`) is a first guess. If most alerts cluster in a narrow band, bars will all look the same; we may want to re-band to quartiles of the candidate pool. Deferred — ship the simple version first.
