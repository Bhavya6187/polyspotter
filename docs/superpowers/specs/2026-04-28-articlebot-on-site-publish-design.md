# Articlebot: publish on polyspotter.com + tweet teaser

**Date:** 2026-04-28
**Status:** Design
**Owner:** bhavya

## Problem

Today, `storybot/articlebot.py` writes a daily ~600-word article and a cover
chart, drops them as a draft into the `articles` Postgres table + a `.md`
file on disk, and waits for a human to paste the article into the X article
composer. After the human posts, `mark_published.py` records the X URL.

This loses three things:

1. **No SEO.** The article only ever lives on x.com (an article composer
   page). polyspotter.com sees no inbound traffic from the article.
2. **No editorial control of cover.** The X article composer doesn't render
   our cover chart well; we hand it off and hope.
3. **Manual paste step.** Easy to skip on busy days; defeats the
   "set-and-forget cron" property the bot was supposed to give us.

We want the article to be a first-class page on polyspotter.com (SEO-indexed,
linkable, sharable), with a teaser tweet driving readers TO that page.

## Goals

- The daily article is published as a real page on polyspotter.com, indexed
  by search engines, with proper SEO metadata.
- A teaser tweet auto-posts at publish time, with the cover chart as media,
  linking to the article page.
- A human still gates the publish step (one CLI invocation), so a bad
  article never auto-leaks to the public web.
- Minimal new infrastructure — no S3, no new services.

## Non-goals

- Article listing/index page (`/articles`). Not in scope; can be added later.
- Multi-author bylines, comments, reactions. Not in scope.
- WYSIWYG admin UI for editing drafts. Reviewer uses `psql` or the on-disk
  `.md` artifact for now.
- Reposting the same event with a meaningfully-new angle. The picker
  already has logic for this; the URL design supports it via the date
  prefix; no extra plumbing here.

## High-level approach

Targeted, minimal-surface change (Approach 1 of three considered):

- Keep `articlebot.py`'s pipeline shape. It still picks an event, researches,
  writes the article, picks a cover chart, validates, and persists a draft.
- Add a tweet teaser to the same LLM run, written to a new `tweet_text`
  column.
- Move the cover image into the DB (`cover_bytes BYTEA`). The backend
  serves it from there.
- Add a Next.js `/article/[date]/[slug]` page on the frontend with full
  SEO metadata + JSON-LD.
- Add a `publish_article.py <run_id>` CLI that flips the draft to
  `published` AND posts the teaser tweet (with the cover image) via the
  existing `tweet_utils` helpers.
- Delete `mark_published.py` — replaced.

## URL design

Articles live at `https://polyspotter.com/article/<YYYY-MM-DD>/<event-slug>`.

- The date is the publish date, stored in the new `published_date` column.
- `<event-slug>` is the existing `event_slug` from the alerts row that drove
  the article.
- Uniqueness key: `(published_date, event_slug)` for `status='published'`.
  If the same event is covered on two different days (a rare "materially
  new" recovery), the URLs differ by date.

The date in the URL signals freshness to readers and crawlers and matches
the daily cadence the bot runs on.

## Data model

Schema migration in `backend/database.py::_migrate_add_articles` (idempotent;
called from existing migration runner):

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS cover_bytes BYTEA;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_text TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_id TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_date DATE;
CREATE INDEX IF NOT EXISTS idx_articles_published_lookup
    ON articles (published_date, event_slug)
    WHERE status = 'published';
```

Column semantics:

| Column | When set | Purpose |
|---|---|---|
| `cover_bytes` | At draft insert (articlebot.py) | PNG bytes of the cover chart. Streamed by the backend. |
| `tweet_text` | At draft insert | Teaser tweet body, ≤255 chars, no inline URL. (280 − 23 URL − 2 separator = 255.) |
| `tweet_id` | At publish (publish_article.py) | X tweet ID returned by the API. |
| `published_date` | At publish | Date the draft was promoted. Drives the article URL. |
| `posted_url` (existing, repurposed) | At publish | The X tweet URL (`https://x.com/.../status/<tweet_id>`). |
| `posted_at` (existing) | At publish | Unchanged semantics. |
| `cover_path`, `md_path` (existing) | At draft insert | Legacy debug artifacts. Stay populated; not load-bearing. |

Existing draft rows in the table that predate this change (no `tweet_text`,
no `cover_bytes`) cannot be promoted via the new `publish_article.py` —
the script refuses with a clear error message and instructs to re-run
`articlebot.py`.

## Backend (`backend/app.py`)

Three new endpoints on the FastAPI app:

### `GET /articles/by-slug/{date}/{event_slug}`

Primary lookup hit by the frontend.

- `date` is `YYYY-MM-DD`, parsed to a `date`.
- 404 unless a row matches `(published_date=date, event_slug=event_slug,
  status='published')`.
- Response shape:
  ```json
  {
    "run_id": "...",
    "event_slug": "...",
    "published_date": "YYYY-MM-DD",
    "headline": "...",
    "subhead": "...",
    "body_markdown": "...",
    "cover_alt_text": "...",
    "alert_ids": [<int>...],
    "posted_url": "https://x.com/.../status/...",
    "has_cover": true | false
  }
  ```
- `has_cover` is `true` iff `cover_bytes IS NOT NULL`. The frontend builds
  the cover URL itself as `${API_BASE}/articles/${run_id}/cover.png` —
  keeps the backend agnostic of its public hostname.

### `GET /articles/{run_id}/cover.png`

- 404 if `cover_bytes` is null OR `status != 'published'`.
- Response: `Content-Type: image/png`, body = the bytes,
  `Cache-Control: public, max-age=31536000, immutable` (the bytes for a
  given run_id never change).

### `GET /articles`

- Returns `[{"run_id", "event_slug", "published_date", "headline"}, ...]`
  for all `status='published'` rows, ordered `published_date DESC`.
- Used by the frontend `sitemap.js`.
- No pagination; volume is ~1/day. Revisit when 100+.

### Internal/debug

`GET /articles/{run_id}` (full row, drafts included) is **not** exposed —
all admin reads happen via `psql`. Keeps the public API surface small.

## Frontend

### Page: `frontend/src/app/article/[date]/[slug]/page.jsx`

Server Component.

- Calls `getArticleBySlug(date, slug)` from `lib/api.js`. On 404, calls
  `notFound()`.
- Layout: `<header>` with headline + subhead; cover image (if present);
  body rendered via `react-markdown` + `remark-gfm` inside a Tailwind
  prose container.
- Footer: small "originally posted on X" link via `posted_url` if set,
  otherwise nothing.
- Custom `<a>` renderer for the markdown body: when `href` starts with `/`
  or with `https://polyspotter.com`, render with Next's `<Link>` so internal
  navigation is client-side. External `<a>` get `rel="noopener nofollow"`.

### Metadata: `generateMetadata`

Exports a metadata object with:

- `title`: `<headline> · PolySpotter`
- `description`: `<subhead>`
- `alternates.canonical`: `https://polyspotter.com/article/<date>/<slug>`
- `openGraph`:
  - `type: "article"`
  - `title`, `description`
  - `publishedTime: <published_date as ISO string>`
  - `url`
  - `images: [{ url: cover_url, width, height, alt: cover_alt_text }]` —
    omit when no cover.
- `twitter`:
  - `card: "summary_large_image"`
  - `title`, `description`
  - `images: [cover_url]` — omit when no cover.

### JSON-LD

Inline `<script type="application/ld+json">` in the page body with:

```json
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "...",
  "datePublished": "<published_date ISO>",
  "image": "<cover_url>" or omitted,
  "author": { "@type": "Organization", "name": "PolySpotter" },
  "publisher": {
    "@type": "Organization",
    "name": "PolySpotter",
    "logo": { "@type": "ImageObject", "url": "https://polyspotter.com/logo.png" }
  }
}
```

### `not-found.jsx`

Friendly 404 with link back to `/`.

### Markdown rendering deps

`frontend/package.json` adds:

```
"react-markdown": "^9",
"remark-gfm": "^4"
```

### `lib/api.js`

```js
export async function getArticleBySlug(date, slug) {
  const r = await fetch(`${BASE}/articles/by-slug/${date}/${slug}`, {
    next: { revalidate: 60 },
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getArticleBySlug failed: ${r.status}`);
  return r.json();
}

export async function getArticles() {
  const r = await fetch(`${BASE}/articles`, { next: { revalidate: 300 } });
  if (!r.ok) throw new Error(`getArticles failed: ${r.status}`);
  return r.json();
}
```

### Sitemap

`frontend/src/app/sitemap.js` adds article entries:

```js
const articles = await getArticles();
const articleEntries = articles.map(a => ({
  url: `https://polyspotter.com/article/${a.published_date}/${a.event_slug}`,
  lastModified: a.published_date,
  changeFrequency: "weekly",
  priority: 0.8,
}));
```

## `articlebot.py` changes

### SYSTEM_PROMPT

Reframe and extend:

- Replace any "X article composer" framing with "an SEO-indexed article
  page on polyspotter.com".
- Article body shape unchanged (headline ≤90, subhead ≤160, 450-800 word
  body, 3-4 H2s, mandatory inline polyspotter.com link, banned phrases,
  cover chart selection).
- New required field: `tweet_text` — a teaser, NOT a summary.
  - ≤255 chars.
  - Must NOT contain a URL — the article URL gets appended at publish time
    by `publish_article.py`. Two URLs in a tweet would look spammy.
  - Reuses the `twitter_simple.py` style guide: lead with the most
    surprising fact, no jargon, no hashtags, no @mentions, ≤1 emoji,
    same banned-phrase list (`_BANNED_TWEET_PHRASES`).
  - The teaser should make a reader want to click through to the article.

### Output JSON schema

```json
{
  "decision": "post" | "skip",
  "reason": "...",
  "article": {
    "headline": "...",
    "subhead": "...",
    "body_markdown": "...",
    "cover_alt_text": "..."
  },
  "tweet_text": "...",
  "alert_ids": [<int>...],
  "cover_chart_spec": {
    "chart_type": "...",
    "alert_id": <int>,
    "params": {}
  }
}
```

When `decision == "skip"`: `article`, `tweet_text`, `cover_chart_spec`,
`alert_ids` are all null.

### `validate_article_decision` additions

Inside the `decision == "post"` branch:

- `tweet_text` is a non-empty string.
- `_tweet_length(tweet_text + "\n\nhttps://x")` ≤ `TWEET_MAX_CHARS`
  (any URL works — `_tweet_length` counts every URL as `TWEET_URL_CHARS`
  regardless of source length).
- `tweet_text` does not contain any phrase in `_BANNED_TWEET_PHRASES`.
- `tweet_text` does not match `_POLYSPOTTER_URL_RE` — model isn't allowed
  to inline its own URL.

### Cover chart flow

`render_cover_chart` is refactored:

- Renders to PNG bytes.
- Writes those bytes to `<run_id>.png` in `articles/` (or `dry_runs/`
  on `DRY_RUN`) for human review — unchanged debug artifact.
- Returns `(png_bytes, written_path)`.

`main` passes `png_bytes` into `articlebot_storage.persist_article` for
the `cover_bytes` column.

### `articlebot_storage.persist_article` signature

```python
def persist_article(*, run_id: str, decision: dict,
                    cover_bytes: bytes | None,
                    cover_path: str | None) -> dict
```

INSERT now includes `cover_bytes` (passed in) and `tweet_text` (from
`decision["tweet_text"]`). `published_date` stays NULL on draft insert.
The `.md` file write is unchanged.

### Final stdout

```
[articlebot] draft run_id=<id> md=<path> words=<n>
[articlebot] review the markdown, then: python storybot/publish_article.py <run_id>
```

## `publish_article.py` (new)

Lives at `storybot/publish_article.py`.

### Usage

```
python storybot/publish_article.py <run_id>
DRY_RUN=true python storybot/publish_article.py <run_id>
```

### Flow

1. Load row from `articles WHERE run_id = %s`. Refuse (exit 1, clear
   error) if `status != 'draft'`. Refuse if `tweet_text IS NULL` —
   pre-migration drafts.
2. Compute:
   - `published_date = today (UTC)`
   - `article_url = f"https://polyspotter.com/article/{published_date.isoformat()}/{event_slug}"`
3. Build the final tweet body:
   - `f"{tweet_text}\n\n{article_url}"`
   - Defensively re-run `_tweet_length` + banned-phrase + `_POLYSPOTTER_URL_RE`
     check (catches manual edits to the DB row that broke invariants).
   - If invariants fail, exit 1 with a clear error pointing at the row.
4. Twitter clients via `tweet_utils._build_twitter_client()` and
   `_build_twitter_api_v1()`. Cover bytes from `cover_bytes`.
5. `tweet_utils.post_tweet(tweet, twitter_client=..., twitter_api_v1=...,
   media_png=cover_bytes, dry_run=DRY_RUN)`.
6. On `DRY_RUN`: print the tweet, print the article URL, print
   `cover_bytes` size; prompt `Post this for real? [y/N]`. If `y`,
   re-call `post_tweet` with `dry_run=False`. If `n` or empty, exit 0
   without DB changes.
7. On successful (real) post:
   - Single transaction:
     ```sql
     UPDATE articles
     SET status='published',
         published_date=%s,
         tweet_id=%s,
         posted_url=%s,
         posted_at=NOW()
     WHERE run_id=%s AND status='draft'
     ```
   - Verify `rowcount == 1` (concurrent publish guard); raise on
     mismatch.
8. Print:
   ```
   [publish_article] published run_id=<id>
       article: https://polyspotter.com/article/<date>/<slug>
       tweet:   https://x.com/.../status/<tweet_id>
   ```

### What it does NOT do

- Does NOT call `record_tweet()` — that helper writes to `tweeted_alerts`,
  the per-alert dedup table for `twitter_simple.py`. Article tweets are a
  separate stream and don't share dedup state.
- Does NOT regenerate the tweet text. If the human wants different wording,
  they edit the row in `psql` before running this script, OR re-run
  `articlebot.py` to regenerate.

## Cutover

### Files deleted

- `storybot/mark_published.py` — fully replaced by `publish_article.py`.

### `CLAUDE.md` updates

Replace the articlebot block:

```bash
python storybot/articlebot.py
DRY_RUN=true python storybot/articlebot.py

# After reviewing the draft (storybot/articles/<run_id>.md):
python storybot/publish_article.py <run_id>
DRY_RUN=true python storybot/publish_article.py <run_id>
```

Drop the `mark_published.py` line.

### Deployment ordering

Mid-rollout the system never serves a 404 because publish lags everything:

1. Backend deploys schema migration + the three new endpoints. Existing
   draft rows have null `tweet_text` / `cover_bytes`; harmless.
2. Frontend deploys `/article/[date]/[slug]` page + sitemap addition.
   No published rows yet → page route returns 404 if hit, sitemap is empty.
   Both fine.
3. Articlebot deploys the new prompt + storage + `publish_article.py`.
4. First cron run produces a draft. Reviewer runs `publish_article.py`.
   Article goes live, tweet posts.

## Testing

### Scanner side

- `storybot/test/test_articlebot.py` extends `validate_article_decision`:
  - tweet_text missing
  - tweet_text empty string
  - tweet_text exceeds length budget
  - tweet_text contains a banned phrase
  - tweet_text contains a `polyspotter.com` URL
- `storybot/test/test_publish_article.py` (new):
  - monkeypatch `tweet_utils.post_tweet` and the `_get_conn` to a stub.
  - Asserts: refuses `status='published'` row; refuses null
    `tweet_text`; computes correct URL; passes `cover_bytes` to
    `post_tweet`; UPDATE sets all five fields; idempotent (running twice
    on the same run_id refuses on the second call).
  - Skip case: `cover_bytes` is null → `post_tweet` called with
    `media_png=None` (still posts, no error).

### Backend side

- `backend/test_endpoints.py` adds:
  - `GET /articles/by-slug/<date>/<slug>` 200 for published row, 404
    for non-existent and for draft.
  - `GET /articles/<run_id>/cover.png` 200 with correct content-type and
    body length, 404 for null bytes / draft row.
  - `GET /articles` returns expected shape, ordered by published_date DESC.

### Frontend

- `npm run lint` continues to gate.
- No new tests; manual verification via `npm run dev` against a Postgres
  with one published row.

## Open questions

None at this point — all the major decisions (URL shape, cover hosting,
publish flow, tweet generation timing) are resolved above.

## Risks

1. **PostgreSQL row size with `cover_bytes`.** Charts run ~50-200 KB. At
   1 article/day the table will be ~5 MB/year — well within Postgres
   comfort. If charts ever balloon, swap to S3 in a future iteration; the
   `cover_url` field on the API response already abstracts the storage.
2. **Tweet validation drift.** `articlebot.py` validates `tweet_text` at
   write time, but `publish_article.py` re-validates the final
   `tweet_text + url` because human edits can land between draft and
   publish. If the reviewer pastes a too-long replacement into psql, the
   publish script catches it before posting.
3. **Cron host vs backend host** — `articlebot.py` writes `cover_bytes`
   directly to Postgres, and the backend reads from the same DB. The two
   hosts only need DB access, no shared filesystem. This is the same
   coupling that already exists today, so no new operational concern.
