# X Follow & Feedback Prominence — Design

**Date:** 2026-05-03
**Status:** Approved, ready for implementation plan
**Scope:** Frontend (`frontend/src/app/home-client.jsx` and two new components)

## Problem

The PolySpotter homepage exposes the X (Twitter) follow as a tiny icon-only button buried in the top-right header alongside Articles and Feedback links ([HeaderActions.jsx:61-79](frontend/src/components/HeaderActions.jsx#L61-L79)). It gets effectively no clicks. Feedback is in the same dead zone.

We want to surface the X follow more prominently — without adopting a hard-ask modal or feeling like a growth-hack overlay that erodes the credibility we sell on (smart-money intelligence).

## Goals

- Increase discoverability of `@polyspotter` X account from the homepage.
- Tie the follow to a clear value prop ("today's top alerts arrive in your feed") rather than presenting it as orphan chrome.
- Provide a soft, dismissible secondary nudge that also surfaces feedback.
- Preserve the homepage's focus on the Top 3 / alerts content.

## Non-goals

- Modifying the existing `HeaderActions` row. The new surfaces are additive.
- Surfacing the toast on non-home pages (market, wallet, alert, articles, etc.) in v1. We can extend later if data warrants.
- Backend or analytics work — this spec is purely frontend.
- Replacing the existing mailto-based feedback flow.

## Approach

Two complementary surfaces, both additive:

1. **`TopThreeFollowStrip`** — an always-visible narrative strip that sits directly under the Top 3 cards and ties the follow to the section users care most about.
2. **`EngagementToast`** — a dismissible, bottom-right slide-in card triggered after engagement that combines the X follow (primary CTA) with a feedback link (secondary CTA).

These were chosen over alternatives (modal popup, header pill upgrade, fourth Top-3 card, inline badges per card) because they:
- Don't block reading or feel like spam (preserves trust).
- Earn attention through engagement signals rather than demanding it on page load.
- Keep the Top 3 visual contract ("3 cards") intact while still associating the follow with that section.

## Component 1 — `TopThreeFollowStrip`

### Placement
Home page only. Renders directly below the `<TopThree />` component and above the live ticker / Resolving Soon section in [home-client.jsx:180-189](frontend/src/app/home-client.jsx#L180-L189).

### Form
- Slim, single-line strip spanning the same width as the Top 3 row.
- Subdued background using existing surface tokens (`var(--surface-2)` or equivalent), with the X icon receiving the only brand accent.
- Right-aligned chevron / `Follow →` affordance.
- Entire strip is a single `<a>` to `https://x.com/polyspotter` with `target="_blank"` and `rel="noopener noreferrer"`.

### Copy
```
𝕏  We post today's top alerts at @polyspotter — Follow →
```

### Behavior
- No dismiss control — this is part of the page, not an overlay.
- Hover state: subtle background lift (`hover:opacity-90` or token swap), pointer cursor.
- Clicking anywhere on the strip opens X in a new tab.

### Mobile
- Stays single-line. Copy may auto-truncate (`text-overflow: ellipsis`) but the `Follow →` affordance must always be visible.
- Maintains the same height as the slim desktop strip; do not balloon to a card.

### Accessibility
- Wrapping `<a>` carries `aria-label="Follow PolySpotter on X"`.
- X icon marked `aria-hidden="true"` since the label conveys the action.

## Component 2 — `EngagementToast`

### Placement
Home page only for v1. Fixed positioning, bottom-right, with reasonable insets (`bottom: 1.5rem; right: 1.5rem` on desktop, full-width with side margins on mobile).

### Trigger
Toast appears once per page load when **either** of the following first fires, provided suppression rules allow it:
- 20 seconds elapsed since mount, OR
- User scrolls past the bottom of the Top 3 section (use `IntersectionObserver` on the section's bottom sentinel).

Use whichever fires first. Once shown, do not re-trigger on the same page load.

### Form
- Single card, ~320px wide on desktop, full width minus side margins on mobile.
- Visual structure (top to bottom):
  - Header row: X icon + bold `Follow @polyspotter` + close (`×`) button on the right.
  - Body line: `We're constantly sharing today's top alerts.`
  - Primary button (full-width inside card): `Follow on X`.
  - Thin divider.
  - Secondary text link: `Got thoughts? Send feedback →`.

### Copy
- Title: `Follow @polyspotter`
- Body: `We're constantly sharing today's top alerts.`
- Primary CTA: `Follow on X` → `https://x.com/polyspotter` (new tab, `noopener noreferrer`)
- Secondary link: `Got thoughts? Send feedback →` → `mailto:feedback@polyspotter.com`

### Suppression logic
LocalStorage key: `polyspotter_engage_toast`. Stored value is a JSON object.

| User action | Stored value | Future suppression |
|---|---|---|
| Clicks close (`×`) | `{ "dismissedAt": <unix ms> }` | Suppressed for 2 days from `dismissedAt`. After 48h elapsed, eligible again. |
| Clicks `Follow on X` | `{ "followedAt": <unix ms> }` | Permanently suppressed (no expiry check). |
| Clicks `Send feedback` | `{ "dismissedAt": <unix ms> }` | Same as close — 2-day suppression. They engaged but may still follow later. |

On mount, read the key:
- If it has `followedAt`, never show.
- If it has `dismissedAt` and `now - dismissedAt < 2 days`, do not show.
- Otherwise eligible — set up the trigger timers/observers.

If parsing fails or the key is missing, treat as eligible.

### Animations
- Entry: fade in + 8px slide-up, ~250ms ease-out.
- Exit: reverse, ~200ms ease-in. Remove from DOM after exit completes.

### Accessibility
- Container has `role="region"` with `aria-label="Follow PolySpotter"`.
- Close button has `aria-label="Dismiss"` and is keyboard-focusable.
- When focus is inside the toast, pressing `Esc` dismisses (treated as close click — 2-day suppression).
- Focus is NOT auto-trapped inside the toast (it must not steal keyboard flow from the page).

## File changes

### New files
- `frontend/src/components/TopThreeFollowStrip.jsx` — the always-visible strip.
- `frontend/src/components/EngagementToast.jsx` — the dismissible toast with all suppression and trigger logic encapsulated.

### Modified files
- `frontend/src/app/home-client.jsx`:
  - Import both new components.
  - Render `<TopThreeFollowStrip />` immediately after `<TopThree />` (line ~180).
  - Render `<EngagementToast />` once at the root of `<main>` (or as a sibling near the end), so it positions correctly and isn't clipped by container `overflow` rules.

### Unchanged
- `frontend/src/components/HeaderActions.jsx` — existing X / Articles / Feedback row remains exactly as-is.
- All other pages and components.

## Out of scope (revisit later)

- Site-wide toast on market, wallet, alert, and article pages.
- Analytics events / tracking on toast and strip clicks.
- A/B testing different copy or trigger thresholds.
- Replacing the mailto feedback link with an in-app feedback form.
- Server-side personalization (e.g., suppress for users who already follow).

## Success signals (post-launch, no code in scope here)

- Click-through rate on the toast `Follow on X` button.
- Dismiss rate (high dismiss = trigger too aggressive; tune the 20s threshold or scroll signal).
- Click-through on the Top 3 strip.
- Net X follower growth attributable to homepage referrers.
