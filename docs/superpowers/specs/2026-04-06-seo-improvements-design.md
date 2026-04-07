# SEO Improvements — Organic Traffic & Rich Results

**Date:** 2026-04-06
**Goal:** Increase organic search traffic and earn Google rich results for existing page types (markets, wallets, tags, theses, alerts, homepage) — no new page types.

## Current State

The frontend already has a strong SEO foundation:
- Metadata (`generateMetadata()`) on all pages with OG/Twitter tags
- JSON-LD structured data (WebSite, ItemList, FAQPage, Article, ProfilePage, BreadcrumbList, CollectionPage)
- Dynamic sitemap + robots.txt
- Server-rendered `.seo-content` blocks with semantic HTML hidden from visual users
- OG image generation (homepage, markets, alerts)
- URL canonicalization middleware (301 redirects for old URLs)
- ISR with 60s revalidation

## Design

### 1. LLM-Enriched Market Page Content

At market ingest time, the backend calls the LLM to generate all SEO fields for a market in a **single API call**. This content is stored in PostgreSQL and served via the existing market API endpoint.

**LLM integration:** Uses the same Azure OpenAI setup as `llm_filter.py` — same client pattern (`OpenAI` with `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY`), same model (`gpt-5.4`), structured JSON output via `response_format` with a `json_schema`. One call per market, all fields returned together.

**Generated fields (single call):**
- `seo_summary` (string) — 2-3 sentence plain-language market explainer, targeting queries like "[topic] prediction market odds"
- `seo_faqs` (JSON array of `{question, answer}`) — 3-5 FAQ pairs (e.g., "What are the current odds on X?", "When does this market resolve?", "What is the smart money doing on X?")
- `seo_title` (string) — keyword-optimized title (e.g., "Trump 2026 Prediction Market Odds & Smart Money Signals")
- `seo_description` (string) — click-optimized meta description, ~155 chars

**LLM input context:** Market title, description, category, resolution date, current odds, recent alert headlines, volume data — all available at ingest time.

**Storage:** New columns on the market table in PostgreSQL:
- `seo_summary TEXT`
- `seo_faqs JSONB`
- `seo_title TEXT`
- `seo_description TEXT`
- `seo_generated_at TIMESTAMPTZ`

**Regeneration:** None for now. Generate once per market at ingest time. Skip if `seo_generated_at` is already set.

**Backend changes:**
- New module/function for LLM SEO generation, following the same pattern as `llm_filter.py` (Azure OpenAI client, structured JSON response schema, system prompt + user prompt)
- Call this during market ingest (or as a post-ingest step) — skip if `seo_generated_at` is already set
- Expose `seo_*` fields in the market API response
- New DB migration adding the columns

**Frontend changes:**
- Market page `generateMetadata()` uses `seo_title` and `seo_description` when available, falls back to current behavior
- Market page `.seo-content` block renders `seo_summary` and `seo_faqs` as semantic HTML
- Market page `FAQPage` JSON-LD uses `seo_faqs` when available instead of alert-headline-based FAQ

### 2. Keyword-Optimized Titles & Meta Descriptions

Improve `generateMetadata()` output across all page types to target real search intents.

**Market pages:** Use LLM-generated `seo_title` / `seo_description` (see section 1). Fallback to current behavior if empty.

**Wallet pages:**
- Title: `"Polymarket Whale Trader 0xABC… — $X Total P&L | PolySpotter"` (include truncated address + P&L)
- Description: Include win rate, top market names, total volume

**Tag pages:**
- Title: `"[Tag] Prediction Markets — Smart Money Signals | PolySpotter"`
- Description: Include market count and recent signal summary

**Thesis pages:**
- Title: `"[Headline] — Cross-Market Analysis | PolySpotter"`
- Description: Mention number of correlated markets and core thesis

**Homepage:**
- Title: `"PolySpotter — Polymarket Smart Money Tracker"` (keep as-is)
- Description: More keyword-rich — mention whale trades, sharp bettors, prediction market odds, large bets

### 3. Technical SEO Fixes

#### 3a. Pagination Links
Tag pages with `?page=N`: add `rel="next"` / `rel="prev"` in `generateMetadata()` alternates.

#### 3b. Canonical URLs for Pagination
- Page 1: canonical = `/tag/[slug]` (no query param)
- Page 2+: canonical = `/tag/[slug]?page=N`

#### 3c. Resource Hints
Add to root layout `<head>`:
```html
<link rel="preconnect" href="https://api.polyspotter.com" />
<link rel="dns-prefetch" href="https://api.polyspotter.com" />
```

#### 3d. Favicon Set
Add `apple-touch-icon.png` (180x180) and a `manifest.json` / `site.webmanifest` with multiple icon sizes. Reference in root layout metadata.

#### 3e. Wallet Pages in Sitemap
Add top wallets to `sitemap.js` — wallets with 5+ alerts or significant P&L. Fetch from API. Priority 0.6, frequency daily.

#### 3f. Homepage Breadcrumb
Add `BreadcrumbList` JSON-LD to homepage: single item `[{name: "Home", url: "/"}]`.

### 4. Internal Linking

Add contextual `<a>` links in `.seo-content` blocks using data already in API responses:

**Market pages →**
- Wallets that triggered alerts on this market
- The market's tag page
- Related theses

**Wallet pages →**
- Top markets by trade volume or alert count

**Tag pages →**
- Related tags (e.g., "Politics" → "Elections", "US Politics") — based on shared markets or manual mapping

**Thesis pages →**
- Each constituent market page

**Homepage →**
- Top tags section in SEO content
- Top wallets section in SEO content (in addition to existing top markets)

### 5. Rich Results Enhancements

#### 5a. Richer FAQPage on Market Pages
Use LLM-generated FAQ pairs (from section 1) instead of current alert-headline-based FAQ. More natural Q&A phrasing increases the chance Google renders FAQ dropdowns in search results.

#### 5b. Homepage SiteNavigationElement
Add `SiteNavigationElement` JSON-LD for main nav links (Markets/Tags/Wallets) to help Google understand site hierarchy.

#### 5c. Wallet ProfilePage Enhancement
Extend existing `ProfilePage` schema: add `knowsAbout` array listing market categories (tags) this wallet trades in.

## Implementation Order

1. **Backend: LLM SEO generation** — DB migration, Claude API integration, generation logic, expose in API
2. **Frontend: Market pages** — consume `seo_*` fields in metadata + SEO content + JSON-LD
3. **Frontend: Titles & meta descriptions** — update `generateMetadata()` across all page types
4. **Frontend: Technical fixes** — pagination links, canonicals, resource hints, favicons, sitemap, breadcrumb
5. **Frontend: Internal linking** — add cross-links in `.seo-content` blocks
6. **Frontend: Rich results** — SiteNavigationElement, wallet schema enhancement

Steps 3-6 can be parallelized once step 2 is done. Step 1 must come first.

## Out of Scope

- New page types (blog, glossary, guides)
- `Event` schema on market pages
- Internationalization / hreflang
- Full blog or content marketing infrastructure
