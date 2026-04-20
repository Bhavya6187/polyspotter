# TopBar: Feedback + X links

## Goal

Add two site-wide links to the top of every page:

- A **Send feedback** link that opens the user's email client addressed to `feedback@polyspotter.com`.
- An **X (Twitter)** icon link pointing to `https://x.com/polyspotter`.

Both must appear at the top of the page (not in a footer) and must work across every route without editing each page's existing header.

## Motivation

There is currently no way for users to contact us or find our social presence from within the app. The app has no site-wide footer, and the header is duplicated across five page clients — so adding these links inside each existing header would require editing five files and stay out of sync easily.

## Design

### Placement

A new thin strip rendered in [frontend/src/app/layout.jsx](frontend/src/app/layout.jsx) inside `<body>` and above `{children}`. Because `layout.jsx` wraps every route, the strip appears site-wide automatically — no changes needed to any page client or existing header.

The strip sits above the existing per-page headers, so the visual order from top to bottom is: TopBar → existing page header → page content.

### Component

New file: `frontend/src/components/TopBar.jsx`.

- Full-width outer container (spans the viewport) with a subtle bottom border using `var(--border)`.
- Inner row constrained to `max-w-6xl` and centered (matching the existing page width used in [home-client.jsx](frontend/src/app/home-client.jsx)), right-aligned flex with `gap-3`, centered vertically.
- Small padding (approx. `px-4 py-2`), `text-xs`.
- Text color uses `var(--text-muted)` so it stays unobtrusive; hover brightens to `var(--text-primary)`.

Contents, left to right:

1. **Send feedback** — an `<a>` with `href="mailto:feedback@polyspotter.com"`. Plain text link, muted color, hover underline.
2. **X icon** — an `<a>` with `href="https://x.com/polyspotter"`, `target="_blank"`, `rel="noopener noreferrer"`, and `aria-label="Follow PolySpotter on X"`. Inline SVG for the X logo (single-path monochrome, ~14×14px), `currentColor` fill, same muted→primary hover behavior.

No modal, no client-side handlers — both links are pure anchors. The component has no props and no state, so it can be rendered directly from the server component `layout.jsx` without a `"use client"` directive.

### Styling consistency

The strip must match the minimal aesthetic of the existing header: same font family (inherited), muted text via the existing CSS variables, and a hairline bottom border that reads as a divider rather than a bar. No background fill beyond `var(--surface-0)` (inherited from body).

## Non-goals

- No in-app feedback modal or form — `mailto:` only.
- No footer — this is an explicit reversal of the earlier footer proposal.
- No edits to existing page headers.
- No analytics/event tracking on the links (can be added later if needed).

## Acceptance criteria

- TopBar renders on every route (home, tag pages, market pages incl. basketball and cricket variants).
- Clicking "Send feedback" opens the user's default mail client with `feedback@polyspotter.com` in the To field.
- Clicking the X icon opens `https://x.com/polyspotter` in a new tab.
- No existing page header is modified.
- `npm run lint` in `frontend/` passes.
