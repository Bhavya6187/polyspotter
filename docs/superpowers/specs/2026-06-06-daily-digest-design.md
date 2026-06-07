# Daily Digest Generator — Design

**Date:** 2026-06-06
**Status:** Approved (pending spec review)

## Goal

A `claude -p`-driven script that picks the most interesting Polymarket events, writes a daily digest stating which way PolySpotter is leaning on each, and:

1. Outputs a **styled HTML email** the operator opens, copies, and pastes into Gmail to send manually (recipients in BCC).
2. **Publishes the same content to the website** at `/digest/[date]` immediately.

The digest covers **(a)** events resolving today and **(b)** a few top events this week — a mix of most-popular and highest-conviction — each annotated with PolySpotter's lean.

## Non-Goals

- No automated sending / Resend integration (operator sends manually via BCC).
- No personalization — one global digest per day.
- No scoreboard/track-record "receipts" section (picks only).
- No double opt-in, unsubscribe flow, or subscriber-list integration (that is the separate Proof Loop email pipeline).

## Decisions (locked)

| Decision | Choice |
|---|---|
| Website storage/render | New `digests` table + `/digest` and `/digest/[date]` routes |
| Email output | Self-contained, inline-styled `.html` file |
| "Top events this week" scope | Mixed pool: upcoming-resolution **and** recent-activity; Claude picks |
| Receipts/scoreboard | Excluded — picks only |
| Publish timing | Publish to website immediately (status `published`); `DRY_RUN` previews without writing |
| LLM | `claude -p --model opus` for both the PICK and WRITE passes |

## Architecture

### Data flow

```
digestbot.py
  └─ SQL: build candidate pools (resolving-today + this-week mix)
       └─ claude -p (PICK)  → selected event_slugs + section + rationale + leaning
            └─ hydrate full data for picks
                 └─ claude -p (WRITE) → structured JSON (subject, intro, per-event copy)
                      └─ render:
                          • storybot/digests/digest-<date>.html   (email)
                          • UPSERT digests row (content_json source of truth)
                              └─ frontend /digest/[date] renders from content_json
```

Both LLM passes shell out to the Claude CLI: `claude -p "<prompt>" --model opus --dangerously-skip-permissions`, with the candidate/pick JSON piped on **stdin**. No tools are granted (pure text generation); `--dangerously-skip-permissions` mirrors the existing `storybot/run_*.sh` pattern for non-interactive headless runs.

**Why JSON, not raw HTML, from the WRITE pass:** Claude returns structured content; the Python script and the React frontend each render that one source. This keeps the email and the website visually consistent and deterministic, and makes the renderer unit-testable.

### Candidate pools (read from Postgres via `DATABASE_URL`)

**Pool A — Resolving today.** Mirror `_fetch_resolving_soon` in `backend/app.py` but bound to the current UTC day:

```sql
SELECT DISTINCT ON (event_slug)
  event_slug, market_title, market_url, market_image,
  event_end_estimate, end_date,
  composite_score, total_usd, trade_count, llm_copy_action, tags
FROM alerts
WHERE COALESCE(event_end_estimate, end_date) >= date_trunc('day', now() at time zone 'utc')
  AND COALESCE(event_end_estimate, end_date) <  date_trunc('day', now() at time zone 'utc') + interval '1 day'
  -- drop Gamma-settled markets, same predicate _fetch_resolving_soon uses
ORDER BY event_slug, composite_score DESC;
```

> Implementation note: copy the exact "settled" predicate and column list from `_fetch_resolving_soon` (`backend/app.py:1365`) so the today-bound query stays consistent with the live endpoint. The `> NOW()` bound there becomes the same-day window above.

**Pool B — This-week mix.** Union of two sub-queries, deduped by `event_slug`, capped at ~25 candidates (token control):

- *Upcoming:* `COALESCE(event_end_estimate, end_date)` within `(now, now + interval '7 days']`, `DISTINCT ON (event_slug)` by highest `composite_score`.
- *Hot recently:* `created_at >= now() - interval '7 days'`, aggregated by `event_slug` → `SUM(total_usd)`, `COUNT(*)`, `MAX(composite_score)`, plus the top alert's `llm_copy_action`.

Each candidate (both pools) is serialized for the PICK pass with:
`event_slug, title, resolution_time, total_usd, trade_count, composite_score, leaning {outcome, entry_price} (from llm_copy_action), top_strategies, market_url`.

### Leaning & conviction semantics (existing fields)

- **Leaning (which side)** = `alerts.llm_copy_action.outcome` (+ `entry_price`). May be `null` (no defensible single buy) → render as "no clear lean / watching".
- **Conviction (strength)** = `alerts.composite_score`; strength badge `min(4, composite_score // 25 + 1)` (same formula as `/api/top3`, `app.py:1600`).
- **Popularity** = `SUM(total_usd)` / `trade_count`.

### LLM passes

**PICK** — input: candidate JSON (both pools, tagged by pool). Prompt instructs Claude to return JSON:

```json
{
  "resolving_today": [{"event_slug": "...", "reason": "...", "leaning": "..."}],
  "top_this_week":  [{"event_slug": "...", "reason": "...", "leaning": "..."}]
}
```

Select **all** qualifying resolving-today events (cap ~6) and the top **3–5** this-week events explicitly balancing popularity against conviction.

**WRITE** — input: hydrated full data for the picked slugs. Prompt instructs Claude to return JSON:

```json
{
  "subject": "PolySpotter Daily — <date>: <hook>",
  "intro": "1–2 sentence opener",
  "sections": [
    {
      "key": "resolving_today",
      "title": "Resolving Today",
      "items": [
        {"event_slug":"...","headline":"...","leaning":"YES @ 0.62 ▲","blurb":"...","url":"https://polyspotter.com/event/..."}
      ]
    },
    {"key": "top_this_week", "title": "Top This Week", "items": [ ... ]}
  ]
}
```

`leaning` is a short human string derived from `llm_copy_action` (outcome, entry price, direction arrow). `url` points at the PolySpotter event page (built from `event_slug`).

### Rendering

- **Email** → `storybot/digests/digest-<date>.html`: a self-contained document with **inline** styles (email clients strip `<style>`/external CSS). Header (PolySpotter Daily + date), intro, two sections, each item a card with headline, leaning chip, blurb, and a "View market" link. Footer with link to the web version (`/digest/<date>`).
- **Website** → React renders from `content_json` using the site theme (CSS vars: `--accent`, `--surface-card`, `--bullish`, `--bearish`, …), reusing component patterns from the existing `/articles` pages.

### Persistence: `digests` table

Migration added in `backend/database.py` (mirrors `_migrate_add_*`), and DDL appended to `backend/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS digests (
    id            SERIAL PRIMARY KEY,
    digest_date   DATE NOT NULL UNIQUE,
    run_id        TEXT,
    subject       TEXT NOT NULL,
    intro         TEXT,
    content_json  JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'published',  -- 'draft' | 'published'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(digest_date DESC);
```

Re-running the same day **upserts** (`ON CONFLICT (digest_date) DO UPDATE`) so a re-run refreshes the day's digest in place.

### Backend API (`backend/app.py`)

- `GET /api/digests` — published digests, newest-first: `[{digest_date, subject}]`.
- `GET /api/digest/{date}` — one digest: `{digest_date, subject, intro, content_json}` (404 if missing/unpublished).

Pydantic models added to `backend/models.py`.

### Frontend (`frontend/`)

- `frontend/src/lib/api.js` — `fetchDigests()`, `fetchDigest(date)`.
- `frontend/src/app/digest/page.jsx` — index list linking to `/digest/<date>`.
- `frontend/src/app/digest/[date]/page.jsx` — renders subject, intro, and sections/items from `content_json`; `not-found.jsx` for unknown dates.
- Optionally surface a link to `/digest` from the homepage/nav (low priority; can defer).

## Error handling

- **Nothing resolving today** → omit the Resolving-Today section (digest still ships with This-Week).
- **Empty candidate set entirely** → no-op with a log line; no file, no DB write (matches articlebot's no-op convention).
- **`claude -p` non-zero exit or non-JSON output** → retry once; on second failure abort with a clear error and write nothing (no half-built digest).
- **`DRY_RUN=true`** → write the HTML to `storybot/dry_runs/`, print the structured content, skip the DB upsert.
- **Idempotency** → `digest_date UNIQUE` upsert.

## Testing

- **Python (`storybot/test_digestbot.py`, pytest):**
  - Pool SQL builders return expected shape (monkeypatched DB cursor).
  - `claude -p` wrapper: monkeypatch `subprocess.run`; assert correct argv (`--model opus`, `--dangerously-skip-permissions`), stdin payload, and JSON parsing incl. the retry-on-bad-JSON path.
  - Email renderer: given a `content_json` fixture, output HTML contains each item's headline, leaning, and URL, and has no external `<link>`/`<style>` stylesheet (inline only).
  - `DRY_RUN` writes to `dry_runs/` and performs no DB write.
- **Backend (`backend/test_*.py`):** `/api/digests` and `/api/digest/{date}` via FastAPI TestClient with a monkeypatched DB read (mirrors `test_subscribe.py`).
- **Frontend:** `npm run build` (no test harness; lint is pre-existing-broken).

## File summary

**Create**
- `storybot/digestbot.py`
- `storybot/test_digestbot.py`
- `frontend/src/app/digest/page.jsx`
- `frontend/src/app/digest/[date]/page.jsx`
- `frontend/src/app/digest/[date]/not-found.jsx`

**Modify**
- `backend/schema.sql` — `digests` DDL
- `backend/database.py` — `_migrate_add_digests` + call in `init_db()`
- `backend/models.py` — digest response models
- `backend/app.py` — `GET /api/digests`, `GET /api/digest/{date}`
- `frontend/src/lib/api.js` — `fetchDigests`, `fetchDigest`

## Operator workflow

```bash
source venv/bin/activate
DRY_RUN=true python storybot/digestbot.py     # preview HTML in storybot/dry_runs/
python storybot/digestbot.py                  # writes storybot/digests/digest-<date>.html + publishes to /digest/<date>
# open storybot/digests/digest-<date>.html, copy, paste into Gmail, BCC recipients, send
```
