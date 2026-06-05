# Proof Loop — Plan 2: Homepage Proof UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the graded track record on the homepage — a scoreboard hero + "receipts" strip — and reorder the page so proof leads, removing the redundant ticker.

**Architecture:** `page.jsx` (server) fetches `/api/scoreboard` alongside the existing home data and passes it to the client `HomeClient`, which renders two new presentational components — `ScoreboardHero` (30-day W–L, copy return, hit rate, with a cold-start state) and `RecentCalls` (recent graded calls as ✓/✗ chips) — at the top of the page. The live `Ticker` is removed (its own code comment says it "duplicates feed"); `TopThree` is relabeled "Today's sharpest calls."

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind CSS 4. **No frontend unit-test harness exists** (the project ships only `next lint`); verification is `npm run lint` + `npm run build` + a described visual check against the hosted API. We are NOT adding a test framework (YAGNI; follow the existing pattern).

**Spec:** `docs/superpowers/specs/2026-06-04-homepage-proof-loop-design.md` (subsystem C). Depends on Plan 1's `GET /api/scoreboard` (already merged to `main`).

---

## File Structure

- **Modify** `frontend/src/lib/api.js` — add `fetchScoreboard()`.
- **Modify** `frontend/src/app/page.jsx` — fetch `/api/scoreboard` in `getHomeData`, pass `scoreboard` to `HomeClient`.
- **Create** `frontend/src/components/ScoreboardHero.jsx` — the proof hero (presentational).
- **Create** `frontend/src/components/RecentCalls.jsx` — the receipts strip (presentational).
- **Modify** `frontend/src/app/home-client.jsx` — accept `scoreboard` prop, mount the two components at top, remove `Ticker`.
- **Modify** `frontend/src/components/TopThree.jsx` — relabel heading + subtitle.

**Scoreboard response shape** (from Plan 1, `GET /api/scoreboard`):
```json
{
  "window_days": 30,
  "window":   { "wins": 47, "losses": 19, "hit_rate": 0.71, "copy_return_pct": 2.12 },
  "all_time": { "wins": 60, "losses": 25, "hit_rate": 0.70, "copy_return_pct": 1.9 },
  "recent": [ { "market_title": "...", "outcome": "San Diego Padres", "won": true, "return_pct": 0.63, "event_slug": "mlb-sd-phi-2026-06-04", "resolved_at": "..." } ]
}
```
`copy_return_pct` and `return_pct` are fractions (2.12 → +212%, 0.63 → +63%); `hit_rate` is a fraction (0.71 → 71%).

**Design tokens to use** (from `globals.css`): `--surface-card`, `--surface-1`, `--surface-2`, `--border`, `--text-primary`, `--text-secondary`, `--text-muted`, `--bullish` (green), `--bearish` (red), `--accent`, `--font-display`.

**Deferred to Plan 3 (do NOT build here):** the email-capture form (it needs `POST /api/subscribe`, built in Plan 3) and `SharpsLeaderboard`. This plan ships the proof surface only.

---

## Task 1: `fetchScoreboard()` API client

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add the function** after the existing `fetchTopThree` function (around line 84):

```javascript
export function fetchScoreboard() {
  return request("/api/scoreboard");
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(home): fetchScoreboard API client"
```

---

## Task 2: `ScoreboardHero` component

**Files:**
- Create: `frontend/src/components/ScoreboardHero.jsx`

This is a presentational component (props only — no hooks, no fetching). It renders a cold-start state when fewer than 10 calls have been graded all-time, otherwise the 30-day record.

- [ ] **Step 1: Create `frontend/src/components/ScoreboardHero.jsx`**

```jsx
// Presentational proof hero. Renders the graded track record (Plan 1
// /api/scoreboard). Shows a "building" state until >= MIN_GRADED calls exist
// so a tiny early sample never reads as a confident claim.

const MIN_GRADED = 10;

function asPct(fraction) {
  return `${Math.round(fraction * 100)}%`;
}

function asSignedPct(fraction) {
  const v = Math.round(fraction * 100);
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function Stat({ value, label, color }) {
  return (
    <div>
      <div
        className="text-4xl font-extrabold tracking-tight tabular-nums"
        style={{ color }}
      >
        {value}
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
    </div>
  );
}

export default function ScoreboardHero({ scoreboard }) {
  const window = scoreboard?.window;
  const allTime = scoreboard?.all_time;
  const gradedCount = allTime ? allTime.wins + allTime.losses : 0;

  const shell =
    "mb-6 rounded-2xl p-6 sm:p-8";
  const shellStyle = {
    background: "var(--surface-card)",
    border: "1px solid var(--border)",
  };

  if (!window || gradedCount < MIN_GRADED) {
    return (
      <section aria-label="Track record" className={shell} style={shellStyle}>
        <h2
          className="text-lg font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          We grade every call we make.
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          PolySpotter tracks Polymarket&rsquo;s sharpest wallets and scores each
          call against the result.{" "}
          {gradedCount > 0
            ? `Building our track record — ${gradedCount} call${gradedCount === 1 ? "" : "s"} graded so far.`
            : "Our public track record is being built now."}
        </p>
      </section>
    );
  }

  const returnColor =
    window.copy_return_pct >= 0 ? "var(--bullish)" : "var(--bearish)";

  return (
    <section aria-label="Track record" className={shell} style={shellStyle}>
      <div className="flex flex-wrap items-end gap-x-10 gap-y-5">
        <Stat
          value={`${window.wins}–${window.losses}`}
          label={`tracked calls · last ${scoreboard.window_days}d`}
          color="var(--bullish)"
        />
        <Stat
          value={asSignedPct(window.copy_return_pct)}
          label="if you copied $100 each"
          color={returnColor}
        />
        <Stat
          value={asPct(window.hit_rate)}
          label="hit rate"
          color="var(--text-primary)"
        />
      </div>
      <p
        className="mt-5 max-w-xl text-sm"
        style={{ color: "var(--text-secondary)" }}
      >
        We track Polymarket&rsquo;s sharpest wallets and grade every call —
        here&rsquo;s how copying them has actually worked out.
      </p>
    </section>
  );
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ScoreboardHero.jsx
git commit -m "feat(home): ScoreboardHero proof component with cold-start state"
```

---

## Task 3: `RecentCalls` component

**Files:**
- Create: `frontend/src/components/RecentCalls.jsx`

Presentational. Renders the recent graded calls as ✓/✗ chips. Hidden entirely until at least 3 receipts exist (matches the spec's cold-start rule). Chips link to the event page when `event_slug` is present.

- [ ] **Step 1: Create `frontend/src/components/RecentCalls.jsx`**

```jsx
import Link from "next/link";

const MIN_RECEIPTS = 3;

function asSignedPct(fraction) {
  const v = Math.round(fraction * 100);
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function Chip({ call }) {
  const color = call.won ? "var(--bullish)" : "var(--bearish)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <span style={{ color }}>{call.won ? "✓" : "✗"}</span>
      <span style={{ color: "var(--text-primary)" }}>{call.outcome}</span>
      <span style={{ color }} className="tabular-nums">
        {asSignedPct(call.return_pct)}
      </span>
    </span>
  );
}

export default function RecentCalls({ recent }) {
  if (!recent || recent.length < MIN_RECEIPTS) return null;

  return (
    <section aria-label="Recent graded calls" className="mb-6">
      <h2
        className="mb-2 text-[11px] font-bold uppercase tracking-wider"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
      >
        Recent calls — the receipts
      </h2>
      <div className="flex flex-wrap gap-2">
        {recent.map((call, i) =>
          call.event_slug ? (
            <Link
              key={`${call.event_slug}-${i}`}
              href={`/event/${encodeURIComponent(call.event_slug)}`}
              className="transition-opacity hover:opacity-80"
            >
              <Chip call={call} />
            </Link>
          ) : (
            <span key={i}>
              <Chip call={call} />
            </span>
          ),
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/RecentCalls.jsx
git commit -m "feat(home): RecentCalls receipts strip"
```

---

## Task 4: Fetch scoreboard server-side and thread it through

**Files:**
- Modify: `frontend/src/app/page.jsx`

- [ ] **Step 1: Add the scoreboard fetch to `getHomeData`**

In `frontend/src/app/page.jsx`, the `Promise.all([...])` in `getHomeData` (lines 11-20) currently fetches markets, tags, theses, wallets. Add a fifth fetch. Replace the `Promise.all` array and the destructuring + parsing so it reads:

```javascript
    const [marketsRes, tagsRes, thesesRes, walletsRes, scoreboardRes] =
      await Promise.all([
        fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20&group_events=true`, {
          next: { revalidate: 60 },
        }),
        fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
        fetch(`${API_URL}/api/theses?page=1&per_page=5`, {
          next: { revalidate: 60 },
        }),
        fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
        fetch(`${API_URL}/api/scoreboard`, { next: { revalidate: 60 } }),
      ]);

    const marketsData = marketsRes.ok ? await marketsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;
    const thesesData = thesesRes.ok ? await thesesRes.json() : null;
    const walletsData = walletsRes.ok ? await walletsRes.json() : null;
    const scoreboardData = scoreboardRes.ok ? await scoreboardRes.json() : null;

    return {
      markets: marketsData?.markets || [],
      total: marketsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
      theses: thesesData?.theses || thesesData || [],
      topWallets: walletsData?.wallets || [],
      scoreboard: scoreboardData,
    };
```

- [ ] **Step 2: Add `scoreboard` to the catch fallback**

The `catch` return (line 35) must also include the new key so the shape is stable. Change it to:

```javascript
    return { markets: [], total: 0, tags: [], theses: [], topWallets: [], scoreboard: null };
```

- [ ] **Step 3: Destructure and pass to `HomeClient`**

Change the `HomePage` destructure (line 40) to include `scoreboard`:

```javascript
  const { markets, total, tags, theses, topWallets, scoreboard } = await getHomeData();
```

And add the prop to the `<HomeClient ... />` element (lines 282-288):

```jsx
      <HomeClient
        initialMarkets={markets}
        initialTotal={total}
        tags={tags}
        initialTheses={theses}
        topWallets={topWallets}
        scoreboard={scoreboard}
      />
```

- [ ] **Step 4: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/page.jsx
git commit -m "feat(home): fetch /api/scoreboard server-side and pass to HomeClient"
```

---

## Task 5: Reorder homepage, mount proof components, remove Ticker

**Files:**
- Modify: `frontend/src/app/home-client.jsx`

- [ ] **Step 1: Update imports**

In `frontend/src/app/home-client.jsx`, remove the `Ticker` import (line 8: `import Ticker from "../components/Ticker";`) and add the two new components. After the existing component imports (near line 17), add:

```javascript
import ScoreboardHero from "../components/ScoreboardHero";
import RecentCalls from "../components/RecentCalls";
```

- [ ] **Step 2: Accept the `scoreboard` prop**

Change the component signature (line 29) from:

```javascript
export default function HomeClient({ initialMarkets, initialTotal, tags, initialTheses, topWallets }) {
```
to:
```javascript
export default function HomeClient({ initialMarkets, initialTotal, tags, initialTheses, topWallets, scoreboard }) {
```

- [ ] **Step 3: Mount the proof components and remove the Ticker section**

In the returned JSX: directly after `<TopicNav />` (line 180) and BEFORE `{/* Today's Top 3 */}`, insert:

```jsx
      {/* Proof: graded track record + recent receipts */}
      <ScoreboardHero scoreboard={scoreboard} />
      <RecentCalls recent={scoreboard?.recent} />
```

Then DELETE the entire live-ticker section (lines 187-190):

```jsx
      {/* Live ticker — hidden on mobile, duplicates feed */}
      <section aria-label="Live ticker" className="hidden sm:block mb-5 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
        <Ticker />
      </section>
```

- [ ] **Step 4: Lint**

Run: `cd frontend && npm run lint`
Expected: no new errors, and no "Ticker is defined but never used" (the import was removed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/home-client.jsx
git commit -m "feat(home): lead with scoreboard + receipts, remove redundant ticker"
```

---

## Task 6: Relabel TopThree as "Today's sharpest calls"

**Files:**
- Modify: `frontend/src/components/TopThree.jsx`

- [ ] **Step 1: Update the heading and aria-label**

In `frontend/src/components/TopThree.jsx`:
- Change the `<section aria-label="Today's top 3" ...>` (line 33) to `aria-label="Today's sharpest calls"`.
- Change the `<h2>` text (lines 38-40) from `Today&rsquo;s top 3` to `Today&rsquo;s sharpest calls`.

The surrounding markup, subtitle, and `HowWePickPopover` stay unchanged.

- [ ] **Step 2: Lint + build (full verification)**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint clean; build completes. (During build, server-side fetches to the API may fail if the API is unreachable — that is caught in `getHomeData` and returns `scoreboard: null`, so the page still builds; `ScoreboardHero` renders its cold-start state.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TopThree.jsx
git commit -m "feat(home): relabel Top 3 as Today's sharpest calls"
```

---

## Manual verification (after Task 6)

Point the frontend at the hosted API and eyeball the homepage:

```bash
cd frontend && NEXT_PUBLIC_API_URL=https://api.polyspotter.com npm run dev
# open http://localhost:3000
```

Confirm:
- The scoreboard hero appears at the top (below the header/topic nav). If `/api/scoreboard` has < 10 graded calls, it shows the "building our track record" copy instead of numbers — expected until `grade_worker` has graded enough markets in prod.
- The receipts strip appears only when there are ≥ 3 recent graded calls; chips are green ✓ / red ✗ with signed % and link to event pages.
- The live ticker is gone.
- "Today's sharpest calls" is the Top-3 heading.

---

## Self-Review Notes

- **Spec coverage (subsystem C, this slice):** ScoreboardHero (Task 2) ✓; RecentCalls receipts (Task 3) ✓; server fetch + threading (Tasks 1, 4) ✓; reorder so proof leads + Ticker removed (Task 5) ✓; Top 3 reframed (Task 6) ✓; cold-start "building" state + receipts hidden < 3 (Tasks 2, 3) ✓. **Deferred (stated):** email-capture form + `SharpsLeaderboard` → Plan 3 / later (email form needs the Plan 3 subscribe endpoint).
- **No placeholders:** every component and edit is complete, copy-paste runnable.
- **Type/shape consistency:** `ScoreboardHero`/`RecentCalls` consume exactly the `window`/`all_time`/`recent` shape that Plan 1's `/api/scoreboard` returns; `scoreboard` prop flows page.jsx → HomeClient → both components; the catch-path returns `scoreboard: null` so the components' null-guards apply.
- **No FE test harness:** verification is `npm run lint` + `npm run build` + the manual check above — consistent with the project (no jest/vitest present). Not adding one.

## Deferred to later plans

- **Plan 3 (Email loop):** `subscribers` table, `POST /api/subscribe`, `EmailCapture` form (wired into `ScoreboardHero` and a repeat at the foot of the feed), `digest_worker.py`, Resend integration.
- **Later:** `SharpsLeaderboard` (uses existing `/api/wallets/top` + `pseudonym.js`/`tiers.js`), `TopThreeFollowStrip` consolidation.
