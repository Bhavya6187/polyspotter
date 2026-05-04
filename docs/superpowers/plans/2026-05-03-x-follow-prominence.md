# X Follow & Feedback Prominence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two surfaces to the PolySpotter homepage that promote following `@polyspotter` on X and (secondarily) sending feedback — a slim always-visible strip beneath Today's Top 3, and an engagement-triggered dismissible toast bottom-right.

**Architecture:** Two new client components (`TopThreeFollowStrip`, `EngagementToast`) added under `frontend/src/components/`, both rendered inside `home-client.jsx`. The toast encapsulates its own trigger (20s timer OR scrolling past a sentinel below the Top 3) and suppression logic (localStorage with 2-day dismiss / permanent on follow). No backend, hooks, or other-page changes.

**Tech Stack:** Next.js 15 (App Router) client components, React 19, Tailwind CSS 4, CSS variables defined in `frontend/src/app/globals.css`. The frontend has no test framework — verification is `npm run lint` plus manual browser check at each task.

**Spec:** [docs/superpowers/specs/2026-05-03-x-follow-prominence-design.md](docs/superpowers/specs/2026-05-03-x-follow-prominence-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `frontend/src/components/TopThreeFollowStrip.jsx` | Create | Always-visible slim strip linking to X, anchored under the Top 3 row. |
| `frontend/src/components/EngagementToast.jsx` | Create | Bottom-right dismissible toast with X follow (primary) + feedback (secondary), triggered after engagement, with localStorage-backed suppression. |
| `frontend/src/app/home-client.jsx` | Modify | Render the strip directly under `<TopThree />`; render a sentinel div beneath the strip so the toast can observe scroll-past; render the toast at the end of `<main>`. |

The two new files are independently understandable and have one clear job each. Suppression and trigger logic is fully encapsulated in `EngagementToast` — `home-client.jsx` does not import or pass any timing/state for it.

---

## Conventions To Follow

Already established in this codebase — match them:

- Client components start with `"use client";` on line 1.
- Style colors and surfaces via inline `style={{ background: "var(--surface-...)", ... }}` referencing the CSS variables in [frontend/src/app/globals.css](frontend/src/app/globals.css). Use Tailwind classes for layout, spacing, sizing, typography utilities.
- Available tokens used in this plan: `--surface-1`, `--surface-2`, `--surface-card`, `--border`, `--border-subtle`, `--text-primary`, `--text-muted`, `--accent`, `--accent-hover`.
- All external `<a>` tags get `target="_blank"` and `rel="noopener noreferrer"`.
- The X icon SVG already used elsewhere — copy from [frontend/src/components/HeaderActions.jsx:70-78](frontend/src/components/HeaderActions.jsx#L70-L78).

---

## Task 1: Create `TopThreeFollowStrip` component

**Files:**
- Create: `frontend/src/components/TopThreeFollowStrip.jsx`

- [ ] **Step 1: Create the component file**

Create `frontend/src/components/TopThreeFollowStrip.jsx` with the following exact contents:

```jsx
"use client";

/**
 * Slim, always-visible strip rendered directly beneath Today's Top 3.
 * Ties the value of the @polyspotter X account to the section users care
 * most about. Entire strip is one link to X (opens in new tab).
 */
export default function TopThreeFollowStrip() {
  return (
    <a
      href="https://x.com/polyspotter"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Follow PolySpotter on X"
      className="mb-5 flex items-center justify-between gap-3 rounded-xl px-4 py-2.5 text-xs transition-colors"
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border)",
        color: "var(--text-secondary)",
      }}
    >
      <span className="flex min-w-0 items-center gap-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="h-3.5 w-3.5 shrink-0"
          style={{ color: "var(--text-primary)" }}
          aria-hidden="true"
        >
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
        </svg>
        <span className="truncate">
          We post today&rsquo;s top alerts at{" "}
          <span style={{ color: "var(--text-primary)" }}>@polyspotter</span>
        </span>
      </span>
      <span
        className="shrink-0 whitespace-nowrap font-medium"
        style={{ color: "var(--text-primary)" }}
      >
        Follow →
      </span>
    </a>
  );
}
```

- [ ] **Step 2: Lint the new file**

Run: `cd frontend && npm run lint`
Expected: passes with no new errors. (If unrelated pre-existing warnings appear, ignore them.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TopThreeFollowStrip.jsx
git commit -m "feat(frontend): add TopThreeFollowStrip component"
```

---

## Task 2: Render `TopThreeFollowStrip` and a scroll sentinel in `home-client.jsx`

**Files:**
- Modify: `frontend/src/app/home-client.jsx`

- [ ] **Step 1: Add the import**

In `frontend/src/app/home-client.jsx`, add the import alongside the other component imports near the top of the file (currently around lines 5–15). Insert immediately after the `import TopThree from "../components/TopThree";` line:

Find this line:
```jsx
import TopThree from "../components/TopThree";
```

Replace with:
```jsx
import TopThree from "../components/TopThree";
import TopThreeFollowStrip from "../components/TopThreeFollowStrip";
```

- [ ] **Step 2: Render the strip and a sentinel directly below `<TopThree />`**

In the JSX, locate this block (currently around lines 179–181):

```jsx
      {/* Today's Top 3 */}
      <TopThree />

      {/* Live ticker — hidden on mobile, duplicates feed */}
```

Replace with:

```jsx
      {/* Today's Top 3 */}
      <TopThree />
      <TopThreeFollowStrip />
      {/* Sentinel observed by EngagementToast to detect scroll past Top 3 */}
      <div id="top-three-end-sentinel" aria-hidden="true" />

      {/* Live ticker — hidden on mobile, duplicates feed */}
```

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`
Expected: passes.

- [ ] **Step 4: Manual browser verification**

Run the dev server (in a separate terminal or background): `cd frontend && npm run dev`

Open http://localhost:3000 and verify:
- The slim strip appears directly under the Top 3 cards row, above the live ticker.
- It says: `𝕏  We post today's top alerts at @polyspotter — Follow →`
- Hover shows pointer cursor; clicking opens https://x.com/polyspotter in a new tab.
- Strip is single-line at desktop and mobile widths (resize browser to ~375px to confirm).
- Inspect the DOM and confirm a `<div id="top-three-end-sentinel">` exists immediately after the strip.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/home-client.jsx
git commit -m "feat(frontend): render TopThreeFollowStrip and sentinel under Top 3"
```

---

## Task 3: Scaffold `EngagementToast` component (visible, no triggers, no suppression)

This task creates the toast UI in an always-visible state so we can verify the visual design before layering on trigger and suppression logic. It also adds a one-shot entry animation (fade + slide-up) that fires whenever the toast mounts visible.

**Spec note on animations:** The spec specifies both entry and exit animations. We implement entry (250ms fade + 8px slide-up) here. Exit animation is deferred — `if (!visible) return null` removes the element immediately on dismiss. Adding an exit transition would require a deferred-unmount state machine that adds disproportionate complexity for polish; current behavior (instant disappear) is acceptable.

**Files:**
- Create: `frontend/src/components/EngagementToast.jsx`
- Modify: `frontend/src/app/globals.css`

- [ ] **Step 1: Add the toast entry keyframe to `globals.css`**

In `frontend/src/app/globals.css`, locate the existing `fade-up` block (around line 134–141):

```css
@keyframes fade-up {
  from { opacity: 0; }
  to { opacity: 1; }
}
.animate-fade-up {
  animation: fade-up 0.3s ease-out both;
  content-visibility: auto;
}
```

Add the following block immediately after it:

```css
@keyframes toast-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-toast-in {
  animation: toast-in 0.25s ease-out both;
}
```

- [ ] **Step 2: Create the component file with always-visible scaffold**

Create `frontend/src/components/EngagementToast.jsx` with the following contents:

```jsx
"use client";

import { useState, useCallback } from "react";

/**
 * Bottom-right dismissible toast that promotes following @polyspotter
 * (primary CTA) and sending feedback (secondary CTA).
 *
 * v1: scaffold — always visible on mount, dismiss closes it for the rest
 * of the session only. Trigger and persistent suppression added in
 * subsequent tasks.
 */
export default function EngagementToast() {
  const [visible, setVisible] = useState(true);

  const handleClose = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    setVisible(false);
  }, []);

  if (!visible) return null;

  return (
    <div
      role="region"
      aria-label="Follow PolySpotter"
      className="animate-toast-in fixed z-50 w-[calc(100%-2rem)] max-w-[320px] rounded-xl p-4 shadow-lg"
      style={{
        bottom: "1.5rem",
        right: "1.5rem",
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="h-4 w-4"
            style={{ color: "var(--text-primary)" }}
            aria-hidden="true"
          >
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
          </svg>
          <span
            className="text-sm font-semibold"
            style={{ color: "var(--text-primary)" }}
          >
            Follow @polyspotter
          </span>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 transition-opacity hover:opacity-70"
          style={{ color: "var(--text-muted)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-3.5 w-3.5"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      <p
        className="mt-2 text-xs"
        style={{ color: "var(--text-secondary)" }}
      >
        We&rsquo;re constantly sharing today&rsquo;s top alerts.
      </p>

      <a
        href="https://x.com/polyspotter"
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleFollow}
        className="mt-3 flex w-full items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition-colors"
        style={{
          background: "var(--accent)",
          color: "#ffffff",
        }}
      >
        Follow on X
      </a>

      <div
        className="my-3 h-px"
        style={{ background: "var(--border-subtle)" }}
        aria-hidden="true"
      />

      <a
        href="mailto:feedback@polyspotter.com"
        onClick={handleFeedback}
        className="block text-xs transition-opacity hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
      >
        Got thoughts? Send feedback →
      </a>
    </div>
  );
}
```

- [ ] **Step 3: Render the toast in `home-client.jsx`**

In `frontend/src/app/home-client.jsx`, add the import below the `TopThreeFollowStrip` import:

Find:
```jsx
import TopThreeFollowStrip from "../components/TopThreeFollowStrip";
```

Replace with:
```jsx
import TopThreeFollowStrip from "../components/TopThreeFollowStrip";
import EngagementToast from "../components/EngagementToast";
```

Then locate the closing `</main>` tag at the end of the returned JSX (currently around line 220) and add the toast as the last child of `<main>` immediately before `</main>`:

Find:
```jsx
      {/* Pagination */}
      <nav aria-label="Pagination">
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
        />
      </nav>
    </main>
```

Replace with:
```jsx
      {/* Pagination */}
      <nav aria-label="Pagination">
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
        />
      </nav>

      <EngagementToast />
    </main>
```

- [ ] **Step 4: Lint**

Run: `cd frontend && npm run lint`
Expected: passes.

- [ ] **Step 5: Manual browser verification**

Reload http://localhost:3000 and verify:
- Toast appears bottom-right immediately on page load with a brief fade + slide-up animation (~250ms).
- Card has X icon, `Follow @polyspotter` title, body line, green `Follow on X` button, divider, `Got thoughts? Send feedback →` text link, and a close (×) button.
- Clicking × hides the toast (refresh brings it back — that's expected; persistence comes in Task 5).
- Clicking `Follow on X` opens https://x.com/polyspotter in a new tab and hides the toast.
- Clicking `Got thoughts? Send feedback →` opens the mail client with `feedback@polyspotter.com` and hides the toast.
- Resize to mobile width (~375px); toast still fits, sized to `calc(100% - 2rem)` capped at 320px.
- Toggle dark mode (theme toggle in header); toast remains legible — text and surface colors swap correctly.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/globals.css frontend/src/components/EngagementToast.jsx frontend/src/app/home-client.jsx
git commit -m "feat(frontend): scaffold EngagementToast (always-visible v1)"
```

---

## Task 4: Add trigger logic to `EngagementToast` (20s OR scroll past sentinel)

Replace the always-visible behavior with the engagement-based trigger.

**Files:**
- Modify: `frontend/src/components/EngagementToast.jsx`

- [ ] **Step 1: Replace state initialization and add trigger effect**

Open `frontend/src/components/EngagementToast.jsx`. Replace the existing `useState` import line with one that also imports `useEffect`:

Find:
```jsx
import { useState, useCallback } from "react";
```

Replace with:
```jsx
import { useState, useEffect, useCallback } from "react";
```

Then replace the `const [visible, setVisible] = useState(true);` line and add the trigger effect immediately below the handler `useCallback`s. The full block from the top of the function through the handlers should now look like this:

Find:
```jsx
export default function EngagementToast() {
  const [visible, setVisible] = useState(true);

  const handleClose = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    setVisible(false);
  }, []);

  if (!visible) return null;
```

Replace with:
```jsx
export default function EngagementToast() {
  const [visible, setVisible] = useState(false);

  const handleClose = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    setVisible(false);
  }, []);

  // Trigger: show toast after 20s on page OR when user scrolls past the
  // Top 3 sentinel — whichever fires first. Once shown, do not re-trigger
  // on this page load.
  useEffect(() => {
    let alreadyShown = false;
    const show = () => {
      if (alreadyShown) return;
      alreadyShown = true;
      setVisible(true);
    };

    const timer = setTimeout(show, 20_000);

    let observer = null;
    const sentinel = document.getElementById("top-three-end-sentinel");
    if (sentinel && typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              show();
              break;
            }
          }
        },
        { threshold: 0 }
      );
      observer.observe(sentinel);
    }

    return () => {
      clearTimeout(timer);
      if (observer) observer.disconnect();
    };
  }, []);

  if (!visible) return null;
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npm run lint`
Expected: passes.

- [ ] **Step 3: Manual browser verification — 20s timer trigger**

Hard reload http://localhost:3000 (Cmd+Shift+R). Do NOT scroll. Wait ~20 seconds.

Expected: toast appears bottom-right after ~20s.

If a previous Task 3 dismiss is still hidden by browser session state, refresh again — Task 3 used in-memory state only, so reloading restores visibility eligibility.

- [ ] **Step 4: Manual browser verification — scroll trigger**

Hard reload http://localhost:3000. Within the first few seconds, scroll down past the Top 3 cards row.

Expected: toast appears as soon as the sentinel below the strip enters the viewport (well before 20s elapse).

- [ ] **Step 5: Manual browser verification — no double trigger**

Hard reload, scroll past Top 3 immediately to fire the scroll trigger, then dismiss the toast with ×, then wait 20s.

Expected: toast does NOT reappear when the 20s timer would have fired. (`alreadyShown` guards against re-trigger within the same page load.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EngagementToast.jsx
git commit -m "feat(frontend): trigger EngagementToast after 20s or scroll past Top 3"
```

---

## Task 5: Add persistent suppression to `EngagementToast` (localStorage, 2-day dismiss / permanent on follow)

**Files:**
- Modify: `frontend/src/components/EngagementToast.jsx`

- [ ] **Step 1: Add suppression helpers and update the trigger effect and handlers**

Open `frontend/src/components/EngagementToast.jsx`.

Add the following helper constants and functions immediately above the `export default function EngagementToast()` line:

```jsx
const STORAGE_KEY = "polyspotter_engage_toast";
const DISMISS_TTL_MS = 2 * 24 * 60 * 60 * 1000; // 2 days

function readSuppression() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeSuppression(value) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {}
}

function isCurrentlySuppressed() {
  const stored = readSuppression();
  if (!stored) return false;
  if (typeof stored.followedAt === "number") return true; // permanent
  if (typeof stored.dismissedAt === "number") {
    return Date.now() - stored.dismissedAt < DISMISS_TTL_MS;
  }
  return false;
}
```

Then update the three handlers to write their respective suppression state. Replace this block:

```jsx
  const handleClose = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    setVisible(false);
  }, []);
```

with:

```jsx
  const handleClose = useCallback(() => {
    writeSuppression({ dismissedAt: Date.now() });
    setVisible(false);
  }, []);

  const handleFollow = useCallback(() => {
    writeSuppression({ followedAt: Date.now() });
    setVisible(false);
  }, []);

  const handleFeedback = useCallback(() => {
    writeSuppression({ dismissedAt: Date.now() });
    setVisible(false);
  }, []);
```

Then update the trigger `useEffect` to bail out early if currently suppressed. Replace:

```jsx
  useEffect(() => {
    let alreadyShown = false;
    const show = () => {
      if (alreadyShown) return;
      alreadyShown = true;
      setVisible(true);
    };

    const timer = setTimeout(show, 20_000);
```

with:

```jsx
  useEffect(() => {
    if (isCurrentlySuppressed()) return undefined;

    let alreadyShown = false;
    const show = () => {
      if (alreadyShown) return;
      alreadyShown = true;
      setVisible(true);
    };

    const timer = setTimeout(show, 20_000);
```

(Everything below that line in the effect — the IntersectionObserver setup and the cleanup return — stays as-is.)

- [ ] **Step 2: Add Esc-to-dismiss when toast is visible**

Immediately after the existing trigger `useEffect` (the one ending in `return () => { clearTimeout(timer); if (observer) observer.disconnect(); };`), add a second `useEffect` that listens for Esc only while the toast is visible:

```jsx
  useEffect(() => {
    if (!visible) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        writeSuppression({ dismissedAt: Date.now() });
        setVisible(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible]);
```

- [ ] **Step 3: Lint**

Run: `cd frontend && npm run lint`
Expected: passes.

- [ ] **Step 4: Manual browser verification — close persists for 2 days**

In DevTools console, run `localStorage.removeItem("polyspotter_engage_toast")` to start clean. Hard reload, wait for toast to appear (or scroll past Top 3 to speed it up), then click the × close button.

In DevTools → Application → Local Storage, confirm `polyspotter_engage_toast` now contains a JSON object with `dismissedAt: <large number>`.

Hard reload the page. Wait 25 seconds and scroll the page.

Expected: toast does NOT reappear.

To verify the 2-day expiry boundary works without waiting two days, in DevTools console run:
```js
localStorage.setItem("polyspotter_engage_toast", JSON.stringify({ dismissedAt: Date.now() - (2 * 24 * 60 * 60 * 1000 + 1000) }));
```
Hard reload and either wait 20s or scroll past Top 3.

Expected: toast appears (the stored timestamp is more than 2 days old, so suppression has expired).

- [ ] **Step 5: Manual browser verification — follow permanently suppresses**

Clear storage: `localStorage.removeItem("polyspotter_engage_toast")` then hard reload.

When the toast appears, click `Follow on X`. Confirm a new tab opens to https://x.com/polyspotter.

In DevTools → Application → Local Storage, confirm the value is now `{"followedAt": <number>}`.

Hard reload, wait 25s, scroll, etc.

Expected: toast does NOT reappear, ever (no expiry check on `followedAt`).

To prove the permanence: in DevTools console run:
```js
localStorage.setItem("polyspotter_engage_toast", JSON.stringify({ followedAt: 1 }));
```
Hard reload and try every trigger.

Expected: toast does NOT appear.

- [ ] **Step 6: Manual browser verification — feedback dismisses for 2 days**

Clear storage and hard reload. When toast appears, click `Got thoughts? Send feedback →`. Mail client opens.

Confirm `polyspotter_engage_toast` now contains `dismissedAt: <number>`.

Hard reload, wait 25s, scroll.

Expected: toast does NOT reappear.

- [ ] **Step 7: Manual browser verification — Esc dismisses**

Clear storage and hard reload. When toast appears, click anywhere inside the toast (e.g., focus the close button), then press Esc.

Expected: toast disappears, `polyspotter_engage_toast` now contains `dismissedAt: <number>`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/EngagementToast.jsx
git commit -m "feat(frontend): persist EngagementToast suppression in localStorage"
```

---

## Task 6: Final end-to-end verification

No code changes — a final checklist to confirm the spec is satisfied before considering the work shippable.

- [ ] **Step 1: Clean state e2e walkthrough**

In DevTools console: `localStorage.removeItem("polyspotter_engage_toast")`. Hard reload http://localhost:3000.

Verify in order:
- [ ] Top 3 cards render at the top of the page.
- [ ] The slim follow strip appears immediately under the Top 3 cards, above the live ticker.
- [ ] The strip text reads `We post today's top alerts at @polyspotter` with a `Follow →` affordance on the right and a small X icon on the left.
- [ ] Clicking the strip opens https://x.com/polyspotter in a new tab.
- [ ] Without scrolling or interacting, after ~20 seconds the bottom-right toast appears with the X follow + feedback CTAs.
- [ ] Hard reload, then scroll down past Top 3 within the first few seconds; toast appears almost immediately (scroll trigger beats 20s).

- [ ] **Step 2: Suppression matrix walk**

For each of the three actions (close ×, Follow, Send feedback), clear storage, trigger the toast, perform the action, then verify the localStorage value matches the table:

| Action | Expected `polyspotter_engage_toast` value |
|---|---|
| Close (×) | `{ "dismissedAt": <recent ms> }` |
| Follow on X | `{ "followedAt": <recent ms> }` |
| Send feedback | `{ "dismissedAt": <recent ms> }` |
| Esc key | `{ "dismissedAt": <recent ms> }` |

- [ ] **Step 3: Other pages unaffected**

Navigate to `/articles`, a market detail page (click any market in the alert list), and a wallet page. Confirm:
- [ ] No follow strip appears (it lives only on home).
- [ ] No engagement toast appears (it's only mounted on home).
- [ ] The existing header X icon and Feedback link still work as before — no regression in [HeaderActions.jsx](frontend/src/components/HeaderActions.jsx).

- [ ] **Step 4: Light + dark theme**

On the homepage, toggle the theme via the header's theme toggle. Verify both the strip and the toast remain legible and visually consistent in both themes (text contrast, surface vs. background, button color).

- [ ] **Step 5: Mobile width**

Resize browser to ~375px (or use DevTools device toolbar). Verify:
- [ ] Strip stays single-line, copy may truncate but `Follow →` always visible.
- [ ] Toast appears bottom-right with comfortable side margin (`calc(100% - 2rem)` capped at 320px), not edge-to-edge.

- [ ] **Step 6: Lint clean**

Run: `cd frontend && npm run lint`
Expected: passes.

- [ ] **Step 7: No commit needed**

If everything passes, the work is complete. If any issue surfaces, file a small fix commit and re-run the relevant verification step.
