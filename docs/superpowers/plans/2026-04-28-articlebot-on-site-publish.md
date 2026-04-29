# Articlebot On-Site Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace articlebot's "X composer paste" workflow with on-site publishing at `/article/<date>/<slug>` on polyspotter.com plus an auto-posted teaser tweet linking back to the article.

**Architecture:** Targeted, minimal-surface change. Add four columns to the existing `articles` table (`cover_bytes`, `tweet_text`, `tweet_id`, `published_date`). Add three FastAPI endpoints (`/api/articles/by-slug/...`, cover.png streamer, list). Add a Next.js article page with full SEO metadata + JSON-LD. Articlebot now also writes a teaser tweet at draft time. A new `publish_article.py <run_id>` CLI flips draft → published AND auto-posts the tweet via the existing `tweet_utils` helpers. Delete `mark_published.py`.

**Tech Stack:** Python 3.13 / FastAPI / psycopg2 / Pydantic on the backend; tweepy + OpenAI client in `storybot/`; Next.js 15 / React 19 / Tailwind 4 / `react-markdown` + `remark-gfm` on the frontend; Postgres (column add via `ALTER TABLE ADD COLUMN IF NOT EXISTS`).

**Spec:** [docs/superpowers/specs/2026-04-28-articlebot-on-site-publish-design.md](../specs/2026-04-28-articlebot-on-site-publish-design.md)

---

## File Structure

**Files created:**
- `storybot/publish_article.py` — new CLI, replaces `mark_published.py`
- `test/test_publish_article.py` — tests for the CLI
- `frontend/src/app/article/[date]/[slug]/page.jsx` — article page (Server Component)
- `frontend/src/app/article/[date]/[slug]/not-found.jsx` — friendly 404

**Files modified:**
- `backend/database.py` — extend `_migrate_add_articles` with 4 ALTERs + 1 partial index, and update the canonical `CREATE TABLE` to include the new columns
- `backend/models.py` — add `ArticleOut`, `ArticleListItem`
- `backend/app.py` — add 3 endpoints (by-slug, cover.png, list); endpoints use the existing `with db() as conn:` context manager
- `backend/test_endpoints.py` — add tests for the 3 endpoints (use the existing `with db() as conn:` pattern)
- `storybot/articlebot.py` — extend SYSTEM_PROMPT with tweet_text instructions; extend validator; refactor `render_cover_chart` to return PNG bytes; update `main()` flow
- `storybot/articlebot_storage.py` — `persist_article()` accepts `cover_bytes` and `tweet_text`
- `test/test_articlebot_validation.py` — extend with tweet_text cases
- `test/test_articlebot_storage.py` — update migration assertion (8 statements now), update persist_article test
- `test/test_articlebot_e2e.py` — add `tweet_text` field to mocked LLM JSON
- `frontend/package.json` — add `react-markdown` + `remark-gfm`
- `frontend/src/app/sitemap.js` — add a `getArticleEntries()` section parallel to `getMarketEntries()` / `getTagEntries()`
- `CLAUDE.md` — replace articlebot block

**Frontend conventions to match:**
- Server Component pages do inline `fetch(\`${API_URL}/api/...\`)` with try/catch returning null on failure (see `app/market/[id]/page.jsx`, `app/alert/[id]/page.jsx`). They do NOT use `lib/api.js`. The new article page follows this same inline-fetch pattern.
- The frontend has no `@/`-style path alias; relative imports only.
- `lib/api.js` is used by client hooks/components (e.g. `useLiveMarket`, `Ticker`). We do not extend it for the article page or sitemap — both are Server Components and will inline their fetches.

**Files deleted:**
- `storybot/mark_published.py`

---

## Task 1: Schema migration — extend `_migrate_add_articles`

**Files:**
- Modify: `backend/database.py:155-184`
- Modify: `test/test_articlebot_storage.py` (the migration test at top of file)

- [ ] **Step 1: Update the migration test to expect new statements**

Open `test/test_articlebot_storage.py` and replace the existing `test_migrate_add_articles_executes_create_table_and_indexes` with:

```python
def test_migrate_add_articles_executes_full_migration():
    """Migration runs: CREATE TABLE + 2 base indexes + 4 ALTER ADD COLUMN
    + 1 partial index, all idempotent."""
    import database

    cur = MagicMock()
    database._migrate_add_articles(cur)

    sqls = [call.args[0] for call in cur.execute.call_args_list]
    assert len(sqls) == 8, f"expected 8 statements, got {len(sqls)}"
    assert "CREATE TABLE IF NOT EXISTS articles" in sqls[0]
    assert "cover_bytes     BYTEA" in sqls[0]
    assert "tweet_text      TEXT" in sqls[0]
    assert "tweet_id        TEXT" in sqls[0]
    assert "published_date  DATE" in sqls[0]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_event_slug" in sqls[1]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_status" in sqls[2]
    assert "ADD COLUMN IF NOT EXISTS cover_bytes BYTEA" in sqls[3]
    assert "ADD COLUMN IF NOT EXISTS tweet_text TEXT" in sqls[4]
    assert "ADD COLUMN IF NOT EXISTS tweet_id TEXT" in sqls[5]
    assert "ADD COLUMN IF NOT EXISTS published_date DATE" in sqls[6]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_published_lookup" in sqls[7]
    assert "WHERE status = 'published'" in sqls[7]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/test_articlebot_storage.py::test_migrate_add_articles_executes_full_migration -v
```

Expected: FAIL — old migration only emits 3 statements.

- [ ] **Step 3: Update `backend/database.py::_migrate_add_articles`**

Replace the existing function (lines 155-184) with:

```python
def _migrate_add_articles(cur):
    """Create the articles table for articlebot drafts (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id              SERIAL PRIMARY KEY,
            run_id          TEXT NOT NULL UNIQUE,
            event_slug      TEXT NOT NULL,
            alert_ids       INTEGER[] NOT NULL,
            headline        TEXT NOT NULL,
            subhead         TEXT NOT NULL,
            body_markdown   TEXT NOT NULL,
            cover_alt_text  TEXT,
            cover_path      TEXT,
            md_path         TEXT NOT NULL,
            word_count      INTEGER NOT NULL,
            status          TEXT NOT NULL DEFAULT 'draft',
            posted_url      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            posted_at       TIMESTAMPTZ,
            cover_bytes     BYTEA,
            tweet_text      TEXT,
            tweet_id        TEXT,
            published_date  DATE
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_event_slug
            ON articles (event_slug, created_at DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_status
            ON articles (status, created_at DESC)
    """)
    # Backward-compat ALTERs for tables created before these columns existed
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS cover_bytes BYTEA")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_text TEXT")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_id TEXT")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_date DATE")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_published_lookup
            ON articles (published_date, event_slug)
            WHERE status = 'published'
    """)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest test/test_articlebot_storage.py::test_migrate_add_articles_executes_full_migration -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py test/test_articlebot_storage.py
git commit -m "$(cat <<'EOF'
articlebot: extend articles schema for on-site publish

Add cover_bytes, tweet_text, tweet_id, published_date columns plus a
partial index on (published_date, event_slug) WHERE status='published'
for the by-slug frontend lookup. Idempotent ALTER TABLE ADD COLUMN IF
NOT EXISTS handles upgrade from existing tables.
EOF
)"
```

---

## Task 2: Backend Pydantic models

**Files:**
- Modify: `backend/models.py` (append at end)

- [ ] **Step 1: Add models to `backend/models.py`**

Append at the end of the file:

```python
# -- Articles ----------------------------------------------------------------

class ArticleOut(BaseModel):
    """Full article payload returned to the frontend article page."""
    run_id: str
    event_slug: str
    published_date: str        # ISO YYYY-MM-DD
    headline: str
    subhead: str
    body_markdown: str
    cover_alt_text: str | None = None
    alert_ids: list[int]
    posted_url: str | None = None
    has_cover: bool


class ArticleListItem(BaseModel):
    """Single entry in GET /api/articles, used by the sitemap."""
    run_id: str
    event_slug: str
    published_date: str
    headline: str
```

- [ ] **Step 2: Verify the file imports cleanly**

```bash
cd /home/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "import models; print(models.ArticleOut.model_json_schema()['required'])"
```

Expected: prints a list including `'run_id'`, `'event_slug'`, `'has_cover'` etc.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "articlebot: add ArticleOut + ArticleListItem pydantic models"
```

---

## Task 3: Backend endpoint — `GET /api/articles/by-slug/{date}/{event_slug}`

**Files:**
- Modify: `backend/app.py` (add to imports + new handler)
- Modify: `backend/test_endpoints.py` (new test)

- [ ] **Step 1: Write the failing test**

Append to `backend/test_endpoints.py`:

```python
@skip_no_db
def test_articles_by_slug_returns_published_row():
    """A published row is returned by (date, slug); drafts and missing rows 404."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO articles
                (run_id, event_slug, alert_ids, headline, subhead,
                 body_markdown, cover_alt_text, md_path, word_count,
                 status, published_date, posted_url, tweet_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            ("TEST_byslug_run", "test-event-slug", [1, 2],
             "Test Headline", "Test Subhead", "body **md**", "cover alt",
             "test.md", 600, "published", "2026-04-28",
             "https://x.com/PolySpotter/status/1", "tweet teaser"),
        )

    try:
        r = client.get("/api/articles/by-slug/2026-04-28/test-event-slug")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "TEST_byslug_run"
        assert body["headline"] == "Test Headline"
        assert body["body_markdown"] == "body **md**"
        assert body["alert_ids"] == [1, 2]
        assert body["published_date"] == "2026-04-28"
        assert body["has_cover"] is False  # no cover_bytes set

        # 404 for unknown slug
        r = client.get("/api/articles/by-slug/2026-04-28/no-such-slug")
        assert r.status_code == 404

        # 404 for draft (re-INSERT same event_slug as a draft on a different date)
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO articles
                    (run_id, event_slug, alert_ids, headline, subhead,
                     body_markdown, md_path, word_count, status, tweet_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ("TEST_byslug_draft", "test-event-slug", [3],
                 "Draft", "Draft sub", "body", "test.md", 600,
                 "draft", "tweet"),
            )
        r = client.get("/api/articles/by-slug/2026-04-29/test-event-slug")
        assert r.status_code == 404
    finally:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM articles WHERE run_id LIKE 'TEST_byslug_%%'")
```

NOTE: `db` is already imported at the top of `test_endpoints.py` via `from app import app, db`. The `with db() as conn:` pattern auto-commits on success and rolls back on exception (see app.py:75-87).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/bhavya/git/polybot/backend && source ../venv/bin/activate
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_by_slug_returns_published_row -v
```

Expected: FAIL with 404 on the first GET (endpoint doesn't exist).

- [ ] **Step 3: Add endpoint to `backend/app.py`**

In the imports block at the top (around line 36), add `ArticleOut` and `ArticleListItem` to the existing `from models import (...)`:

```python
from models import (
    # ... existing imports ...
    ArticleOut,
    ArticleListItem,
)
```

Then append a new handler near the other GET endpoints (e.g. after the live-market endpoint):

```python
@app.get("/api/articles/by-slug/{date}/{event_slug}", response_model=ArticleOut)
def get_article_by_slug(date: str, event_slug: str):
    """Look up a published article by (published_date, event_slug)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, event_slug, published_date, headline, subhead,
                   body_markdown, cover_alt_text, alert_ids, posted_url,
                   (cover_bytes IS NOT NULL) AS has_cover
            FROM articles
            WHERE published_date = %s::date
              AND event_slug = %s
              AND status = 'published'
            LIMIT 1
            """,
            (date, event_slug),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="article not found")
    return ArticleOut(
        run_id=row[0],
        event_slug=row[1],
        published_date=row[2].isoformat(),
        headline=row[3],
        subhead=row[4],
        body_markdown=row[5],
        cover_alt_text=row[6],
        alert_ids=list(row[7] or []),
        posted_url=row[8],
        has_cover=bool(row[9]),
    )
```

NOTE: `db` is the existing context manager in `app.py:75-87` — it grabs a connection, yields it, commits on success, rolls back on exception. All other handlers in this file use the same pattern.

- [ ] **Step 4: Run test to verify it passes**

```bash
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_by_slug_returns_published_row -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "articlebot: GET /api/articles/by-slug/{date}/{slug} endpoint"
```

---

## Task 4: Backend endpoint — `GET /api/articles/{run_id}/cover.png`

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/test_endpoints.py`:

```python
@skip_no_db
def test_articles_cover_png_streams_bytes():
    """Cover endpoint streams the BYTEA contents with image/png; 404 if null
    or if status != 'published'."""
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO articles
                (run_id, event_slug, alert_ids, headline, subhead,
                 body_markdown, md_path, word_count, status,
                 published_date, cover_bytes, tweet_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            ("TEST_cover_run", "cov", [1], "h", "s", "b", "x.md", 600,
             "published", "2026-04-28", psycopg2.Binary(fake_png), "tweet"),
        )

    try:
        r = client.get("/api/articles/TEST_cover_run/cover.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == fake_png

        # 404 for unknown run_id
        assert client.get("/api/articles/no-such-run/cover.png").status_code == 404

        # 404 for null cover_bytes
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO articles
                    (run_id, event_slug, alert_ids, headline, subhead,
                     body_markdown, md_path, word_count, status, tweet_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ("TEST_cover_nobytes", "cov2", [1], "h", "s", "b", "x.md",
                 600, "published", "tweet"),
            )
        assert client.get("/api/articles/TEST_cover_nobytes/cover.png").status_code == 404
    finally:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM articles WHERE run_id LIKE 'TEST_cover_%%'")
```

Add `import psycopg2` to the test file's imports if not already present.

- [ ] **Step 2: Run test to verify it fails**

```bash
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_cover_png_streams_bytes -v
```

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Add the endpoint to `backend/app.py`**

Add `from fastapi.responses import Response` to the imports if not already there.

Then add this handler near the by-slug handler:

```python
@app.get("/api/articles/{run_id}/cover.png")
def get_article_cover(run_id: str):
    """Stream the cover_bytes for a published article."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT cover_bytes
            FROM articles
            WHERE run_id = %s AND status = 'published'
            LIMIT 1
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        raise HTTPException(status_code=404, detail="cover not found")
    png_bytes = bytes(row[0])  # psycopg2 BYTEA → memoryview, normalize to bytes
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_cover_png_streams_bytes -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "articlebot: GET /api/articles/{run_id}/cover.png streams BYTEA"
```

---

## Task 5: Backend endpoint — `GET /api/articles` list

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/test_endpoints.py`:

```python
@skip_no_db
def test_articles_list_returns_published_only_ordered_desc():
    """List endpoint returns published rows ordered by published_date DESC.
    Used by the sitemap."""
    with db() as conn:
        cur = conn.cursor()
        for run_id, slug, date, status in [
            ("TEST_list_a", "ev-a", "2026-04-26", "published"),
            ("TEST_list_b", "ev-b", "2026-04-28", "published"),
            ("TEST_list_c", "ev-c", "2026-04-27", "draft"),
        ]:
            cur.execute(
                """
                INSERT INTO articles
                    (run_id, event_slug, alert_ids, headline, subhead,
                     body_markdown, md_path, word_count, status,
                     published_date, tweet_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, slug, [1], f"H {run_id}", "s", "b", "x.md", 600,
                 status, date if status == "published" else None, "tweet"),
            )

    try:
        r = client.get("/api/articles")
        assert r.status_code == 200
        body = r.json()
        # Only published rows should appear
        run_ids = [a["run_id"] for a in body if a["run_id"].startswith("TEST_list_")]
        assert run_ids == ["TEST_list_b", "TEST_list_a"]  # 04-28 before 04-26
        # Shape check
        for a in body:
            if a["run_id"].startswith("TEST_list_"):
                assert {"run_id", "event_slug", "published_date", "headline"} <= a.keys()
    finally:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM articles WHERE run_id LIKE 'TEST_list_%%'")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_list_returns_published_only_ordered_desc -v
```

Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Add the endpoint to `backend/app.py`**

```python
@app.get("/api/articles", response_model=list[ArticleListItem])
def list_articles():
    """List all published articles for sitemap consumption."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, event_slug, published_date, headline
            FROM articles
            WHERE status = 'published'
            ORDER BY published_date DESC, created_at DESC
            """,
        )
        rows = cur.fetchall()
    return [
        ArticleListItem(
            run_id=r[0],
            event_slug=r[1],
            published_date=r[2].isoformat(),
            headline=r[3],
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
DATABASE_URL=postgresql://localhost/polybot_test pytest test_endpoints.py::test_articles_list_returns_published_only_ordered_desc -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "articlebot: GET /api/articles list endpoint for sitemap"
```

---

## Task 6: Articlebot validator — extend for `tweet_text`

**Files:**
- Modify: `storybot/articlebot.py` (validator constants + `validate_article_decision`)
- Modify: `test/test_articlebot_validation.py` (new tests + helper update)

- [ ] **Step 1: Update the validation test helper**

In `test/test_articlebot_validation.py`, update `_valid_decision()` to include `tweet_text`:

```python
def _valid_decision(**overrides):
    base = {
        "decision": "post",
        "reason": "sharp",
        "article": {
            "headline": "Headline",
            "subhead": "Subhead",
            "body_markdown": _valid_body(600),
            "cover_alt_text": "alt",
        },
        "tweet_text": "A 178-20 wallet just stacked $80k on the underdog tonight.",
        "alert_ids": [1],
        "cover_chart_spec": None,
    }
    base.update(overrides)
    return base
```

- [ ] **Step 2: Add new failing tests**

Append to `test/test_articlebot_validation.py`:

```python
def test_tweet_text_missing_fails():
    import articlebot
    d = _valid_decision()
    d.pop("tweet_text")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet_text" in err.lower()


def test_tweet_text_empty_fails():
    import articlebot
    d = _valid_decision(tweet_text="   ")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet_text" in err.lower()


def test_tweet_text_too_long_fails():
    import articlebot
    # 256 visible chars + "\n\n" + URL(23) > 280
    d = _valid_decision(tweet_text="x" * 256)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet" in err.lower()


def test_tweet_text_banned_phrase_fails():
    import articlebot
    d = _valid_decision(tweet_text="Read the full breakdown of this play.")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "banned" in err.lower()


def test_tweet_text_inline_polyspotter_url_fails():
    import articlebot
    d = _valid_decision(
        tweet_text="A wallet just stacked $80k. https://polyspotter.com/alert/123"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "polyspotter" in err.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/test_articlebot_validation.py -v -k tweet_text
```

Expected: 5 FAILS — validator doesn't yet check `tweet_text`.

- [ ] **Step 4: Extend `validate_article_decision` in `storybot/articlebot.py`**

Inside `validate_article_decision` (around line 527-584), add tweet_text checks **after** the body checks and **before** the `alert_ids` check:

```python
    # tweet_text checks
    tweet_text = decision.get("tweet_text")
    if not isinstance(tweet_text, str) or not tweet_text.strip():
        return False, "tweet_text must be a non-empty string when decision=post"

    # Tweet body + "\n\n" + any URL must fit in TWEET_MAX_CHARS.
    # _tweet_length counts every URL as TWEET_URL_CHARS regardless of source length.
    from tweet_utils import TWEET_MAX_CHARS, _tweet_length
    if _tweet_length(tweet_text + "\n\nhttps://x") > TWEET_MAX_CHARS:
        return False, (
            f"tweet_text length combined with URL exceeds {TWEET_MAX_CHARS} "
            f"(tweet_text is {len(tweet_text)} chars)"
        )

    tweet_lower = tweet_text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in tweet_lower:
            return False, f"tweet_text contains banned phrase {phrase!r}"

    if _POLYSPOTTER_URL_RE.search(tweet_text):
        return False, "tweet_text must not contain an inline polyspotter.com URL"
```

The existing imports at the top of `articlebot.py` already pull in `_BANNED_TWEET_PHRASES` and `_POLYSPOTTER_URL_RE` from `tweet_utils`. The local `from tweet_utils import` for `TWEET_MAX_CHARS` and `_tweet_length` keeps the change additive (don't disturb the existing top-of-file import block).

- [ ] **Step 5: Run all validator tests**

```bash
pytest test/test_articlebot_validation.py -v
```

Expected: ALL PASS (existing tests still pass because `_valid_decision` now includes `tweet_text`).

- [ ] **Step 6: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_validation.py
git commit -m "articlebot: validate tweet_text on draft output"
```

---

## Task 7: Articlebot — extend SYSTEM_PROMPT

**Files:**
- Modify: `storybot/articlebot.py` (SYSTEM_PROMPT only)

This is a prompt edit — no new test. The validator caught any structural issues in Task 6, and the e2e test in Task 11 will verify the full flow.

- [ ] **Step 1: Update the SYSTEM_PROMPT**

In `storybot/articlebot.py`, replace the `SYSTEM_PROMPT` (lines 46-147). The full new content:

```python
SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service
that surfaces notable bets on Polymarket (whales, sharp wallets, coordinated
flow, informed edge). Once a day, a cron triggers you to look at what sharp
money has done in the last 24 hours and write ONE article (~600 words) that
will be published as an SEO-indexed page on polyspotter.com, plus a teaser
tweet that links readers TO that article.

Audience: a general audience. Curious news readers, not desk traders. People
who follow the news but don't speak desk slang. The article should be
comprehensible without jargon and should make a stranger care about a
specific bet on a specific market.

## Your job, in order

1. The kickoff message contains the alert(s) for the chosen event, picked by
   a tournament-picker upstream. Their full fields are embedded; no need to
   re-query.

2. RESEARCH. A great article cites specific, surprising facts the raw alerts
   don't already contain. Same data sources storybot's thread bot uses:
   - The wallet(s) — wallet_profiles, wallet_funders, wallet_event_history,
     Data API /trades?user=…
   - The market(s) — Gamma /markets, CLOB /prices-history, /book
   - The event — Gamma /events?slug=…, alerts on the same tag, wallet_theses
   You have ONE research tool: `query(intent, hint?)` — describe WHAT you
   want in natural language. The compressor picks the backend.

3. WRITE the article AND the teaser tweet.

## Article shape (~500-700 words)

- **Headline** — ≤90 chars. Specific. Stakes baked in. NOT a summary; a hook.
- **Subhead** — ≤160 chars. One sentence that adds context the headline
  doesn't have room for. Don't restate the headline.
- **Body markdown** — 450-800 words (target 500-700). Three to four `## H2`
  sections. Pick from this menu:
    - `## The wallet` (or `## The squad` for clusters)
    - `## The bet`
    - `## What the market thinks`
    - `## What to watch`
    - `## The track record`
    - `## The other side`
  Pick 3-4 that fit your story. The article is one continuous piece of
  prose with these section breaks — not a bulleted list.

  Open with a 2-3 sentence opening paragraph BEFORE the first H2 — the hook
  paragraph that makes the reader keep reading. Close with a paragraph
  AFTER the last H2 — the catalyst, level, or wallet to track.

- **Polyspotter link(s) MANDATORY** — at least one inline markdown link
  somewhere in the body. These are internal links that boost SEO and let
  the reader explore the underlying alert. Prefer the closing paragraph.
  Use up to 2 links. Build URLs against `https://polyspotter.com`:
    - market: `https://polyspotter.com/market/<slug>` where <slug> is
      kebab-cased market_title (lowercase, non-alnum → single dash, max 80
      chars) + "-" + first 7 chars of `condition_id`.
    - wallet: `https://polyspotter.com/wallet/<full 0x address>`
    - alert:  `https://polyspotter.com/alert/<id>`
    - tag:    `https://polyspotter.com/tag/<tag-slug>`

- **Cover chart** — pick ONE chart from this menu, or null if no chart fits:
    - `wallet_record_card` — when one sharp wallet's track record carries the story
    - `price_sparkline`    — when the market's price moved
    - `volume_bar`         — when there was a volume surge
    - `cluster_card`       — when a coordinated squad is the story
    - null                 — when no chart adds anything

- **Cover alt text** — ≤200 chars. Plain English description of the chart.

## Teaser tweet (~200-250 chars)

You ALSO produce a `tweet_text` — the teaser that drives readers from X to the
article. It is NOT a summary of the article; it is a hook.

- ≤255 chars. The article URL is appended automatically at publish time —
  you must NOT include any URL in tweet_text yourself.
- Lead with the SINGLE most surprising fact. Same hook-led style as the body
  opening, compressed to one or two sentences.
- 0-1 emoji, no hashtags, no @mentions.
- BANNED jargon and CTAs (same list as the body): "deployed capital", "real
  size", "conviction flow", "high-conviction", "scan window", "composite
  score", "alerted flow", "positioning", "near-resolution flag", "priced
  in", "coordinated burst", "pile-in", "counterpunch", "looked cleaner",
  "linked wallet(s)", "wallet trio/duo/squad", "informed flow", "smart money
  flow", "in bio", "full breakdown", "link below", "more at", "link in bio".

{STYLE_RULES}

## When to skip

If research reveals the picked event is weaker than it looked (track record
softer than the signals suggested, no surprising numbers beyond what's
already in the alert, the narrative just doesn't hold up for a general
audience), return decision=skip. Don't force an article.

## Output format (strict JSON — your final assistant content)

{{
  "decision": "post" | "skip",
  "reason": "one short sentence",
  "article": {{
    "headline": "...",
    "subhead": "...",
    "body_markdown": "...",
    "cover_alt_text": "..."
  }},
  "tweet_text": "...",
  "alert_ids": [<int>, ...],
  "cover_chart_spec": {{
    "chart_type": "wallet_record_card" | "price_sparkline" |
                  "volume_bar" | "cluster_card",
    "alert_id": <int>,
    "params": {{}}
  }}
}}

When decision=skip, set `article`, `tweet_text`, and `cover_chart_spec`
to null and `alert_ids` to null.

Budget: up to {ARTICLE_MAX_TOOL_CALLS} tool calls. If you hit the budget,
write the article with what you have — do not keep digging.
"""
```

- [ ] **Step 2: Verify the file imports and the prompt builds**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
python -c "from storybot import articlebot; assert 'tweet_text' in articlebot.SYSTEM_PROMPT; print('ok, prompt is', len(articlebot.SYSTEM_PROMPT), 'chars')"
```

Expected: `ok, prompt is <some-number> chars`.

- [ ] **Step 3: Commit**

```bash
git add storybot/articlebot.py
git commit -m "articlebot: SYSTEM_PROMPT now requests tweet_text + reframes for on-site publish"
```

---

## Task 8: Refactor `render_cover_chart` to return PNG bytes

**Files:**
- Modify: `storybot/articlebot.py` (`render_cover_chart` function)

The existing function returns the path-or-None and writes bytes to disk internally. We change it to return `(png_bytes_or_None, path_or_None)` so the caller can pass bytes to the storage layer.

- [ ] **Step 1: Update `render_cover_chart` in `storybot/articlebot.py`**

Replace the existing `render_cover_chart` function (around lines 598-630):

```python
def render_cover_chart(
    spec: dict | None,
    chosen_alerts: list[dict],
    out_path: str,
) -> tuple[bytes | None, str | None]:
    """Render the cover chart specified by `cover_chart_spec`.

    Returns (png_bytes, written_path). Either or both may be None on a soft
    failure (no chart spec, missing alert, render error, write error). The
    caller writes png_bytes to the DB; the disk artifact is debug-only.
    """
    if not spec:
        return None, None
    chart_type = spec.get("chart_type")
    alert_id = spec.get("alert_id")
    if not chart_type:
        return None, None
    alert = next((a for a in chosen_alerts if a.get("id") == alert_id), None)
    if alert is None:
        log("articlebot_chart_skip", reason=f"alert_id {alert_id} not in chosen_alerts")
        return None, None
    try:
        png_bytes = _dispatch_chart_render(chart_type, alert)
    except Exception as exc:
        log("articlebot_chart_error",
            chart_type=chart_type, alert_id=alert_id,
            error=f"{type(exc).__name__}: {exc}")
        return None, None
    if not png_bytes:
        log("articlebot_chart_empty", chart_type=chart_type, alert_id=alert_id)
        return None, None
    try:
        with open(out_path, "wb") as f:
            f.write(png_bytes)
    except OSError as exc:
        log("articlebot_chart_write_error",
            out_path=out_path, error=f"{type(exc).__name__}: {exc}")
        # Bytes still good even if disk write failed — we return them.
        return png_bytes, None
    return png_bytes, out_path
```

- [ ] **Step 2: Update callers of `render_cover_chart`**

Search for callers — there's one in `main()` around line 847:

```bash
grep -n "render_cover_chart" /home/bhavya/git/polybot/storybot/articlebot.py
```

Replace the call site in `main()` (around line 847):

```python
    # Stage 4: cover chart
    cover_target_dir = _DRY_RUN_DIR if DRY_RUN else _storage.ARTICLES_DIR
    os.makedirs(cover_target_dir, exist_ok=True)
    cover_path_target = os.path.join(cover_target_dir, f"{run_id}.png")
    cover_bytes, cover_path = render_cover_chart(
        decision.get("cover_chart_spec"), chosen_alerts, cover_path_target
    )
```

- [ ] **Step 3: Smoke-test imports**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
python -c "from storybot import articlebot; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add storybot/articlebot.py
git commit -m "articlebot: render_cover_chart returns (bytes, path) for DB storage"
```

---

## Task 9: `articlebot_storage.persist_article` accepts new fields

**Files:**
- Modify: `storybot/articlebot_storage.py`
- Modify: `test/test_articlebot_storage.py` (the persist_article test)

- [ ] **Step 1: Update the persist_article test**

In `test/test_articlebot_storage.py`, update `_decision()` to include `tweet_text`:

```python
def _decision(**overrides):
    base = {
        "decision": "post",
        "reason": "sharp",
        "event_slug": "alive-event",
        "article": {
            "headline": "Headline",
            "subhead": "Subhead",
            "body_markdown": "Opening.\n\n## A\n\nbody.\n\nClose. https://polyspotter.com/market/x",
            "cover_alt_text": "alt",
        },
        "tweet_text": "An account up $2M just stacked $80k on a coin-flip.",
        "alert_ids": [11, 12],
    }
    base.update(overrides)
    return base
```

Update the `test_persist_article_writes_md_file_and_inserts_row` test to pass `cover_bytes` and assert it lands in the params:

```python
def test_persist_article_writes_md_file_and_inserts_row(tmp_path, monkeypatch):
    import articlebot_storage as st

    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    out = st.persist_article(
        run_id="abc12345",
        decision=_decision(),
        cover_bytes=fake_png,
        cover_path=str(tmp_path / "abc12345.png"),
    )

    md_path = tmp_path / "abc12345.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "# Headline" in content
    assert "Subhead" in content
    assert "abc12345.png" in content
    assert "https://polyspotter.com/market/x" in content
    assert "alert_ids: [11, 12]" in content

    fake_cur.execute.assert_called_once()
    sql, params = fake_cur.execute.call_args.args
    assert "INSERT INTO articles" in sql
    assert "cover_bytes" in sql
    assert "tweet_text" in sql
    # tweet_text should land somewhere in the params
    assert any(
        p == "An account up $2M just stacked $80k on a coin-flip." for p in params
    )
    # cover_bytes wrapped in psycopg2.Binary
    import psycopg2
    cover_binary_or_bytes = [p for p in params if isinstance(p, (bytes, psycopg2.Binary))]
    assert len(cover_binary_or_bytes) == 1

    assert out == {"md_path": str(md_path), "word_count": out["word_count"]}
    assert out["word_count"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/test_articlebot_storage.py::test_persist_article_writes_md_file_and_inserts_row -v
```

Expected: FAIL — signature doesn't accept `cover_bytes`.

- [ ] **Step 3: Update `storybot/articlebot_storage.py`**

Replace `persist_article` (around lines 51-104):

```python
def persist_article(*, run_id: str, decision: dict,
                    cover_bytes: bytes | None,
                    cover_path: str | None) -> dict:
    """INSERT the article row into Postgres and write the .md file to disk.

    Returns {"md_path", "word_count"}.
    Raises on DB failure (caller decides whether to keep the .md file).
    """
    os.makedirs(ARTICLES_DIR, exist_ok=True)

    article = decision.get("article") or {}
    body = article.get("body_markdown", "")
    word_count = _word_count(body)

    md_text = _format_md_file(run_id, decision, cover_path)
    md_path = os.path.join(ARTICLES_DIR, f"{run_id}.md")
    with open(md_path, "w") as f:
        f.write(md_text)

    rel_md = os.path.relpath(md_path, os.path.dirname(ARTICLES_DIR))
    rel_cover = (os.path.relpath(cover_path, os.path.dirname(ARTICLES_DIR))
                 if cover_path else None)

    sql = """
        INSERT INTO articles
            (run_id, event_slug, alert_ids, headline, subhead,
             body_markdown, cover_alt_text, cover_path, md_path,
             word_count, status, cover_bytes, tweet_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
    """
    params = (
        run_id,
        decision.get("event_slug") or "",
        list(decision.get("alert_ids") or []),
        article.get("headline", ""),
        article.get("subhead", ""),
        body,
        article.get("cover_alt_text"),
        rel_cover,
        rel_md,
        word_count,
        psycopg2.Binary(cover_bytes) if cover_bytes else None,
        decision.get("tweet_text") or "",
    )

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    log("articlebot_persisted", run_id=run_id, md_path=md_path,
        word_count=word_count,
        cover=bool(cover_bytes),
        tweet_text_chars=len(decision.get("tweet_text") or ""))

    return {"md_path": md_path, "word_count": word_count}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest test/test_articlebot_storage.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot_storage.py test/test_articlebot_storage.py
git commit -m "articlebot: persist_article writes cover_bytes + tweet_text"
```

---

## Task 10: Articlebot main() — wire the new flow

**Files:**
- Modify: `storybot/articlebot.py` (`main()` function)
- Modify: `test/test_articlebot_e2e.py` (add `tweet_text` to mocked decision)

- [ ] **Step 1: Update the e2e test mock decision**

In `test/test_articlebot_e2e.py`, find `_FINAL_DECISION_JSON` (around line 36) and add `tweet_text`:

```python
_FINAL_DECISION_JSON = json.dumps({
    "decision": "post",
    "reason": "sharp wallet at the buzzer",
    "article": {
        "headline": "A sharp wallet just bought into a forgotten market",
        "subhead": "An account up $2M lifetime is dropping size on a coin-flip",
        "body_markdown": _VALID_BODY,
        "cover_alt_text": "wallet record card",
    },
    "tweet_text": "A wallet up $2M lifetime just dropped $80k on a coin-flip nobody was watching.",
    "alert_ids": [42],
    "cover_chart_spec": {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}},
})
```

- [ ] **Step 2: Update the e2e test's persist_article assertion**

The test currently passes the result of `persist_article` to assertions. Verify after your edits the test passes the new (`cover_bytes=...`) signature. Search for `persist_article` calls or monkeypatches in the test:

```bash
grep -n "persist_article\|_dispatch_chart_render" /home/bhavya/git/polybot/test/test_articlebot_e2e.py
```

If the test monkeypatches `persist_article`, update the patched callable to accept the new kwarg:

```python
captured = {}
def fake_persist(**kwargs):
    captured.update(kwargs)
    return {"md_path": str(tmp_path / "out.md"), "word_count": 600}
monkeypatch.setattr(_storage, "persist_article", fake_persist)
```

Then assert `assert "cover_bytes" in captured` somewhere in the test.

If the test does NOT monkeypatch persist_article, no change needed — the e2e test stubs `_get_conn` upstream.

- [ ] **Step 3: Update `main()` in `storybot/articlebot.py`**

Find the `cover_path = render_cover_chart(...)` line (Task 8 already updated it to a tuple unpack). Then update the call to `persist_article` (around line 863):

```python
    try:
        result = _storage.persist_article(
            run_id=run_id,
            decision=decision,
            cover_bytes=cover_bytes,
            cover_path=cover_path,
        )
    except Exception as exc:
        log("articlebot_persist_error", run_id=run_id,
            error=f"{type(exc).__name__}: {exc}")
        return 1

    print(f"[articlebot] draft run_id={run_id} md={result['md_path']} "
          f"cover={cover_path or 'none'} words={result['word_count']}")
    print(f"[articlebot] review the markdown, then: "
          f"python storybot/publish_article.py {run_id}")
    return 0
```

- [ ] **Step 4: Run the e2e test**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/test_articlebot_e2e.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all storybot/articlebot tests together**

```bash
pytest test/test_articlebot_*.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_e2e.py
git commit -m "articlebot: main() persists cover_bytes; final stdout points at publish_article.py"
```

---

## Task 11: Create `publish_article.py` CLI

**Files:**
- Create: `storybot/publish_article.py`
- Create: `test/test_publish_article.py`

- [ ] **Step 1: Write the failing test for the happy path**

Create `test/test_publish_article.py`:

```python
"""Tests for storybot/publish_article.py."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _draft_row():
    """Return a single 'draft' row tuple shaped like the SELECT in publish_article."""
    return (
        "abc12345",                                                       # run_id
        "test-event",                                                     # event_slug
        "draft",                                                          # status
        b"\x89PNG\r\n\x1a\nfakepngbytes",                                  # cover_bytes
        "An account up $2M just dropped $80k on a coin-flip.",            # tweet_text
    )


def _make_db(rows):
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = rows
    fake_cur.rowcount = 1
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    return fake_conn, fake_cur


def test_publish_happy_path_updates_row_and_posts(monkeypatch):
    import publish_article as pa

    fake_conn, fake_cur = _make_db(_draft_row())
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)

    fake_v2_client = MagicMock()
    fake_v1_client = MagicMock()
    monkeypatch.setattr(pa, "_build_twitter_client", lambda: fake_v2_client)
    monkeypatch.setattr(pa, "_build_twitter_api_v1", lambda: fake_v1_client)

    posted = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        posted["text"] = text
        posted["media_png"] = media_png
        posted["dry_run"] = dry_run
        return "1234567890"
    monkeypatch.setattr(pa, "post_tweet", fake_post_tweet)

    today_iso = date.today().isoformat()
    rc = pa.main(["abc12345"])
    assert rc == 0

    # Tweet body has the article URL appended
    assert "https://polyspotter.com/article/" in posted["text"]
    assert "/test-event" in posted["text"]
    assert posted["media_png"] == b"\x89PNG\r\n\x1a\nfakepngbytes"
    assert posted["dry_run"] is False

    # UPDATE call has the right shape
    update_calls = [c for c in fake_cur.execute.call_args_list
                    if "UPDATE articles" in c.args[0]]
    assert len(update_calls) == 1
    upd_sql, upd_params = update_calls[0].args
    assert "status='published'" in upd_sql or "status = 'published'" in upd_sql
    assert "1234567890" in str(upd_params)
    assert "abc12345" in str(upd_params)


def test_publish_refuses_already_published(monkeypatch):
    import publish_article as pa

    row = list(_draft_row())
    row[2] = "published"
    fake_conn, fake_cur = _make_db(tuple(row))
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)

    rc = pa.main(["abc12345"])
    assert rc == 1


def test_publish_refuses_unknown_run_id(monkeypatch):
    import publish_article as pa

    fake_conn, fake_cur = _make_db(None)
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)

    rc = pa.main(["nope"])
    assert rc == 1


def test_publish_refuses_null_tweet_text(monkeypatch):
    import publish_article as pa

    row = list(_draft_row())
    row[4] = None
    fake_conn, fake_cur = _make_db(tuple(row))
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)

    rc = pa.main(["abc12345"])
    assert rc == 1


def test_publish_with_no_cover_bytes_still_posts(monkeypatch):
    import publish_article as pa

    row = list(_draft_row())
    row[3] = None
    fake_conn, fake_cur = _make_db(tuple(row))
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)
    monkeypatch.setattr(pa, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pa, "_build_twitter_api_v1", lambda: MagicMock())

    captured = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        captured["media_png"] = media_png
        return "9999"
    monkeypatch.setattr(pa, "post_tweet", fake_post_tweet)

    rc = pa.main(["abc12345"])
    assert rc == 0
    assert captured["media_png"] is None


def test_publish_validates_final_tweet_text(monkeypatch):
    import publish_article as pa

    row = list(_draft_row())
    row[4] = "x" * 300  # over budget even before URL appending
    fake_conn, fake_cur = _make_db(tuple(row))
    monkeypatch.setattr(pa, "_get_conn", lambda: fake_conn)
    monkeypatch.setattr(pa, "DRY_RUN", False)

    rc = pa.main(["abc12345"])
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/test_publish_article.py -v
```

Expected: All 6 tests FAIL with `ModuleNotFoundError: No module named 'publish_article'`.

- [ ] **Step 3: Create `storybot/publish_article.py`**

```python
"""Publish a draft articlebot row to polyspotter.com + post the teaser tweet.

Usage:
    python storybot/publish_article.py <run_id>
    DRY_RUN=true python storybot/publish_article.py <run_id>

Replaces mark_published.py — articles now live on our own site, and the
linked tweet is auto-posted at publish time.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log
from tweet_utils import (
    TWEET_MAX_CHARS,
    _BANNED_TWEET_PHRASES,
    _POLYSPOTTER_URL_RE,
    _build_twitter_api_v1,
    _build_twitter_client,
    _tweet_length,
    post_tweet,
)


DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

POLYSPOTTER_BASE = "https://polyspotter.com"


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def _validate_tweet(text: str) -> tuple[bool, str]:
    """Defensive re-validation in case a human edited the row directly."""
    if _tweet_length(text) > TWEET_MAX_CHARS:
        return False, (
            f"final tweet exceeds {TWEET_MAX_CHARS} chars "
            f"(twitter-counted={_tweet_length(text)})"
        )
    lower = text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned phrase {phrase!r}"
    if not _POLYSPOTTER_URL_RE.search(text):
        return False, "tweet is missing the polyspotter article URL"
    return True, ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: publish_article.py <run_id>", file=sys.stderr)
        return 2
    run_id = argv[0]

    log("publish_article_start", run_id=run_id, dry_run=DRY_RUN)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, event_slug, status, cover_bytes, tweet_text
                FROM articles
                WHERE run_id = %s
                LIMIT 1
                """,
                (run_id,),
            )
            row = cur.fetchone()

        if row is None:
            print(f"error: no article found for run_id={run_id!r}", file=sys.stderr)
            return 1

        _, event_slug, status, cover_bytes_raw, tweet_text = row

        if status != "draft":
            print(
                f"error: article {run_id!r} is status={status!r}, expected 'draft'. "
                "Refusing to re-publish.",
                file=sys.stderr,
            )
            return 1

        if not tweet_text or not tweet_text.strip():
            print(
                f"error: article {run_id!r} has no tweet_text. "
                "This is a pre-migration draft — re-run articlebot.py to regenerate.",
                file=sys.stderr,
            )
            return 1

        published_date = date.today()
        article_url = f"{POLYSPOTTER_BASE}/article/{published_date.isoformat()}/{event_slug}"
        tweet = f"{tweet_text}\n\n{article_url}"

        ok, err = _validate_tweet(tweet)
        if not ok:
            print(f"error: {err}", file=sys.stderr)
            return 1

        cover_bytes = bytes(cover_bytes_raw) if cover_bytes_raw else None

        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if cover_bytes else None

        # Print + confirm in DRY_RUN
        print(f"\n--- Tweet ({_tweet_length(tweet)} twitter chars) ---")
        print(tweet)
        print(f"\nArticle URL: {article_url}")
        print(f"Cover: {len(cover_bytes) if cover_bytes else 0} bytes")

        if DRY_RUN:
            try:
                answer = input("\nPost this for real? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer not in ("y", "yes"):
                log("publish_article_dryrun_aborted", run_id=run_id)
                return 0

        try:
            tweet_id = post_tweet(
                tweet,
                twitter_client=twitter_client,
                twitter_api_v1=twitter_api_v1,
                media_png=cover_bytes,
                dry_run=False,
            )
        except Exception as exc:
            log("publish_article_post_error", run_id=run_id,
                error=f"{type(exc).__name__}: {exc}")
            return 1

        x_tweet_url = f"https://x.com/i/web/status/{tweet_id}"

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE articles
                SET status='published',
                    published_date=%s,
                    tweet_id=%s,
                    posted_url=%s,
                    posted_at=NOW()
                WHERE run_id=%s AND status='draft'
                """,
                (published_date, tweet_id, x_tweet_url, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                print(
                    f"error: UPDATE rowcount={cur.rowcount}, expected 1. "
                    "Concurrent publish? Refusing without committing.",
                    file=sys.stderr,
                )
                return 1
        conn.commit()
    finally:
        conn.close()

    log("publish_article_done", run_id=run_id, tweet_id=tweet_id,
        published_date=published_date.isoformat())

    print(f"\n[publish_article] published run_id={run_id}")
    print(f"    article: {article_url}")
    print(f"    tweet:   {x_tweet_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest test/test_publish_article.py -v
```

Expected: ALL 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/publish_article.py test/test_publish_article.py
git commit -m "$(cat <<'EOF'
articlebot: publish_article.py CLI flips draft → published + posts tweet

Reads tweet_text + cover_bytes from the draft row, appends the article URL
(today/event_slug), validates the final tweet, posts via tweet_utils, and
updates the row to published with tweet_id + posted_url. Refuses non-draft
rows and pre-migration drafts (null tweet_text).
EOF
)"
```

---

## Task 12: Delete `mark_published.py`

**Files:**
- Delete: `storybot/mark_published.py`

- [ ] **Step 1: Verify nothing imports it**

```bash
cd /home/bhavya/git/polybot
grep -rn "mark_published" --include="*.py" --include="*.md" --include="*.sh"
```

Expected: only the file itself, possibly references in `CLAUDE.md` (handled in Task 16), and possibly the docstring of `publish_article.py`.

- [ ] **Step 2: Delete the file**

```bash
git rm storybot/mark_published.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "articlebot: drop mark_published.py (replaced by publish_article.py)"
```

---

## Task 13: Frontend — add markdown deps

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install deps**

```bash
cd /home/bhavya/git/polybot/frontend
npm install react-markdown@^9 remark-gfm@^4
```

This updates both `package.json` and `package-lock.json`.

- [ ] **Step 2: Verify lint still passes (no new warnings)**

```bash
npm run lint
```

Expected: PASS (or same warnings as before).

- [ ] **Step 3: Commit**

```bash
cd /home/bhavya/git/polybot
git add frontend/package.json frontend/package-lock.json
git commit -m "frontend: add react-markdown + remark-gfm for article body rendering"
```

---

## Task 14: Frontend — article page

**Files:**
- Create: `frontend/src/app/article/[date]/[slug]/page.jsx`
- Create: `frontend/src/app/article/[date]/[slug]/not-found.jsx`

- [ ] **Step 1: Create `not-found.jsx`**

`frontend/src/app/article/[date]/[slug]/not-found.jsx`:

```jsx
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-24 text-center">
      <h1 className="text-3xl font-semibold">Article not found</h1>
      <p className="mt-4 text-zinc-400">
        We couldn&apos;t find the article you were looking for.
      </p>
      <p className="mt-8">
        <Link href="/" className="text-indigo-400 hover:text-indigo-300 underline">
          Back to PolySpotter
        </Link>
      </p>
    </main>
  );
}
```

- [ ] **Step 2: Create `page.jsx`**

`frontend/src/app/article/[date]/[slug]/page.jsx`:

```jsx
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

async function getArticle(date, slug) {
  try {
    const res = await fetch(
      `${API_URL}/api/articles/by-slug/${encodeURIComponent(date)}/${encodeURIComponent(slug)}`,
      { next: { revalidate: 60 } },
    );
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function coverUrlFor(runId) {
  return `${API_URL}/api/articles/${encodeURIComponent(runId)}/cover.png`;
}

export async function generateMetadata({ params }) {
  const { date, slug } = await params;
  const article = await getArticle(date, slug);
  if (!article) return {};

  const url = `${SITE_URL}/article/${date}/${slug}`;
  const coverUrl = article.has_cover ? coverUrlFor(article.run_id) : null;
  const images = coverUrl
    ? [{ url: coverUrl, alt: article.cover_alt_text || article.headline }]
    : [];

  return {
    title: `${article.headline} · PolySpotter`,
    description: article.subhead,
    alternates: { canonical: url },
    openGraph: {
      type: "article",
      title: article.headline,
      description: article.subhead,
      url,
      publishedTime: article.published_date,
      images,
    },
    twitter: {
      card: "summary_large_image",
      title: article.headline,
      description: article.subhead,
      images: coverUrl ? [coverUrl] : [],
    },
  };
}

function MarkdownLink({ href, children, ...props }) {
  if (!href) return <a {...props}>{children}</a>;
  const isInternal =
    href.startsWith("/") || href.startsWith(SITE_URL);
  if (isInternal) {
    const path = href.startsWith(SITE_URL) ? href.slice(SITE_URL.length) : href;
    return (
      <Link href={path} className="text-indigo-400 hover:text-indigo-300 underline">
        {children}
      </Link>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener nofollow"
      className="text-indigo-400 hover:text-indigo-300 underline"
    >
      {children}
    </a>
  );
}

export default async function ArticlePage({ params }) {
  const { date, slug } = await params;
  const article = await getArticle(date, slug);
  if (!article) notFound();

  const coverUrl = article.has_cover ? coverUrlFor(article.run_id) : null;
  const url = `${SITE_URL}/article/${date}/${slug}`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: article.headline,
    datePublished: article.published_date,
    description: article.subhead,
    image: coverUrl ? [coverUrl] : undefined,
    author: { "@type": "Organization", name: "PolySpotter" },
    publisher: {
      "@type": "Organization",
      name: "PolySpotter",
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/logo.png`,
      },
    },
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
  };

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <header className="mb-10">
        <p className="text-sm text-zinc-500">
          <time dateTime={article.published_date}>
            {new Date(article.published_date).toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </time>
        </p>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">
          {article.headline}
        </h1>
        <p className="mt-4 text-xl text-zinc-300">{article.subhead}</p>
      </header>

      {coverUrl && (
        <div className="mb-10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={coverUrl}
            alt={article.cover_alt_text || article.headline}
            className="w-full rounded-lg"
          />
        </div>
      )}

      <article className="prose prose-invert max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{ a: MarkdownLink }}
        >
          {article.body_markdown}
        </ReactMarkdown>
      </article>

      {article.posted_url && (
        <footer className="mt-12 border-t border-zinc-800 pt-6 text-sm text-zinc-500">
          <a
            href={article.posted_url}
            target="_blank"
            rel="noopener nofollow"
            className="hover:text-zinc-300"
          >
            Discuss this on X →
          </a>
        </footer>
      )}
    </main>
  );
}
```

NOTE: This page uses Tailwind's `prose prose-invert` classes from `@tailwindcss/typography`. Check whether `frontend/src/app/globals.css` already loads it; if not, the markdown will render unstyled but still work. If you want the prose styling, install with `npm install -D @tailwindcss/typography` and add `@plugin "@tailwindcss/typography";` near the top of `globals.css`. Adding the typography plugin is optional polish — verify the page works WITHOUT it before adding the plugin.

- [ ] **Step 3: Smoke-test the build**

```bash
cd /home/bhavya/git/polybot/frontend && npm run build
```

Expected: build SUCCEEDS. The article route shows up in the route list as a dynamic route.

- [ ] **Step 4: Manual smoke test (optional but recommended)**

```bash
# Terminal 1 (backend, with at least one published article in the DB):
cd /home/bhavya/git/polybot/backend && uvicorn app:app --reload

# Terminal 2 (frontend):
cd /home/bhavya/git/polybot/frontend && npm run dev
```

Open `http://localhost:3000/article/<date>/<slug>` in a browser. Expected: the article renders with headline, subhead, cover image, markdown body. View source: `<title>` matches the headline, OG meta tags are populated, JSON-LD `<script>` is present.

If no published article exists yet, you can manually INSERT one in psql for the smoke test:

```sql
INSERT INTO articles
  (run_id, event_slug, alert_ids, headline, subhead, body_markdown,
   md_path, word_count, status, published_date, tweet_text)
VALUES
  ('smoketest', 'fake-event', ARRAY[1], 'Smoke test headline',
   'A subhead for smoke testing.', 'Body **markdown**.\n\n## H2\n\nMore.',
   'smoke.md', 600, 'published', CURRENT_DATE, 'tweet');
```

- [ ] **Step 5: Commit**

```bash
cd /home/bhavya/git/polybot
git add frontend/src/app/article
git commit -m "$(cat <<'EOF'
frontend: /article/[date]/[slug] page with SEO metadata + JSON-LD

Server Component fetching by-slug from the backend, rendering the
markdown body via react-markdown with internal-link rewrites to
Next.js Link, plus generateMetadata for OG/Twitter cards and a
NewsArticle JSON-LD block.
EOF
)"
```

---

## Task 15: Frontend — sitemap includes articles

**Files:**
- Modify: `frontend/src/app/sitemap.js`

The existing sitemap uses `Promise.all([getMarketEntries(), getTagEntries()])` and returns `[...staticPages, ...markets, ...tags]`. We add a parallel `getArticleEntries()` function with the same try/catch pattern as the existing helpers, then include it in the parallel fetch and the final return.

- [ ] **Step 1: Add `getArticleEntries()` to `frontend/src/app/sitemap.js`**

Insert this function near the existing `getMarketEntries` / `getTagEntries`:

```js
async function getArticleEntries() {
  try {
    const res = await fetch(`${API_URL}/api/articles`, FETCH_OPTS);
    if (!res.ok) return [];
    const articles = await res.json();
    return articles.map((a) => ({
      url: `${SITE_URL}/article/${a.published_date}/${a.event_slug}`,
      lastModified: new Date(a.published_date),
      changeFrequency: "weekly",
      priority: 0.8,
    }));
  } catch {
    return [];
  }
}
```

- [ ] **Step 2: Wire it into the default export**

Find the existing parallel fetch (`const [markets, tags] = await Promise.all([...])`) and update both the destructure and the return:

```js
const [markets, tags, articles] = await Promise.all([
  getMarketEntries(),
  getTagEntries(),
  getArticleEntries(),
]);

return [...staticPages, ...articles, ...markets, ...tags];
```

(Articles come right after `staticPages` because they're high-priority editorial content; ordering within a sitemap doesn't affect crawlers but reads better.)

- [ ] **Step 3: Smoke-test the build**

```bash
cd /home/bhavya/git/polybot/frontend && npm run build
```

Expected: PASS, sitemap.xml generates without error. The fetch of `/api/articles` happens at build time, so if the backend is unreachable the try/catch returns `[]` and the build still succeeds.

- [ ] **Step 4: Commit**

```bash
cd /home/bhavya/git/polybot
git add frontend/src/app/sitemap.js
git commit -m "frontend: include published articles in sitemap.xml"
```

---

## Task 16: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace the articlebot block**

Open `CLAUDE.md` and find the articlebot section:

```bash
grep -n "articlebot\|mark_published" /home/bhavya/git/polybot/CLAUDE.md
```

Replace the block (around the "Articlebot (daily X article generator)" section) with:

```markdown
Articlebot (daily PolySpotter article + teaser tweet):
\`\`\`bash
source venv/bin/activate
python storybot/articlebot.py        # writes a draft to articles table + .md to storybot/articles/
DRY_RUN=true python storybot/articlebot.py   # writes to storybot/dry_runs/

# After reviewing the draft (storybot/articles/<run_id>.md):
python storybot/publish_article.py <run_id>
DRY_RUN=true python storybot/publish_article.py <run_id>
\`\`\`

Cron: once daily at 13:00 UTC (9am ET) recommended for articlebot.py;
publish_article.py is run manually after human review.
```

(Drop the literal backticks above when editing — the surrounding markdown context already has its own fencing.)

Remove any reference to `mark_published.py` from `CLAUDE.md`.

- [ ] **Step 2: Sanity check**

```bash
grep -n "mark_published" /home/bhavya/git/polybot/CLAUDE.md
```

Expected: NO output.

- [ ] **Step 3: Commit**

```bash
cd /home/bhavya/git/polybot
git add CLAUDE.md
git commit -m "docs: CLAUDE.md describes the new publish_article.py flow"
```

---

## Task 17: Final integration check

**Files:** none (read-only verification).

- [ ] **Step 1: Run the full Python test suite**

```bash
cd /home/bhavya/git/polybot && source venv/bin/activate
pytest test/ -v
```

Expected: ALL PASS.

- [ ] **Step 2: Run backend tests**

```bash
cd /home/bhavya/git/polybot/backend && source ../venv/bin/activate
DATABASE_URL=postgresql://localhost/polybot_test pytest -v
```

Expected: ALL PASS (assumes a local Postgres is reachable).

- [ ] **Step 3: Frontend lint + build**

```bash
cd /home/bhavya/git/polybot/frontend
npm run lint
npm run build
```

Expected: BOTH PASS.

- [ ] **Step 4: Confirm cutover**

```bash
cd /home/bhavya/git/polybot
test ! -f storybot/mark_published.py && echo "mark_published.py removed ✓"
test -f storybot/publish_article.py && echo "publish_article.py present ✓"
test -f frontend/src/app/article/\[date\]/\[slug\]/page.jsx && echo "article page present ✓"
grep -q "publish_article.py" CLAUDE.md && echo "CLAUDE.md updated ✓"
```

Expected: all four ✓ lines printed.

If everything passes, the on-site publish + tweet teaser flow is complete. The first cron run of `articlebot.py` will write a draft; the human reviews `storybot/articles/<run_id>.md`; `publish_article.py <run_id>` flips it live and tweets.
