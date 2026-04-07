# SEO Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase organic search traffic and earn Google rich results for existing pages via LLM-enriched market content, keyword-optimized metadata, technical SEO fixes, internal linking, and structured data enhancements.

**Architecture:** Backend generates SEO content per market via Azure OpenAI (same pattern as `llm_filter.py`) at ingest time, stored in PostgreSQL, served via the market API. Frontend consumes these fields in `generateMetadata()` and `.seo-content` blocks. Non-LLM improvements (titles, technical fixes, linking, schemas) are frontend-only changes to existing pages.

**Tech Stack:** Python/FastAPI, PostgreSQL, Azure OpenAI (gpt-5.4), Next.js 15, React 19

---

## File Structure

**Backend (new/modified):**
- Create: `backend/seo_generator.py` — LLM SEO content generation (system prompt, schema, generate function)
- Modify: `backend/schema.sql` — add `seo_*` columns to `alerts` table
- Modify: `backend/database.py` — add migration for new columns
- Modify: `backend/app.py` — call SEO generator during ingest, expose fields in market API
- Modify: `backend/models.py` — add `seo_*` fields to `MarketGroup` response model

**Frontend (modified):**
- Modify: `frontend/src/app/market/[id]/page.jsx` — consume SEO fields, update metadata + JSON-LD + seo-content
- Modify: `frontend/src/app/page.jsx` — add top wallets/tags internal links, SiteNavigationElement schema
- Modify: `frontend/src/app/wallet/[address]/page.jsx` — update title/description, add market links, enhance ProfilePage schema
- Modify: `frontend/src/app/tag/[slug]/page.jsx` — update title/description, add pagination links
- Modify: `frontend/src/app/thesis/[id]/page.jsx` — update title/description
- Modify: `frontend/src/app/layout.jsx` — add preconnect/dns-prefetch hints
- Modify: `frontend/src/app/sitemap.js` — add top wallet pages

---

### Task 1: Backend — Add SEO columns to database

**Files:**
- Modify: `backend/schema.sql:5-47` (alerts table)
- Modify: `backend/database.py:67-86` (migrations)

- [ ] **Step 1: Add SEO columns to schema.sql**

Add after the `llm_copy_action` column (line 39) in the `alerts` table definition:

```sql
    -- LLM-generated SEO content for market pages
    seo_title       TEXT,
    seo_description TEXT,
    seo_summary     TEXT,
    seo_faqs        TEXT DEFAULT '[]',   -- JSON array of {question, answer}
    seo_generated_at TIMESTAMPTZ,
```

- [ ] **Step 2: Add migration in database.py**

Add a new migration function after `_migrate_add_market_media`:

```python
def _migrate_add_seo_fields(cur):
    """Add SEO content columns if they don't exist."""
    for col, default in [
        ("seo_title", "NULL"),
        ("seo_description", "NULL"),
        ("seo_summary", "NULL"),
        ("seo_faqs", "'[]'"),
        ("seo_generated_at", "NULL"),
    ]:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name = %s
        """, (col,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT DEFAULT {default}")
```

Call it from `init_db()` after `_migrate_add_market_media(cur)`:

```python
            _migrate_add_seo_fields(cur)
```

- [ ] **Step 3: Verify migration runs cleanly**

Run: `cd /Users/bhavya/git/polybot && source venv/bin/activate && cd backend && python -c "from database import init_db; init_db(); print('OK')"`

Expected: `OK` (no errors)

- [ ] **Step 4: Commit**

```bash
git add backend/schema.sql backend/database.py
git commit -m "feat(backend): add SEO content columns to alerts table"
```

---

### Task 2: Backend — Create SEO content generator module

**Files:**
- Create: `backend/seo_generator.py`

- [ ] **Step 1: Create seo_generator.py**

```python
"""
SEO content generator — calls Azure OpenAI to produce SEO-optimized content
for market pages (title, description, summary, FAQs) in a single API call.

Follows the same Azure OpenAI pattern as llm_filter.py.
"""

from __future__ import annotations

import json
import os

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://gpt-5-mati-labs.cognitiveservices.azure.com/openai/v1/"
MODEL = "gpt-5.4"

SYSTEM_PROMPT = (
    "You are an SEO content specialist for PolySpotter, a Polymarket smart money tracker. "
    "Given a prediction market's metadata, generate SEO-optimized content for the market's page.\n\n"

    "## Guidelines\n"
    "- Write for humans searching Google for prediction market odds, outcomes, and analysis.\n"
    "- Target search queries like '[topic] prediction market odds', '[topic] Polymarket', "
    "'will [outcome] happen prediction market'.\n"
    "- Use natural language, not keyword stuffing.\n"
    "- FAQs should be genuine questions a searcher would ask about this specific market.\n"
    "- Keep the summary informative and factual — mention current odds, what the market covers, "
    "and when it resolves.\n"
    "- The SEO title should be keyword-rich but readable (under 60 chars ideal).\n"
    "- The meta description should be click-worthy and under 155 characters.\n\n"

    "## Output format\n"
    "Return JSON with these fields:\n"
    "- seo_title (string): keyword-optimized page title, under 60 chars\n"
    "- seo_description (string): click-optimized meta description, under 155 chars\n"
    "- seo_summary (string): 2-3 sentence plain-language market explainer\n"
    "- seo_faqs (array of objects with 'question' and 'answer' keys): 3-5 FAQ pairs\n"
)

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "seo_content",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "seo_title": {
                    "type": "string",
                    "description": "Keyword-optimized page title, under 60 chars.",
                },
                "seo_description": {
                    "type": "string",
                    "description": "Click-optimized meta description, under 155 chars.",
                },
                "seo_summary": {
                    "type": "string",
                    "description": "2-3 sentence plain-language market explainer.",
                },
                "seo_faqs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "answer": {"type": "string"},
                        },
                        "required": ["question", "answer"],
                        "additionalProperties": False,
                    },
                    "description": "3-5 FAQ pairs about this market.",
                },
            },
            "required": ["seo_title", "seo_description", "seo_summary", "seo_faqs"],
            "additionalProperties": False,
        },
    },
}


def _build_market_prompt(
    market_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> str:
    """Build a user prompt with market context for SEO generation."""
    parts = [f"Market: {market_title}"]
    if description:
        desc = description[:500] + "..." if len(description) > 500 else description
        parts.append(f"Description: {desc}")
    if tags:
        parts.append(f"Category: {', '.join(tags)}")
    if end_date:
        parts.append(f"Resolution date: {end_date}")
    if total_usd > 0:
        parts.append(f"Total smart money tracked: ${total_usd:,.0f}")
    if alert_count > 0:
        parts.append(f"Number of smart money signals: {alert_count}")
    if alert_headlines:
        parts.append("Recent alert headlines:")
        for h in alert_headlines[:5]:
            parts.append(f"  - {h}")
    return "\n".join(parts)


def generate_seo_content(
    market_title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    end_date: str | None = None,
    total_usd: float = 0,
    alert_count: int = 0,
    alert_headlines: list[str] | None = None,
) -> dict | None:
    """Generate SEO content for a market page via Azure OpenAI.

    Returns dict with seo_title, seo_description, seo_summary, seo_faqs,
    or None if generation fails or API key is missing.
    """
    if not AZURE_OPENAI_API_KEY:
        return None

    client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    user_prompt = _build_market_prompt(
        market_title, description, tags, end_date,
        total_usd, alert_count, alert_headlines,
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_completion_tokens=500,
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=RESPONSE_SCHEMA,
        )
        text = response.choices[0].message.content
        result = json.loads(text)
        return {
            "seo_title": result.get("seo_title", ""),
            "seo_description": result.get("seo_description", ""),
            "seo_summary": result.get("seo_summary", ""),
            "seo_faqs": result.get("seo_faqs", []),
        }
    except Exception as e:
        print(f"[seo_generator] ERROR generating SEO content: {e}")
        return None
```

- [ ] **Step 2: Verify module imports cleanly**

Run: `cd /Users/bhavya/git/polybot && source venv/bin/activate && cd backend && python -c "from seo_generator import generate_seo_content; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/seo_generator.py
git commit -m "feat(backend): add SEO content generator using Azure OpenAI"
```

---

### Task 3: Backend — Integrate SEO generation into ingest + expose in API

**Files:**
- Modify: `backend/app.py:168-217` (ingest endpoint)
- Modify: `backend/app.py:499-517` (market grouping query)
- Modify: `backend/models.py:233-245` (MarketGroup model)

- [ ] **Step 1: Add seo_* fields to MarketGroup model**

In `backend/models.py`, add these fields to the `MarketGroup` class (after line 244, before `alerts`):

```python
    seo_title: str | None = None
    seo_description: str | None = None
    seo_summary: str | None = None
    seo_faqs: list[dict] | None = None
```

- [ ] **Step 2: Update market grouping query to include SEO fields**

In `backend/app.py`, update the market grouping SELECT (around line 500) to also fetch SEO fields. Add these to the SELECT:

```sql
                       MAX(a.seo_title) as seo_title,
                       MAX(a.seo_description) as seo_description,
                       MAX(a.seo_summary) as seo_summary,
                       MAX(a.seo_faqs) as seo_faqs
```

Then update the `MarketGroup(...)` constructor (around line 552) to pass them through:

```python
            # Parse SEO FAQs from JSON
            raw_seo_faqs = mrow.get("seo_faqs") or "[]"
            try:
                seo_faqs = json.loads(raw_seo_faqs) if isinstance(raw_seo_faqs, str) else raw_seo_faqs
            except (json.JSONDecodeError, TypeError):
                seo_faqs = []

            markets.append(
                MarketGroup(
                    condition_id=cid,
                    market_title=mrow["market_title"],
                    market_url=mrow["market_url"],
                    market_image=mrow["market_image"],
                    event_slug=mrow["event_slug"],
                    end_date=mrow["end_date"],
                    total_usd=mrow["total_usd"],
                    alert_count=mrow["alert_count"],
                    max_score=mrow["max_score"],
                    tags=all_tags,
                    scanned_at=mrow["scanned_at"],
                    alerts=parsed_alerts,
                    seo_title=mrow.get("seo_title"),
                    seo_description=mrow.get("seo_description"),
                    seo_summary=mrow.get("seo_summary"),
                    seo_faqs=seo_faqs,
                )
            )
```

- [ ] **Step 3: Add SEO generation to ingest endpoint**

In `backend/app.py`, add the import at the top:

```python
from seo_generator import generate_seo_content
```

After the main alert insertion loop (after all alerts, wallet_profiles, price_candles, and theses are inserted — around line 360), add SEO generation for new markets that don't have SEO content yet:

```python
        # Generate SEO content for markets that don't have it yet
        cur.execute("""
            SELECT DISTINCT condition_id, MAX(market_title) as market_title,
                   MAX(market_description) as market_description,
                   MAX(tags) as tags, MAX(end_date::text) as end_date,
                   SUM(total_usd) as total_usd, COUNT(*) as alert_count
            FROM alerts
            WHERE condition_id IS NOT NULL
              AND seo_generated_at IS NULL
              AND market_title IS NOT NULL
            GROUP BY condition_id
            ORDER BY MAX(scanned_at) DESC
            LIMIT 20
        """)
        seo_candidates = cur.fetchall()

        seo_generated = 0
        for row in seo_candidates:
            cid = row["condition_id"]

            # Gather alert headlines for context
            cur.execute("""
                SELECT llm_headline FROM alerts
                WHERE condition_id = %s AND llm_headline IS NOT NULL
                ORDER BY composite_score DESC LIMIT 5
            """, (cid,))
            headlines = [r["llm_headline"] for r in cur.fetchall()]

            tags_list = []
            try:
                tags_list = json.loads(row["tags"] or "[]")
            except (json.JSONDecodeError, TypeError):
                pass

            result = generate_seo_content(
                market_title=row["market_title"],
                description=row.get("market_description"),
                tags=tags_list,
                end_date=row.get("end_date"),
                total_usd=row["total_usd"] or 0,
                alert_count=row["alert_count"] or 0,
                alert_headlines=headlines,
            )

            if result:
                faqs_json = json.dumps(result["seo_faqs"])
                cur.execute("""
                    UPDATE alerts SET
                        seo_title = %s,
                        seo_description = %s,
                        seo_summary = %s,
                        seo_faqs = %s,
                        seo_generated_at = NOW()
                    WHERE condition_id = %s
                """, (
                    result["seo_title"],
                    result["seo_description"],
                    result["seo_summary"],
                    faqs_json,
                    cid,
                ))
                seo_generated += 1
                print(f"[seo] Generated SEO content for: {row['market_title']}")

        if seo_generated:
            print(f"[seo] Generated SEO content for {seo_generated} markets.")
```

- [ ] **Step 4: Test the ingest endpoint still works**

Run: `cd /Users/bhavya/git/polybot && source venv/bin/activate && cd backend && python -c "from app import app; print('App loads OK')"`

Expected: `App loads OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/models.py
git commit -m "feat(backend): generate SEO content at ingest, expose in market API"
```

---

### Task 4: Frontend — Consume SEO fields on market pages

**Files:**
- Modify: `frontend/src/app/market/[id]/page.jsx`

- [ ] **Step 1: Update generateMetadata to use SEO fields**

In `frontend/src/app/market/[id]/page.jsx`, the `generateMetadata` function (line 92) fetches market data including alerts. We need to also fetch the market group data which now includes `seo_title`/`seo_description`. Update the function:

After line 96 (`const { live, alerts } = await getMarketData(conditionId);`), fetch the market group:

```javascript
  // Fetch SEO fields from market group endpoint
  let seoTitle = null, seoDescription = null;
  try {
    const marketGroupRes = await fetch(
      `${API_URL}/api/alerts/by-market?q=${encodeURIComponent(title)}&per_page=1`,
      { next: { revalidate: 60 } }
    );
    if (marketGroupRes.ok) {
      const mgData = await marketGroupRes.json();
      const match = mgData.markets?.find((m) => m.condition_id === conditionId);
      if (match) {
        seoTitle = match.seo_title;
        seoDescription = match.seo_description;
      }
    }
  } catch {}
```

Then update the return to prefer SEO fields (replace lines 122-138):

```javascript
  return {
    title: seoTitle || title,
    description: seoDescription || description,
    alternates: {
      canonical: `/market/${canonicalSlug}`,
    },
    openGraph: {
      title: `${seoTitle || title} | PolySpotter`,
      description: seoDescription || description,
      images: alertId ? [`${siteUrl}/api/og/${alertId}`] : [],
    },
    twitter: {
      card: "summary_large_image",
      title: `${seoTitle || title} | PolySpotter`,
      description: seoDescription || description,
    },
  };
```

- [ ] **Step 2: Update the page component to use SEO summary and FAQs**

In the `MarketPage` component, fetch the market group data to get SEO fields. After `getMarketData` (line 146), add:

```javascript
  // Fetch SEO content from market group
  let seoSummary = null, seoFaqs = [];
  try {
    const mgRes = await fetch(
      `${API_URL}/api/alerts/by-market?q=${encodeURIComponent(title)}&per_page=1`,
      { next: { revalidate: 60 } }
    );
    if (mgRes.ok) {
      const mgData = await mgRes.json();
      const match = mgData.markets?.find((m) => m.condition_id === conditionId);
      if (match) {
        seoSummary = match.seo_summary;
        seoFaqs = match.seo_faqs || [];
      }
    }
  } catch {}
```

Update the FAQ JSON-LD (lines 182-204) to prefer LLM-generated FAQs:

```javascript
  // FAQ JSON-LD — prefer LLM-generated SEO FAQs, fall back to alert-based
  const faqItems =
    seoFaqs.length > 0
      ? seoFaqs.map((faq) => ({
          "@type": "Question",
          name: faq.question,
          acceptedAnswer: {
            "@type": "Answer",
            text: faq.answer,
          },
        }))
      : alerts
          .filter((a) => a.llm_headline && a.llm_summary)
          .slice(0, 5)
          .map((a) => ({
            "@type": "Question",
            name: a.llm_headline,
            acceptedAnswer: {
              "@type": "Answer",
              text:
                a.llm_bullets?.length > 0
                  ? a.llm_bullets.join(" ")
                  : a.llm_summary,
            },
          }));
```

In the `.seo-content` block, add the SEO summary after the H1 (line 227), before the existing `{live?.description && ...}`:

```jsx
          {seoSummary && <p>{seoSummary}</p>}
```

- [ ] **Step 3: Verify the page builds**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/market/\[id\]/page.jsx
git commit -m "feat(frontend): use LLM-generated SEO content on market pages"
```

---

### Task 5: Frontend — Keyword-optimized titles and descriptions for non-market pages

**Files:**
- Modify: `frontend/src/app/wallet/[address]/page.jsx:51-95`
- Modify: `frontend/src/app/tag/[slug]/page.jsx:56-89`
- Modify: `frontend/src/app/thesis/[id]/page.jsx:22-59`
- Modify: `frontend/src/app/page.jsx` (homepage metadata)
- Modify: `frontend/src/app/layout.jsx:40-97`

- [ ] **Step 1: Update wallet page title and description**

In `frontend/src/app/wallet/[address]/page.jsx`, update the `generateMetadata` function.

Replace the title construction (lines 79-81):

```javascript
  const pnlStr = data?.total_pnl != null
    ? new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(data.total_pnl)
    : null;

  const title = tier
    ? `${pseudonym} — ${tier.name} Polymarket Trader${pnlStr ? ` | ${pnlStr} P&L` : ""}`
    : `${pseudonym} — Polymarket Whale Trader`;
```

- [ ] **Step 2: Update tag page title and description**

In `frontend/src/app/tag/[slug]/page.jsx`, update the `generateMetadata` function.

Replace the title construction (lines 63-66):

```javascript
  const title =
    page > 1
      ? `${display} Prediction Market Smart Money Alerts (Page ${page})`
      : `${display} Prediction Markets — Smart Money Signals`;
```

Replace the description fallback (line 67):

```javascript
  const description = tagDesc || `Track smart money signals and whale trades on ${display} prediction markets. See notable bets from sharp bettors on Polymarket.`;
```

- [ ] **Step 3: Update thesis page title and description**

In `frontend/src/app/thesis/[id]/page.jsx`, update the `generateMetadata` function.

Replace the title (line 30):

```javascript
  const title = thesis.thesis_headline
    ? `${thesis.thesis_headline} — Cross-Market Analysis`
    : "Cross-Market Thesis";
```

Replace the description (line 35):

```javascript
  const description = `Cross-market thesis: "${thesis.thesis_headline || "Unknown"}" — ${walletShort}... is betting $${totalUsd.toLocaleString()} across ${marketCount} correlated Polymarket markets. View positions and entry prices on PolySpotter.`;
```

- [ ] **Step 4: Update homepage meta description**

In `frontend/src/app/layout.jsx`, update the meta description (line 49-50):

```javascript
  description:
    "Track whale trades and smart money on Polymarket in real time. PolySpotter surfaces large bets ($3,000+), sharp bettors with proven win rates, and coordinated flow across prediction markets for politics, sports, crypto, and more.",
```

- [ ] **Step 5: Add pagination rel links to tag page metadata**

In `frontend/src/app/tag/[slug]/page.jsx`, in the `generateMetadata` return (around line 73), add pagination links inside the `alternates` object:

```javascript
    alternates: {
      canonical,
      ...(page > 1 && {
        types: { "prev": `/tag/${tagSlug(tag)}${page > 2 ? `?page=${page - 1}` : ""}` },
      }),
    },
```

Note: Next.js metadata API doesn't natively support `rel="next"/"prev"` via `alternates`. We'll handle this via actual `<link>` tags in the component instead. In the `TagPage` component's return (before `<main>`), add:

```jsx
      {page > 1 && (
        <link
          rel="prev"
          href={`/tag/${tagSlug(tag)}${page > 2 ? `?page=${page - 1}` : ""}`}
        />
      )}
      {page < totalPages && (
        <link rel="next" href={`/tag/${tagSlug(tag)}?page=${page + 1}`} />
      )}
```

- [ ] **Step 6: Verify build**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/wallet/\[address\]/page.jsx frontend/src/app/tag/\[slug\]/page.jsx frontend/src/app/thesis/\[id\]/page.jsx frontend/src/app/page.jsx frontend/src/app/layout.jsx
git commit -m "feat(frontend): keyword-optimized titles and descriptions across all pages"
```

---

### Task 6: Frontend — Technical SEO fixes

**Files:**
- Modify: `frontend/src/app/layout.jsx:99-135`
- Modify: `frontend/src/app/sitemap.js`

- [ ] **Step 1: Add resource hints to root layout**

In `frontend/src/app/layout.jsx`, add preconnect and dns-prefetch inside the `<head>` tag (after line 103):

```jsx
        <link rel="preconnect" href="https://api.polyspotter.com" />
        <link rel="dns-prefetch" href="https://api.polyspotter.com" />
```

- [ ] **Step 2: Add apple-touch-icon to metadata**

In `frontend/src/app/layout.jsx`, update the `icons` section in metadata (lines 91-96):

```javascript
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "32x32", type: "image/x-icon" },
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
```

Note: This requires an `apple-touch-icon.png` file in `frontend/public/`. If one doesn't exist, create a 180x180 PNG from the existing favicon.

- [ ] **Step 3: Add top wallets to sitemap**

In `frontend/src/app/sitemap.js`, add wallet pages after the thesis pages section (before the final `return`). Insert before line 99:

```javascript
    // Fetch top wallets for wallet pages
    let walletPages = [];
    try {
      const walletsRes = await fetch(
        `${API_URL}/api/wallets/top?limit=50`,
        { cache: "no-store" }
      );
      if (walletsRes.ok) {
        const walletsData = await walletsRes.json();
        const wallets = walletsData?.wallets || walletsData || [];
        walletPages = wallets.map((w) => {
          const address = typeof w === "string" ? w : w.wallet;
          return {
            url: `${SITE_URL}/wallet/${address.toLowerCase()}`,
            lastModified: new Date(),
            changeFrequency: "daily",
            priority: 0.6,
          };
        });
      }
    } catch {}
```

Update the return to include wallet pages:

```javascript
    return [...staticPages, ...marketPages, ...tagPages, ...thesisPages, ...walletPages];
```

Note: This requires a `/api/wallets/top` endpoint. If it doesn't exist, we'll need to add it — see Step 4.

- [ ] **Step 4: Add top wallets endpoint to backend (if missing)**

Check if `/api/wallets/top` exists. If not, add to `backend/app.py`:

```python
@app.get("/api/wallets/top")
def top_wallets(limit: int = Query(50, ge=1, le=200)):
    """Return top wallet addresses by alert count (for sitemap)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT wallet, COUNT(*) as alert_count
            FROM alerts
            WHERE wallet IS NOT NULL
            GROUP BY wallet
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    return {"wallets": [{"wallet": r["wallet"], "alert_count": r["alert_count"]} for r in rows]}
```

- [ ] **Step 5: Verify build**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/layout.jsx frontend/src/app/sitemap.js backend/app.py
git commit -m "feat: technical SEO fixes — resource hints, apple icon, wallet sitemap"
```

---

### Task 7: Frontend — Internal linking in SEO content blocks

**Files:**
- Modify: `frontend/src/app/market/[id]/page.jsx` (wallet + tag links)
- Modify: `frontend/src/app/wallet/[address]/page.jsx` (market links)
- Modify: `frontend/src/app/page.jsx` (top wallets section)

- [ ] **Step 1: Add tag and wallet links to market page SEO content**

In `frontend/src/app/market/[id]/page.jsx`, in the `.seo-content` block, add a tag link after the market description paragraph (around line 243). This requires extracting tags from alerts:

After the resolution date paragraph (line 243), add:

```jsx
          {(() => {
            const allTags = [...new Set(alerts.flatMap((a) => a.tags || []))].filter(
              (t) => t && t !== "Hide From New"
            );
            return allTags.length > 0 ? (
              <p>
                Categories:{" "}
                {allTags.map((t, i) => (
                  <span key={t}>
                    {i > 0 && ", "}
                    <a href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}>
                      {t}
                    </a>
                  </span>
                ))}
              </p>
            ) : null;
          })()}
```

- [ ] **Step 2: Add market links to wallet page SEO content**

In `frontend/src/app/wallet/[address]/page.jsx`, after the Trading Performance `</section>` (line 208), add a section linking to the wallet's recent markets. The `data` object includes `recent_alerts`:

```jsx
          {data.recent_alerts?.length > 0 && (
            <section>
              <h2>Recent Markets</h2>
              <ul>
                {data.recent_alerts.map((a) => (
                  <li key={a.id}>
                    <a href={`/market/${a.condition_id}`}>
                      {a.market_title || "Unknown Market"}
                    </a>
                    {a.llm_headline && ` — ${a.llm_headline}`}
                  </li>
                ))}
              </ul>
            </section>
          )}
```

Note: We're using `condition_id` directly here since the SEO content is for crawlers and condition_id URLs get redirected to slugs via middleware.

- [ ] **Step 3: Add top wallets section to homepage SEO content**

In `frontend/src/app/page.jsx`, we need to fetch top wallets. Update `getHomeData` to also fetch wallets:

Add to the Promise.all:
```javascript
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
```

And extract it:
```javascript
    const walletsData = walletsRes.ok ? await walletsRes.json() : null;
    // ...
    return {
      markets: marketsData?.markets || [],
      total: marketsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
      theses: thesesData?.theses || thesesData || [],
      topWallets: walletsData?.wallets || [],
    };
```

Then in the SEO content block, after the "Top Smart Money Markets" section (line 168), add:

```jsx
          {topWallets.length > 0 && (
            <section>
              <h2>Top Smart Money Wallets</h2>
              <ol>
                {topWallets.map((w) => (
                  <li key={w.wallet}>
                    <a href={`/wallet/${w.wallet}`}>
                      {w.wallet.slice(0, 6)}...{w.wallet.slice(-4)}
                    </a>{" "}
                    — {w.alert_count} signal{w.alert_count !== 1 ? "s" : ""}
                  </li>
                ))}
              </ol>
            </section>
          )}
```

Update the component to destructure `topWallets`:
```javascript
  const { markets, total, tags, theses, topWallets } = await getHomeData();
```

- [ ] **Step 4: Verify build**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/market/\[id\]/page.jsx frontend/src/app/wallet/\[address\]/page.jsx frontend/src/app/page.jsx
git commit -m "feat(frontend): add internal cross-links in SEO content blocks"
```

---

### Task 8: Frontend — Rich results schema enhancements

**Files:**
- Modify: `frontend/src/app/page.jsx` (SiteNavigationElement, BreadcrumbList)
- Modify: `frontend/src/app/wallet/[address]/page.jsx` (ProfilePage knowsAbout)

- [ ] **Step 1: Add SiteNavigationElement and BreadcrumbList to homepage**

In `frontend/src/app/page.jsx`, add after the existing `faqLd` object (after line 104):

```javascript
  const navLd = {
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    name: "Main Navigation",
    hasPart: [
      { "@type": "WebPage", name: "Markets", url: `${SITE_URL}` },
      ...visibleTags.slice(0, 8).map((t) => {
        const name = typeof t === "string" ? t : t.tag;
        const slug = name.toLowerCase().replace(/\s+/g, "-");
        return { "@type": "WebPage", name, url: `${SITE_URL}/tag/${encodeURIComponent(slug)}` };
      }),
    ],
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "Home",
        item: SITE_URL,
      },
    ],
  };
```

Add the script tags in the JSX (after the existing faqLd script tag):

```jsx
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(navLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />
```

- [ ] **Step 2: Add knowsAbout to wallet ProfilePage schema**

In `frontend/src/app/wallet/[address]/page.jsx`, we need the wallet's market tags. Fetch recent alerts to extract tags. After `getWalletData` call (line 100), the `data` object includes `recent_alerts`. Extract tags from alerts.

Update the `profileLd` object (around line 115). Add to the `mainEntity` Person object:

```javascript
      knowsAbout: [...new Set(
        (data.recent_alerts || [])
          .flatMap((a) => {
            // alerts in recent_alerts don't include tags, so derive from market titles
            return [];
          })
      )],
```

Actually, `recent_alerts` doesn't include tags. A simpler approach: fetch the wallet's alerts with tags. Instead, let's use a lightweight approach — add `knowsAbout` based on the wallet's alert data if available. We need the full alerts. Let's fetch them:

After `getWalletData` (line 100), add:

```javascript
  // Fetch wallet's market tags for structured data
  let walletTags = [];
  try {
    const alertsRes = await fetch(
      `${API_URL}/api/alerts?wallet=${address}&per_page=50`,
      { next: { revalidate: 300 } }
    );
    if (alertsRes.ok) {
      const alertsData = await alertsRes.json();
      walletTags = [...new Set(
        (alertsData.alerts || []).flatMap((a) => a.tags || []).filter((t) => t && t !== "Hide From New")
      )];
    }
  } catch {}
```

Then update the `mainEntity` in `profileLd` to include `knowsAbout`:

```javascript
    mainEntity: {
      "@type": "Person",
      name: pseudonym,
      identifier: address,
      url: `${siteUrl}/wallet/${address}`,
      description: tier
        ? `${tier.name}-tier Polymarket trader`
        : "Polymarket trader",
      sameAs: [`https://polygonscan.com/address/${address}`],
      knowsAbout: walletTags.map((t) => ({
        "@type": "Thing",
        name: t,
      })),
    },
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/page.jsx frontend/src/app/wallet/\[address\]/page.jsx
git commit -m "feat(frontend): add SiteNavigationElement, BreadcrumbList, and ProfilePage knowsAbout schemas"
```

---

### Task 9: Final verification

**Files:** None (testing only)

- [ ] **Step 1: Run backend tests**

Run: `cd /Users/bhavya/git/polybot && source venv/bin/activate && cd backend && pytest -v 2>&1 | tail -20`

Expected: All tests pass

- [ ] **Step 2: Run frontend build**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -20`

Expected: Build succeeds with no errors

- [ ] **Step 3: Run frontend lint**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run lint 2>&1 | tail -10`

Expected: No lint errors

- [ ] **Step 4: Spot-check structured data**

Start the dev server and verify JSON-LD renders correctly on a market page:

Run: `cd /Users/bhavya/git/polybot/frontend && npm run dev &`

Then check a page's HTML for valid JSON-LD:

Run: `curl -s http://localhost:3000 | grep -c 'application/ld+json'`

Expected: 4+ (ItemList, FAQPage, SiteNavigationElement, BreadcrumbList)

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address issues found during final verification"
```
