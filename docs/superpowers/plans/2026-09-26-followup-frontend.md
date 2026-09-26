# Frontend follow-up (PR D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the hydration, sitemap, error-handling, SEO and hygiene findings in section 4 of the 2026-09-26 handoff.

**Architecture:** Next.js 15/16 App Router app in `frontend/` (React 19, Tailwind 4). Pages are ISR (`revalidate=60`) and several client components render time-dependent values during SSR. No test runner is configured; the gates are `npm run lint` and `npm run build`, plus small pure helpers that can be unit-checked with `node --test` where a helper is extracted. Worktree: `.worktrees/frontend-followup` (dependencies already installed with `npm ci`), branch `fix/frontend-followup`.

**Tech Stack:** Next.js (see `frontend/package.json`), React 19, ESLint via `npm run lint`.

---

### Task 1: `useNow()` and hydration-safe time rendering (handoff 4)

**Files:**
- Create: `frontend/src/hooks/useNow.js`
- Modify: `frontend/src/components/AlertRow.jsx` (~151–170), `frontend/src/app/market/.../market-page-client.jsx` (~57, 72–73), `frontend/src/components/AlertList.jsx` (~205–209, 318–336), `frontend/src/components/TopicNav.jsx` (~34–50), `frontend/src/components/PreGameStats.jsx` (~33–37), `frontend/src/app/event/.../event-page-header.jsx` (~19–27)

- [ ] Implement `useNow(tickMs = 30000)`: `useState(null)`, set `Date.now()` in `useEffect`, interval tick; returns `null` during SSR and the first client render.
- [ ] In each listed component, compute relative times and resolution badges from `useNow()`; when it is `null`, render the server-safe form (absolute UTC timestamp or no badge) so server and client markup match. For `toLocaleTimeString` calls pass `{ timeZone: "UTC" }` or render only after `now` is set.
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): hydration-safe time rendering via useNow()`.

### Task 2: Sitemap index for markets (handoff 4)

**Files:**
- Modify: `frontend/src/app/sitemap-markets.xml/route.js`
- Create: `frontend/src/app/sitemap-markets/[n]/route.js` (or the closest App Router shape that yields `/sitemap-markets-<n>.xml`)
- Modify: `frontend/src/app/sitemap.js` if it references the markets sitemap

- [ ] Make `/sitemap-markets.xml` a `<sitemapindex>` listing `/sitemap-markets-<n>.xml` children of at most 40,000 URLs each, computed from a single count call to the backend; children fetch their page slice. Replace `no-store` with `revalidate = 3600`.
- [ ] Extract `chunkCount(total, size)` into `frontend/src/lib/sitemap.js` and add `frontend/src/lib/sitemap.test.js` runnable with `node --test frontend/src/lib/sitemap.test.js` (0 → 1 child, 40000 → 1, 40001 → 2).
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): split the markets sitemap into an index with 40k-URL children`.

### Task 3: Only a 404 is a 404 (handoff 4)

**Files:**
- Modify: wallet, event, thesis, digest and article page components under `frontend/src/app/` that call `notFound()` after a failed fetch; `frontend/src/lib/api.js` if it swallows status codes.

- [ ] Make the API client surface the HTTP status (throw an error with `.status`, or return `{ status }`). In each page, call `notFound()` only when `status === 404`; rethrow otherwise so Next renders the error boundary (a 500), never a soft 404.
- [ ] Market page: call `notFound()` when the backend returns 404 for the market (today it never does).
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): 5xx from the API is not a 404`.

### Task 4: Public URLs in markup; encoded path params (handoff 4)

**Files:**
- Modify: `frontend/src/app/article/[date]/[slug]/page.jsx` (~39–41), `frontend/src/lib/apiBase.js`, any other place that puts `API_URL_SERVER` into HTML (grep `API_URL_SERVER` and `apiBase` under `src/`), and every `fetch(`${base}/api/.../${param}`)` that does not `encodeURIComponent(param)`.

- [ ] Add `publicApiBase()` to `apiBase.js` returning the public API origin (`NEXT_PUBLIC_API_URL` / `API_URL_BUILD` / `https://api.polyspotter.com` fallback) and use it for anything rendered into markup (og:image, JSON-LD, `<img src>`); keep `API_URL_SERVER` for server fetches only.
- [ ] Encode path params in backend URL construction.
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): public API origin in markup; encode path params`.

### Task 5: Tag slug round trip (handoff 4)

**Files:**
- Modify: `frontend/src/app/tag/[slug]/page.jsx` (or equivalent), `frontend/src/lib/slugify.js`

- [ ] Resolve an incoming tag slug against `/api/tags`: fetch the tag list, find the tag whose `slugify(tag)` equals the slug, query the backend with the exact tag; 404 if none matches. Add `frontend/src/lib/slugify.test.js` (`node --test`) covering "Spider-Man", "US-Iran", "Trump-Netanyahu" round-tripping through a `resolveTagSlug(slug, tags)` helper.
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): resolve tag slugs against /api/tags`.

### Task 6: PriceChart and CommandPalette races (handoff 4)

**Files:**
- Modify: `frontend/src/components/PriceChart.jsx` (~13, 64–76), `frontend/src/components/CommandPalette.jsx` (~132–153)

- [ ] PriceChart: keep the range buttons rendered when a range returns fewer than 2 points (show an empty-state message inside the chart area); guard range fetches with a request counter or `AbortController` so a slow earlier range cannot overwrite a later selection.
- [ ] CommandPalette: create an `AbortController` per debounced query and abort the previous one; ignore results whose query no longer matches the input.
- [ ] `npm run lint && npm run build`; commit: `fix(frontend): PriceChart empty ranges and CommandPalette fetch races`.

### Task 7: SEO hygiene and dead code (handoff 4)

**Files:**
- Modify: article page metadata (duplicate "· PolySpotter | PolySpotter"), every JSON-LD `<script>` (grep `application/ld+json`), and the components below
- Delete: `frontend/src/components/AlertTable.jsx`, `MarketCard.jsx`, `AlertDetail.jsx`, `HeroSpotlight.jsx`, `SearchBar.jsx`, `frontend/src/hooks/useSpotlight.js` — only after `grep -rn` confirms no imports

- [ ] Add `frontend/src/lib/jsonld.js` with `safeJsonLd(obj)` = `JSON.stringify(obj).replace(/</g, "\\u003c")` and a `node --test` case for `</script>`; use it in every JSON-LD block.
- [ ] Fix the article title template so the site name appears once.
- [ ] Delete the unused files.
- [ ] `npm run lint && npm run build`; commit: `chore(frontend): JSON-LD escaping, single site-name suffix, remove dead components`.

### Task 8: `npm audit fix` (handoff 4)

- [ ] Run `npm audit` and record the counts; run `npm audit fix` (never `--force`); re-run `npm audit`; `npm run lint && npm run build`. If the build breaks, revert the lockfile change and report which advisory needs a major bump.
- [ ] Commit: `chore(frontend): npm audit fix`.

### Task 9: Final check

- [ ] `npm run lint` and `npm run build` clean; `node --test` for the three helper tests.
- [ ] Report status with commits, the audit before/after counts, and anything skipped.
