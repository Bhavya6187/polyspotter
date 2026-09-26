# Recon: Section 5 (Astro edge layer + bot-freshness monitoring), 2026-09-26 ~18:45 UTC

## URGENT side-finding
The scanner has been down for about 7 days. The newest alert is `scanned_at` 2026-09-19 21:22 UTC. Live `GET https://api.polyspotter.com/api/health` returns **503** `{"status":"stale","seconds_since_latest_alert":595412}`. `/api/healthz?upstream=1` on the frontend also shows `upstreamStatus: 503`. Digests and tweets both stopped on 2026-09-15 (details in Task B). Either the uptime monitor is not alerting or nobody acted on it.

## Task A: the Astro layer

### DNS
| Query | Result |
|---|---|
| `dig +short polyspotter.com` | 172.67.185.196, 104.21.19.104 (Cloudflare anycast, proxied/orange) |
| `dig +short www.polyspotter.com` | same two Cloudflare IPs |
| `dig +short CNAME polyspotter.com` | (none; apex is flattened or A records) |
| `dig +short NS polyspotter.com` | bryce.ns.cloudflare.com, ivy.ns.cloudflare.com (the zone is on the user's own Cloudflare account) |
| `api.polyspotter.com` | CNAME h5fyat3k.up.railway.app → 69.46.46.86 (grey-clouded, direct to Railway) |
| TXT apex | apple-domain, google-site-verification, SPF (icloud). No Ploy/Pages verification record visible |

Railway (`mcp list-domains`, heroic-miracle): custom domain `polyspotter.com` (port 8080), service domain `heroic-miracle-production.up.railway.app`. Frontend variable names: API_URL_BUILD, API_URL_SERVER, NODE_OPTIONS, **ORIGIN_AUTH_SECRET**, VITE_API_URL, RAILWAY_* (RAILWAY_PUBLIC_DOMAIN=polyspotter.com).

### Evidence table (edge = https://polyspotter.com; origin = https://heroic-miracle-production.up.railway.app)
Every edge response carries `server: cloudflare`, `cf-ray`, `__cf_bm` set-cookie, **and `x-request-id` (8 hex), `x-response-time`, `x-frame-options: SAMEORIGIN`, `x-xss-protection`, `x-content-type-options`**. The origin does **not** send those five headers (origin returns `server: railway-hikari` plus the x-railway-*/x-nextjs-* headers only). So a layer in front of Railway adds them to every path, including the Next.js paths.

| Path (edge) | Status | Served by | Notable |
|---|---|---|---|
| `/` | 200 | Next.js via Railway | x-railway-edge: lax1, x-nextjs-cache: STALE, cf-cache DYNAMIC |
| `/robots.txt` | 200 | **Astro/Ploy** | no x-railway-edge; cf-cache HIT. Body lists Googlebot/Bingbot/Twitterbot/fb/* Allow, `Sitemap: /sitemap-index.xml` + `/sitemap.xml`. It does not list the market/wallet sitemaps and has none of Next's `Disallow` rules |
| `/sitemap.xml` | 200 | **Ploy** | sitemapindex → `/sitemap-0.xml` + `/proxied-sitemap-0.xml` |
| `/sitemap-0.xml`, `/sitemap-index.xml` | 200 | **Ploy** | sitemap-0 = 4 URLs: /blog, 2 blog posts, / |
| `/proxied-sitemap-0.xml` | 200 | **Ploy** (content = Next `/sitemap.xml`) | 5,131 URLs (/, 19 /article, 101 /digest, 5,000 /event, 10 /tag), identical count to origin `/sitemap.xml`; no x-railway-edge. `/proxied-sitemap-1.xml` → 404 (no Astro body, no Railway) |
| `/sitemap-markets.xml` | **404** | **Ploy (Astro 404 HTML)** | origin serves it 200 with **49,541** URLs |
| `/sitemap-wallets.xml` | **404** | **Ploy (Astro 404)** | origin serves it 200 with **10,604** URLs |
| `/tag/politics`, `/tag/sports` | 200 | **Ploy Astro** | "Posts tagged politics", "No posts with this tag yet.", canonical to the same URL, `robots index,follow`. Origin `/tag/sports` = 200 Next tag page (5.1s) |
| `/tag` | 404 Astro; `/tag/` → 301 /tag | Ploy | |
| `/blog` | 200 | Ploy Astro | cf-cache HIT; `/blog/` → 307 /blog; `/blog/foo` → 302 /404. Origin `/blog` → 404 |
| `/_ploy_static/*` | 200/404 | Ploy | Astro CSS assets |
| `/market/southeastern-louisiana-vs-louisiana-monroe-0x1934a` | 200 | Next via Railway | x-railway-edge lax1 |
| `/digest`, `/favicon.ico`, `/llms.txt`, `/article`, `/event`, `/wallet`, `/404`, `/robots`, `/ploy`, `/proxied-foo`, `/nonexistent-xyz` | 200/404 | Next via Railway | x-railway-edge present |
| `/api/healthz?upstream=1` | 200 | Next via Railway | `{"reachable":true,"route":"private-network","upstreamStatus":503}` |

Probing which prefixes Ploy captures (Astro 404 body, no x-railway-edge): `/sitemap`, `/sitemapfoo`, `/sitemap/markets.xml`, `/sitemap-markets`, `/sitemap_index.xml`, `/tagx`, `/tags`, `/blogx`, `/_ploy_static/x`. Probes that fall through to Railway: `/robots` (without .txt), `/proxied-foo`, `/ploy`, `/404`.

**Captured patterns (inferred):** `/robots.txt` (exact), `/sitemap*` (every path that starts with "sitemap"), `/proxied-sitemap-N.xml`, `/tag*` (prefix match without a slash boundary, so `/tags` is captured too), `/blog*`, `/_ploy_static/*`. Everything else is proxied to the Railway origin.

With `curl -H 'Host: polyspotter.com'` against the origin, every path behaves exactly like the direct origin: robots.txt = Next robots.js (with the 3 Sitemap lines and the Disallows), sitemap-markets/wallets 200, /tag/politics 200 Next, /blog 404, /proxied-sitemap-0.xml 404. **The Next app and Railway are fine. The override happens upstream of Railway.**

### Repo evidence
- `frontend/next.config.js` has no rewrites, redirects or headers. There is no `middleware.*` in frontend/.
- There are no "astro", "ploy" or "proxied-sitemap" references in tracked files (only the HANDOFF note). The only "blog" reference is `frontend/src/components/HeaderActions.jsx` (header nav link to `/blog`), added in commit `adddbb5` 2026-06-17 "chore(frontend): point header nav link to /blog (#36)". The blog was deliberately wired to an external host around June 2026.
- The heroic-miracle variable `ORIGIN_AUTH_SECRET` exists but nothing in the repo reads it. It probably came from the Ploy setup (origin auth), and per memory, headers injected on the orange-to-orange path get stripped.

### Conclusion A
- **What serves the Astro pages:** "Ploy", a hosted Astro blog/SEO product (`ploy-astro-starter-version 1.0.0`, `/_ploy_static/`, `window.__ployExperiments` A/B tracker). It sits in the request path on the **polyspotter.com Cloudflare zone**, almost certainly as a **Cloudflare Worker on route `polyspotter.com/*`**. The evidence is that it adds the same `x-request-id`/`x-response-time`/security headers to *every* response, Railway-proxied ones included. It serves its own routes, generates a sitemap index that merges Next's `/sitemap.xml` as `proxied-sitemap-0.xml`, and passes all other paths through to Railway. Cloudflare Pages or a separate Railway service are ruled out: Railway has only the one custom domain, and Pages cannot proxy paths to an origin like this without a Worker/Function. A Ploy-operated Worker attached via Cloudflare for SaaS/custom hostname is possible, but NS points at the user's own zone.
- **Why `/sitemap-markets.xml` is unreachable:** Ploy claims the whole `/sitemap*` prefix. It proxies and renames only the single `/sitemap.xml` from origin (as `proxied-sitemap-0.xml`) and returns its own Astro 404 for any other `/sitemap*` path, so the request never reaches Next. It also replaces `/robots.txt` with its own file, which drops the `Sitemap:` lines for markets and wallets. Crawlers therefore learn of neither sitemap, and fetching them directly gets a 404. Same mechanism for `/tag/*`: Ploy's empty "posts tagged X" pages shadow the Next tag pages (canonical + index,follow, so the real tag pages are replaced in the index by thin empty pages).
- **Missing evidence / where to confirm:** Cloudflare dashboard → polyspotter.com → **Workers Routes** (Workers & Pages → the Ploy worker → Settings → Domains & Routes), plus that worker's route/path config. Also check **Rules → Transform/Redirect/Origin Rules** and **SSL/TLS → Custom Hostnames** in case Ploy is attached via Cloudflare for SaaS. In the Ploy dashboard, look for the "proxied paths" / sitemap-merge settings, i.e. whether extra origin sitemaps can be registered or `/tag` and `/sitemap*` can be excluded.

## Task B: monitoring gap

### Current `/api/health` (backend/app.py:2268)
`GET`/`HEAD`. Runs a single query: `COUNT(*)`, `MAX(scanned_at)`, `EXTRACT(EPOCH FROM NOW()-MAX(scanned_at))::BIGINT` from `alerts`. It uses **scanned_at, not created_at**. The result is fresh iff seconds ≤ 3600; otherwise the handler sets status 503. It returns `{status: "ok"|"stale", alert_count, latest_scanned_at (iso|null), seconds_since_latest_alert}`. Live right now: 503, stale, 201,172 alerts, latest_scanned_at 2026-09-19T21:22:22Z, 595,412 s.

### Freshness facts available (read-only queries, DB now() = 2026-09-26 18:45:46 UTC)
| Source | Columns | Newest value | Age |
|---|---|---|---|
| `digests` | id, digest_date DATE UNIQUE, run_id, subject, intro, content_json, status ('draft'/'published'), created_at, published_at | digest_date **2026-09-15**, id 102, status published, created_at = published_at = 2026-09-15 13:01:12 UTC (100 rows, all published) | ~11.2 days |
| `tweeted_alerts` | alert_id, wallet, condition_id, tweet_id, tweet_text, tweeted_at | tweeted_at **2026-09-15 12:21:50 UTC** (1,018 rows, 0 in the last 24h) | ~11.3 days |
| `graded_calls` | condition_id, alert_id, ..., resolved_at, graded_at | graded_at **2026-09-26 18:29:44 UTC** (7,156 rows, 16 in the last 24h); max resolved_at 2026-09-24 03:59 | fresh |
| `alerts` | ... scanned_at, created_at ... | created_at **2026-09-19 21:24:51**, scanned_at 2026-09-19 21:22:22 | ~6.9 days |
| (extra) `articles` | published_date, created_at, posted_at, status | published_date 2026-05-10, 19 published | articlebot stale since May (may be intentional) |
| (extra) `grade_attempts.last_attempt_at`, `follower_snapshots.snapshot_date/created_at`, `result_tweets.posted_at` | available if wanted | not queried | |

**No "digest sent" timestamp exists anywhere.** `digests` has only created_at/published_at, which are identical on insert. `subscribers` has created_at/unsubscribed_at only, and there is no send-log table. A `/api/health/bots` endpoint can therefore report "digest generated", not "digest emailed". A true sent signal needs a new column (e.g. `digests.sent_at`) or a send-log table.

Suggested thresholds from the data: digest daily at ~13:00 UTC, so stale if `max(digest_date) < current_date - 1` or published_at older than 26h. Tweets: stale if max(tweeted_at) is older than N h (need the loop cadence, likely 6–12h). Grading runs every 30 min, so stale if graded_at is older than ~2h (it can legitimately be quiet if nothing resolves; `grade_attempts.last_attempt_at` is a better liveness signal). Alerts: reuse the scanned_at > 3600s rule.

## Open questions
1. Who set up Ploy, and do they have Ploy dashboard access? Can Ploy (a) exclude `/tag*` and pass it through, (b) pass through or merge `/sitemap-markets.xml` and `/sitemap-wallets.xml`, (c) pass through `/robots.txt` or append Sitemap lines? If not, the Worker route has to be narrowed in Cloudflare (e.g. `polyspotter.com/blog*` + `/_ploy_static/*` only), and the blog URLs added to Next's sitemap.
2. Confirm in Cloudflare → Workers Routes that the route is `polyspotter.com/*` (vs a Custom Hostname / SaaS setup).
3. `ORIGIN_AUTH_SECRET` on heroic-miracle is unused by the code. Was it for Ploy→origin auth? Safe to remove?
4. The scanner (since 09-19), digest and tweet loops (since 09-15) are all down right now. Is the 503 from `/api/health` wired to any monitor that notifies someone?
5. Tweet-loop cadence, to set the staleness threshold for `tweeted_alerts`.
