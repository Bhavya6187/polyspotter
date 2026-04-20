# Feedback + X TopBar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin, site-wide top strip containing a "Send feedback" mailto link and an X (Twitter) icon link to https://x.com/polyspotter.

**Architecture:** A single presentational component (`TopBar.jsx`) rendered once from the root layout (`frontend/src/app/layout.jsx`) above `{children}`. Pure anchors, no state, no client directive. Styled with existing CSS variables (`--text-muted`, `--text-primary`, `--border`) so both dark and light themes Just Work.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind CSS 4.

---

## File Structure

- Create: `frontend/src/components/TopBar.jsx` — presentational component, default export, no props, no state, no `"use client"` directive.
- Modify: `frontend/src/app/layout.jsx` — import `TopBar` and render it inside `<body>` immediately before `{children}`.

No tests are specified. The frontend has no React test harness (only `npm run lint`), so verification is done via lint + manual browser check in the dev server. This matches the existing pattern for this codebase's frontend components (no sibling tests exist for `ThemeToggle`, `BrandMark`, etc.).

---

## Task 1: Create the TopBar component

**Files:**
- Create: `frontend/src/components/TopBar.jsx`

- [ ] **Step 1: Create the component file**

Create `frontend/src/components/TopBar.jsx` with the following content:

```jsx
export default function TopBar() {
  return (
    <div
      className="w-full"
      style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-0)' }}
    >
      <div className="mx-auto max-w-6xl px-4 py-2 flex items-center justify-end gap-3 text-xs">
        <a
          href="mailto:feedback@polyspotter.com"
          className="transition-colors hover:underline"
          style={{ color: 'var(--text-muted)' }}
        >
          Send feedback
        </a>
        <a
          href="https://x.com/polyspotter"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Follow PolySpotter on X"
          className="inline-flex items-center justify-center rounded-md p-1 transition-colors hover:opacity-80"
          style={{ color: 'var(--text-muted)' }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="h-3.5 w-3.5"
            aria-hidden="true"
          >
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
          </svg>
        </a>
      </div>
    </div>
  );
}
```

Notes:
- No `"use client"` directive — this is a server component. It has no hooks and no event handlers.
- The outer `<div>` spans the full viewport width and owns the bottom border. The inner `<div>` matches the `max-w-6xl` width used by the existing pages (see `frontend/src/app/home-client.jsx:121`).
- The SVG is the standard X/Twitter "X" glyph as a single path using `currentColor` so it inherits from the anchor's text color.

- [ ] **Step 2: Lint the new file**

Run:

```bash
cd frontend && npm run lint
```

Expected: passes with no errors for `src/components/TopBar.jsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TopBar.jsx
git commit -m "Add TopBar component with feedback and X links"
```

---

## Task 2: Render TopBar site-wide from the root layout

**Files:**
- Modify: `frontend/src/app/layout.jsx` (add import near top; render inside `<body>` above `{children}`)

- [ ] **Step 1: Add the TopBar import**

In `frontend/src/app/layout.jsx`, add the following import. Place it below the existing `import "./globals.css";` line (around line 3):

```jsx
import TopBar from "../components/TopBar";
```

The imports section should end up looking like:

```jsx
import Script from "next/script";
import { JetBrains_Mono, DM_Sans } from "next/font/google";
import "./globals.css";
import TopBar from "../components/TopBar";
import { themeScript } from "./theme-script";
```

- [ ] **Step 2: Render TopBar inside `<body>` before `{children}`**

In the same file, find the `<body>` opening tag (currently around line 112):

```jsx
<body className="min-h-screen" style={{ background: 'var(--surface-0)', color: 'var(--text-primary)' }}>
  {children}
```

Change it to render `<TopBar />` immediately before `{children}`:

```jsx
<body className="min-h-screen" style={{ background: 'var(--surface-0)', color: 'var(--text-primary)' }}>
  <TopBar />
  {children}
```

Do not change anything else in the file. The three `<Script>` tags after `{children}` stay exactly as they are.

- [ ] **Step 3: Lint**

Run:

```bash
cd frontend && npm run lint
```

Expected: passes with no errors.

- [ ] **Step 4: Manual browser verification**

Start the dev server:

```bash
cd frontend && npm run dev
```

Open http://localhost:3000 and verify:

1. A thin strip appears at the very top of the page, above the existing header (BrandMark / ThemeToggle row).
2. The strip shows "Send feedback" text and an X icon, right-aligned, within the same horizontal content width as the rest of the page.
3. Clicking "Send feedback" triggers the system email handler with `feedback@polyspotter.com` as the recipient.
4. Clicking the X icon opens https://x.com/polyspotter in a new tab.
5. Navigate to at least one other route (e.g. a market page via a card on the home page, or `/tag/politics`) and confirm the TopBar is still present there.
6. Toggle the theme via the existing theme toggle and confirm the TopBar text and border remain legible in both dark and light modes.

If any of the above fails, stop and investigate before committing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/layout.jsx
git commit -m "Render TopBar site-wide from root layout"
```

---

## Done criteria

- `frontend/src/components/TopBar.jsx` exists with the exact content from Task 1 Step 1.
- `frontend/src/app/layout.jsx` imports `TopBar` and renders `<TopBar />` immediately before `{children}` inside `<body>`.
- `npm run lint` passes in `frontend/`.
- The TopBar is visible on home, tag, and market pages.
- Feedback link opens the mail client addressed to `feedback@polyspotter.com`.
- X icon link opens https://x.com/polyspotter in a new tab.
- No existing page header (home, tag, market, basketball, cricket) has been modified.
