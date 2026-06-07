# Daily Digest Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `claude -p`-driven script (`storybot/digestbot.py`) that picks notable Polymarket events (resolving-today + a mixed top-this-week pool), writes a digest stating PolySpotter's lean on each, outputs a styled HTML email file, and publishes the same content to the website at `/digest/[date]`.

**Architecture:** Python script queries Postgres for candidate pools → two `claude -p --model opus` passes (PICK then WRITE) → Python assembles content JSON, renders an inline-styled email HTML file, and upserts a row into a new `digests` table. A FastAPI pair of endpoints serves the digest; two Next.js pages render it. Factual fields (leaning, URL) come from the DB, not the LLM, to avoid hallucination.

**Tech Stack:** Python 3.13 + psycopg2 (script); FastAPI + Pydantic (backend); Next.js 15 / React 19 (frontend). `claude` CLI invoked via `subprocess`. Tests: pytest (backend + script), `npm run build` (frontend — no test harness; lint is pre-existing-broken).

**Spec:** `docs/superpowers/specs/2026-06-06-daily-digest-design.md`

---

## File Structure

**Create**
- `storybot/digestbot.py` — the generator (pools → claude -p ×2 → render → persist).
- `storybot/test_digestbot.py` — unit tests for the pure helpers + the `claude -p` wrapper.
- `frontend/src/app/digest/page.jsx` — digest index page.
- `frontend/src/app/digest/[date]/page.jsx` — digest detail page.
- `frontend/src/app/digest/[date]/not-found.jsx` — 404 for unknown dates.

**Modify**
- `backend/schema.sql` — append `digests` DDL.
- `backend/database.py` — add `_migrate_add_digests`, call it in `init_db()`.
- `backend/models.py` — add digest response models.
- `backend/app.py` — add `GET /api/digests` and `GET /api/digest/{date}`.
- `frontend/src/lib/api.js` — add `fetchDigests()`, `fetchDigest(date)`.

---

## Task 1: `digests` table + migration

**Files:**
- Modify: `backend/schema.sql` (append)
- Modify: `backend/database.py` (`init_db` + new function after `_migrate_add_subscribers`)

- [ ] **Step 1: Append the table DDL to `backend/schema.sql`** (at the end of the file):

```sql

-- digests: one daily editorial digest per date. content_json holds the full
-- structured digest (subject, intro, sections[] with per-event items) and is
-- the source of truth the frontend renders. Idempotent on digest_date so a
-- re-run refreshes the day's digest in place.
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

- [ ] **Step 2: Add the migration function in `backend/database.py`** — immediately after `_migrate_add_subscribers` (ends around line 266):

```python
def _migrate_add_digests(cur):
    """Create the digests table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS digests (
            id            SERIAL PRIMARY KEY,
            digest_date   DATE NOT NULL UNIQUE,
            run_id        TEXT,
            subject       TEXT NOT NULL,
            intro         TEXT,
            content_json  JSONB NOT NULL,
            status        TEXT NOT NULL DEFAULT 'published',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(digest_date DESC)"
    )
```

- [ ] **Step 3: Call it from `init_db()`** — immediately after the `_migrate_add_subscribers(cur)` line (around line 40):

```python
            _migrate_add_digests(cur)
```

- [ ] **Step 4: Verify import**

Run: `cd backend && DATABASE_URL=postgres://x python -c "import database; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/schema.sql backend/database.py
git commit -m "feat(digest): add digests table + migration"
```

---

## Task 2: Digest API models + endpoints

**Files:**
- Modify: `backend/models.py` (append)
- Modify: `backend/app.py` (new endpoints; extend the `from models import (...)` block)
- Create: `backend/test_digest_api.py`

- [ ] **Step 1: Add models to `backend/models.py`** (append at end, matching the file's `BaseModel` style):

```python
# -- Daily digest ------------------------------------------------------------

class DigestSummary(BaseModel):
    digest_date: str
    subject: str


class DigestDetail(BaseModel):
    digest_date: str
    subject: str
    intro: str | None = None
    content_json: dict
```

- [ ] **Step 2: Write the failing endpoint tests** — create `backend/test_digest_api.py`:

```python
from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)

_SAMPLE_CONTENT = {
    "subject": "PolySpotter Daily — 2026-06-06",
    "intro": "Two markets resolve today.",
    "sections": [
        {
            "key": "resolving_today",
            "title": "Resolving Today",
            "items": [
                {
                    "event_slug": "some-event",
                    "headline": "Sharps piling into YES",
                    "leaning": "Yes @ 0.62",
                    "blurb": "Big informed flow late.",
                    "url": "https://polyspotter.com/event/some-event",
                }
            ],
        }
    ],
}


def test_list_digests(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_digest_index_rows",
        lambda: [{"digest_date": "2026-06-06", "subject": "PolySpotter Daily — 2026-06-06"}],
    )
    resp = client.get("/api/digests")
    assert resp.status_code == 200
    assert resp.json() == [
        {"digest_date": "2026-06-06", "subject": "PolySpotter Daily — 2026-06-06"}
    ]


def test_get_digest_found(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_digest_by_date",
        lambda d: {
            "digest_date": "2026-06-06",
            "subject": _SAMPLE_CONTENT["subject"],
            "intro": _SAMPLE_CONTENT["intro"],
            "content_json": _SAMPLE_CONTENT,
        },
    )
    resp = client.get("/api/digest/2026-06-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == _SAMPLE_CONTENT["subject"]
    assert body["content_json"]["sections"][0]["items"][0]["leaning"] == "Yes @ 0.62"


def test_get_digest_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_digest_by_date", lambda d: None)
    resp = client.get("/api/digest/2099-01-01")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_digest_api.py -v`
Expected: FAIL — 404 (routes missing) / AttributeError on `_digest_index_rows`.

- [ ] **Step 4: Implement in `backend/app.py`**

Extend the existing `from models import (...)` block (around line 35) by adding `DigestSummary, DigestDetail` to the imported names.

Add near the other read endpoints (e.g. after the scoreboard endpoint block, around line 1392):

```python
def _digest_index_rows() -> list[dict]:
    """Published digests, newest first. Separated so tests can fake it."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT to_char(digest_date, 'YYYY-MM-DD') AS digest_date, subject
            FROM digests
            WHERE status = 'published'
            ORDER BY digest_date DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def _digest_by_date(date_str: str) -> dict | None:
    """One published digest by YYYY-MM-DD, or None. Separated so tests can fake it."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT to_char(digest_date, 'YYYY-MM-DD') AS digest_date,
                   subject, intro, content_json
            FROM digests
            WHERE digest_date = %s AND status = 'published'
        """, (date_str,))
        row = cur.fetchone()
        return dict(row) if row else None


@app.get("/api/digests", response_model=list[DigestSummary])
def list_digests():
    """All published daily digests, newest first."""
    return _digest_index_rows()


@app.get("/api/digest/{date}", response_model=DigestDetail)
def get_digest(date: str):
    """A single published daily digest by date (YYYY-MM-DD)."""
    row = _digest_by_date(date)
    if not row:
        raise HTTPException(status_code=404, detail="Digest not found.")
    return row
```

> Note: `db()` yields a `RealDictCursor`-style connection whose `cursor()` returns dict rows elsewhere in this file (see `_scoreboard_rows`). `content_json` is JSONB and psycopg2 returns it already deserialized as a `dict`, so it maps straight onto `DigestDetail.content_json`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_digest_api.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/app.py backend/test_digest_api.py
git commit -m "feat(digest): GET /api/digests and /api/digest/{date}"
```

---

## Task 3: digestbot — pure helpers (candidate shaping, leaning, dedupe)

**Files:**
- Create: `storybot/digestbot.py` (module scaffold + pure helpers)
- Create: `storybot/test_digestbot.py`

- [ ] **Step 1: Write the failing tests** — create `storybot/test_digestbot.py`:

```python
import json

import digestbot


def test_leaning_str_with_outcome_and_price():
    assert digestbot.leaning_str({"outcome": "Yes", "entry_price": 0.62}) == "Yes @ 0.62"


def test_leaning_str_outcome_only():
    assert digestbot.leaning_str({"outcome": "Lakers"}) == "Lakers"


def test_leaning_str_none():
    assert digestbot.leaning_str(None) == "No clear lean"
    assert digestbot.leaning_str({}) == "No clear lean"


def test_shape_candidate_parses_json_strings():
    row = {
        "event_slug": "nba-finals",
        "condition_id": "0xabc",
        "market_title": "Will the Lakers win?",
        "market_url": "https://polyspotter.com/event/nba-finals",
        "end_date": None,
        "event_end_estimate": None,
        "total_usd": 12000.0,
        "trade_count": 7,
        "composite_score": 80.0,
        "llm_copy_action": '{"outcome": "Lakers", "entry_price": 0.55}',
        "tags": '["Sports", "NBA"]',
    }
    c = digestbot.shape_candidate(row)
    assert c["event_slug"] == "nba-finals"
    assert c["title"] == "Will the Lakers win?"
    assert c["market_url"] == "https://polyspotter.com/event/nba-finals"
    assert c["total_usd"] == 12000.0
    assert c["trade_count"] == 7
    assert c["composite_score"] == 80.0
    assert c["leaning"] == "Lakers @ 0.55"


def test_dedupe_by_event_keeps_highest_composite():
    cands = [
        {"event_slug": "a", "composite_score": 30.0},
        {"event_slug": "a", "composite_score": 90.0},
        {"event_slug": "b", "composite_score": 50.0},
    ]
    out = digestbot.dedupe_by_event(cands)
    by_slug = {c["event_slug"]: c for c in out}
    assert len(out) == 2
    assert by_slug["a"]["composite_score"] == 90.0
    assert by_slug["b"]["composite_score"] == 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd storybot && python -m pytest test_digestbot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'digestbot'`.

- [ ] **Step 3: Create `storybot/digestbot.py`** with the module scaffold and pure helpers:

```python
"""
PolySpotter daily digest generator.

Picks notable Polymarket events (resolving today + a mixed top-this-week pool),
uses two `claude -p --model opus` passes to choose and write the digest, renders
a styled HTML email file, and upserts the digest into the `digests` table for the
website (/digest/<date>).

Usage:
    DRY_RUN=true python storybot/digestbot.py   # preview into storybot/dry_runs/
    python storybot/digestbot.py                # write email + publish to website
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log

# --- Config -----------------------------------------------------------------

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
CLAUDE_MODEL = "opus"
SITE_URL = os.environ.get("SITE_URL", "https://polyspotter.com")
WEEK_POOL_LIMIT = 25      # max this-week candidates sent to the PICK pass
WEEK_PICKS_MAX = 5        # max this-week events in the final digest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DIGESTS_DIR = os.path.join(_THIS_DIR, "digests")
DRY_RUNS_DIR = os.path.join(_THIS_DIR, "dry_runs")


# --- Pure helpers -----------------------------------------------------------

def _loads(value, default):
    """json.loads a TEXT column that may already be parsed or be NULL/blank."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def leaning_str(copy_action) -> str:
    """Human one-liner for which side PolySpotter leans, from llm_copy_action."""
    if not copy_action or not copy_action.get("outcome"):
        return "No clear lean"
    outcome = copy_action["outcome"]
    entry = copy_action.get("entry_price")
    if isinstance(entry, (int, float)):
        return f"{outcome} @ {entry:.2f}"
    return str(outcome)


def shape_candidate(row: dict) -> dict:
    """Turn a raw alerts row into a compact candidate dict (the unit we pass to
    the PICK pass and later hydrate from)."""
    copy_action = _loads(row.get("llm_copy_action"), {})
    effective = row.get("event_end_estimate") or row.get("end_date")
    return {
        "event_slug": row.get("event_slug") or row.get("condition_id"),
        "title": row.get("market_title"),
        "market_url": row.get("market_url"),
        "resolution_time": effective.isoformat() if effective else None,
        "total_usd": row.get("total_usd"),
        "trade_count": row.get("trade_count"),
        "composite_score": row.get("composite_score"),
        "tags": _loads(row.get("tags"), []),
        "leaning": leaning_str(copy_action),
    }


def dedupe_by_event(cands: list[dict]) -> list[dict]:
    """Keep one candidate per event_slug — the one with the highest composite_score."""
    best: dict[str, dict] = {}
    for c in cands:
        slug = c["event_slug"]
        if slug not in best or (c.get("composite_score") or 0) > (best[slug].get("composite_score") or 0):
            best[slug] = c
    return list(best.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd storybot && python -m pytest test_digestbot.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add storybot/digestbot.py storybot/test_digestbot.py
git commit -m "feat(digest): digestbot pure helpers (shape/leaning/dedupe)"
```

---

## Task 4: digestbot — `claude -p` wrapper + JSON parsing

**Files:**
- Modify: `storybot/digestbot.py` (append functions)
- Modify: `storybot/test_digestbot.py` (append tests)

- [ ] **Step 1: Add failing tests** to `storybot/test_digestbot.py`:

```python
def test_parse_json_response_plain():
    assert digestbot.parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_fenced():
    text = 'here you go:\n```json\n{"a": 2}\n```\nthanks'
    assert digestbot.parse_json_response(text) == {"a": 2}


def test_run_claude_builds_argv_and_passes_stdin(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        return FakeProc()

    monkeypatch.setattr(digestbot.subprocess, "run", fake_run)
    out = digestbot.run_claude("PROMPT", "PAYLOAD")
    assert out == '{"ok": true}'
    assert captured["argv"][:3] == ["claude", "-p", "PROMPT"]
    assert "--model" in captured["argv"]
    assert "opus" in captured["argv"]
    assert "--dangerously-skip-permissions" in captured["argv"]
    assert captured["input"] == "PAYLOAD"


def test_run_claude_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_run_claude(prompt, payload):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else '{"ok": 1}'

    monkeypatch.setattr(digestbot, "run_claude", fake_run_claude)
    assert digestbot.run_claude_json("P", "X") == {"ok": 1}
    assert calls["n"] == 2


def test_run_claude_json_raises_after_two_bad(monkeypatch):
    monkeypatch.setattr(digestbot, "run_claude", lambda p, x: "still not json")
    try:
        digestbot.run_claude_json("P", "X")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd storybot && python -m pytest test_digestbot.py -k "claude or parse_json" -v`
Expected: FAIL — `AttributeError: module 'digestbot' has no attribute 'parse_json_response'`.

- [ ] **Step 3: Append the implementation** to `storybot/digestbot.py`:

```python
# --- claude -p ---------------------------------------------------------------

def run_claude(prompt: str, payload: str) -> str:
    """Invoke the Claude CLI headlessly. `payload` is piped on stdin. No tools."""
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", CLAUDE_MODEL,
         "--dangerously-skip-permissions"],
        input=payload,
        text=True,
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (exit {proc.returncode}): {proc.stderr[:500]}"
        )
    return proc.stdout


def parse_json_response(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating ```json fences/prose."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def run_claude_json(prompt: str, payload: str) -> dict:
    """run_claude + parse_json_response with one retry on non-JSON output."""
    last_err: Exception | None = None
    for attempt in range(2):
        out = run_claude(prompt, payload)
        try:
            return parse_json_response(out)
        except (json.JSONDecodeError, ValueError) as err:
            last_err = err
            log("digest_bad_json", attempt=attempt, error=str(err))
    raise RuntimeError(f"claude -p returned non-JSON twice: {last_err}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd storybot && python -m pytest test_digestbot.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add storybot/digestbot.py storybot/test_digestbot.py
git commit -m "feat(digest): claude -p wrapper with JSON parsing + retry"
```

---

## Task 5: digestbot — content assembly + email HTML renderer

**Files:**
- Modify: `storybot/digestbot.py` (append functions + prompts)
- Modify: `storybot/test_digestbot.py` (append tests)

- [ ] **Step 1: Add failing tests** to `storybot/test_digestbot.py`:

```python
_TODAY_PICK = {
    "event_slug": "nba-finals",
    "title": "Will the Lakers win?",
    "market_url": "https://polyspotter.com/event/nba-finals",
    "leaning": "Lakers @ 0.55",
    "composite_score": 80.0,
}
_WEEK_PICK = {
    "event_slug": "election-x",
    "title": "Will X win?",
    "market_url": "https://polyspotter.com/event/election-x",
    "leaning": "Yes @ 0.40",
    "composite_score": 70.0,
}
_WRITE_OUT = {
    "subject": "PolySpotter Daily — test",
    "intro": "Big day.",
    "writeups": [
        {"event_slug": "nba-finals", "headline": "Sharps on the Lakers", "blurb": "Late informed flow."},
        {"event_slug": "election-x", "headline": "Quiet money on Yes", "blurb": "Coordinated buying."},
    ],
}


def test_assemble_content_merges_facts_from_picks():
    content = digestbot.assemble_content(
        _WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[_WEEK_PICK]
    )
    assert content["subject"] == "PolySpotter Daily — test"
    assert content["intro"] == "Big day."
    sections = {s["key"]: s for s in content["sections"]}
    today_item = sections["resolving_today"]["items"][0]
    # headline/blurb come from the LLM; leaning/url/title come from the DB pick
    assert today_item["headline"] == "Sharps on the Lakers"
    assert today_item["blurb"] == "Late informed flow."
    assert today_item["leaning"] == "Lakers @ 0.55"
    assert today_item["url"] == "https://polyspotter.com/event/nba-finals"
    assert today_item["title"] == "Will the Lakers win?"
    assert sections["top_this_week"]["items"][0]["leaning"] == "Yes @ 0.40"


def test_assemble_content_omits_empty_sections():
    content = digestbot.assemble_content(
        {"subject": "s", "intro": "", "writeups": [
            {"event_slug": "election-x", "headline": "h", "blurb": "b"}]},
        today_picks=[], week_picks=[_WEEK_PICK],
    )
    keys = {s["key"] for s in content["sections"]}
    assert keys == {"top_this_week"}


def test_render_email_html_contains_facts_and_is_inline():
    content = digestbot.assemble_content(
        _WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[_WEEK_PICK]
    )
    html = digestbot.render_email_html(content)
    assert "Sharps on the Lakers" in html
    assert "Lakers @ 0.55" in html
    assert "https://polyspotter.com/event/nba-finals" in html
    assert "Resolving Today" in html
    assert "Top This Week" in html
    # email-safe: no external/embedded stylesheet, inline styles only
    assert "<link" not in html.lower()
    assert "<style" not in html.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd storybot && python -m pytest test_digestbot.py -k "assemble or render_email" -v`
Expected: FAIL — `AttributeError: ... 'assemble_content'`.

- [ ] **Step 3: Append the implementation** to `storybot/digestbot.py`:

```python
# --- Prompts -----------------------------------------------------------------

PICK_PROMPT = (
    "You are the editor of PolySpotter, a Polymarket smart-money tracker. "
    "Stdin is JSON with two candidate lists: `resolving_today` (markets that "
    "resolve today) and `week_pool` (a mix of upcoming-resolution and recently-"
    "active markets). Each candidate has event_slug, title, resolution_time, "
    "total_usd (money behind it), trade_count, composite_score (signal strength, "
    "higher=stronger), and leaning (which side we favor). "
    "Pick the most newsworthy events. Choose ALL genuinely interesting "
    "resolving_today events (max 6). From week_pool choose the 3-5 best, "
    "deliberately balancing popular (high total_usd/trade_count) against "
    "high-conviction (high composite_score). Do not pick the same event_slug "
    "twice. Respond with ONLY JSON, no prose, in this exact shape: "
    '{"resolving_today": [{"event_slug": "...", "reason": "..."}], '
    '"top_this_week": [{"event_slug": "...", "reason": "..."}]}'
)

WRITE_PROMPT = (
    "You are writing the PolySpotter daily digest email. Stdin is JSON with "
    "`resolving_today` and `top_this_week`, each a list of picked events "
    "(event_slug, title, resolution_time, total_usd, trade_count, "
    "composite_score, leaning). Write a punchy subject line, a 1-2 sentence "
    "intro, and for EACH event a short headline (<=8 words) and a 1-2 sentence "
    "blurb explaining why the smart money is interesting and which way we lean. "
    "Be concrete, no hype, no emojis. Do NOT invent prices or URLs. "
    "Respond with ONLY JSON, no prose, in this exact shape: "
    '{"subject": "...", "intro": "...", "writeups": '
    '[{"event_slug": "...", "headline": "...", "blurb": "..."}]}'
)

_SECTIONS = [
    ("resolving_today", "Resolving Today"),
    ("top_this_week", "Top This Week"),
]


# --- Content assembly --------------------------------------------------------

def assemble_content(write_out: dict, today_picks: list[dict],
                     week_picks: list[dict]) -> dict:
    """Merge LLM prose (headline/blurb) with factual fields (leaning/url/title)
    from the DB picks, keyed by event_slug. Factual fields never come from the
    LLM. Empty sections are omitted."""
    writeups = {w["event_slug"]: w for w in write_out.get("writeups", [])}

    def build_items(picks: list[dict]) -> list[dict]:
        items = []
        for p in picks:
            w = writeups.get(p["event_slug"], {})
            items.append({
                "event_slug": p["event_slug"],
                "title": p.get("title"),
                "headline": w.get("headline") or p.get("title") or "",
                "blurb": w.get("blurb") or "",
                "leaning": p.get("leaning") or "No clear lean",
                "url": p.get("market_url") or f"{SITE_URL}/event/{p['event_slug']}",
            })
        return items

    picks_by_key = {"resolving_today": today_picks, "top_this_week": week_picks}
    sections = []
    for key, title in _SECTIONS:
        items = build_items(picks_by_key[key])
        if items:
            sections.append({"key": key, "title": title, "items": items})

    return {
        "subject": write_out.get("subject") or "PolySpotter Daily",
        "intro": write_out.get("intro") or "",
        "sections": sections,
    }


# --- Email HTML rendering ----------------------------------------------------

def _esc(text) -> str:
    s = "" if text is None else str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def render_email_html(content: dict) -> str:
    """Self-contained, inline-styled HTML for pasting into Gmail. No <style>/<link>."""
    wrap = "max-width:640px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#111;"
    parts = [f'<div style="{wrap}">']
    parts.append(
        f'<h1 style="font-size:22px;margin:0 0 4px;">{_esc(content["subject"])}</h1>'
    )
    if content.get("intro"):
        parts.append(
            f'<p style="font-size:15px;color:#444;margin:0 0 20px;">{_esc(content["intro"])}</p>'
        )
    for section in content.get("sections", []):
        parts.append(
            f'<h2 style="font-size:16px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#666;border-bottom:1px solid #eee;padding-bottom:6px;margin:24px 0 12px;">'
            f'{_esc(section["title"])}</h2>'
        )
        for item in section["items"]:
            parts.append('<div style="margin:0 0 16px;">')
            parts.append(
                f'<div style="font-size:16px;font-weight:bold;margin:0 0 2px;">'
                f'{_esc(item["headline"])}</div>'
            )
            parts.append(
                f'<div style="display:inline-block;font-size:13px;font-weight:bold;'
                f'background:#eef6ff;color:#0b6bcb;padding:2px 8px;border-radius:10px;'
                f'margin:0 0 4px;">Leaning: {_esc(item["leaning"])}</div>'
            )
            parts.append(
                f'<p style="font-size:14px;color:#333;margin:4px 0;">{_esc(item["blurb"])}</p>'
            )
            parts.append(
                f'<a href="{_esc(item["url"])}" style="font-size:13px;color:#0b6bcb;">'
                f'View market →</a>'
            )
            parts.append('</div>')
    parts.append(
        '<p style="font-size:12px;color:#999;margin-top:28px;border-top:1px solid #eee;'
        'padding-top:12px;">PolySpotter — smart money on Polymarket.</p>'
    )
    parts.append('</div>')
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd storybot && python -m pytest test_digestbot.py -v`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add storybot/digestbot.py storybot/test_digestbot.py
git commit -m "feat(digest): content assembly + inline email HTML renderer"
```

---

## Task 6: digestbot — DB queries, persistence, and `main()` orchestration

**Files:**
- Modify: `storybot/digestbot.py` (append DB + main)
- Modify: `storybot/test_digestbot.py` (append `output_dir` + persist-skip tests)

- [ ] **Step 1: Add failing tests** to `storybot/test_digestbot.py`:

```python
def test_output_dir_live_vs_dry(monkeypatch):
    monkeypatch.setattr(digestbot, "DRY_RUN", False)
    assert digestbot.output_dir() == digestbot.DIGESTS_DIR
    monkeypatch.setattr(digestbot, "DRY_RUN", True)
    assert digestbot.output_dir() == digestbot.DRY_RUNS_DIR


def test_persist_digest_skipped_in_dry_run(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(digestbot, "DRY_RUN", True)
    monkeypatch.setattr(digestbot, "_get_conn", lambda: (_ for _ in ()).throw(
        AssertionError("DB must not be touched in DRY_RUN")))
    # Should no-op without raising (DB connection never opened).
    digestbot.persist_digest("2026-06-06", "run123", {"subject": "s", "sections": []})
    assert called["n"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd storybot && python -m pytest test_digestbot.py -k "output_dir or persist" -v`
Expected: FAIL — `AttributeError: ... 'output_dir'`.

- [ ] **Step 3: Append DB + persistence + main** to `storybot/digestbot.py`:

```python
# --- Database ----------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


_RESOLVING_TODAY_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE COALESCE(a.event_end_estimate, a.end_date) IS NOT NULL
      AND COALESCE(a.event_end_estimate, a.end_date) >= date_trunc('day', now())
      AND COALESCE(a.event_end_estimate, a.end_date) <  date_trunc('day', now()) + interval '1 day'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""

_WEEK_UPCOMING_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE COALESCE(a.event_end_estimate, a.end_date) > now()
      AND COALESCE(a.event_end_estimate, a.end_date) <= now() + interval '7 days'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""

_WEEK_HOT_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE a.created_at >= now() - interval '7 days'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""


def fetch_candidates() -> dict:
    """Query the three pools and return shaped, deduped candidate lists.
    week_pool excludes anything already in resolving_today and is capped."""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(_RESOLVING_TODAY_SQL)
        today = dedupe_by_event([shape_candidate(dict(r)) for r in cur.fetchall()])
        cur.execute(_WEEK_UPCOMING_SQL)
        upcoming = [shape_candidate(dict(r)) for r in cur.fetchall()]
        cur.execute(_WEEK_HOT_SQL)
        hot = [shape_candidate(dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()

    today_slugs = {c["event_slug"] for c in today}
    week = dedupe_by_event(upcoming + hot)
    week = [c for c in week if c["event_slug"] not in today_slugs]
    week.sort(key=lambda c: c.get("composite_score") or 0, reverse=True)
    week = week[:WEEK_POOL_LIMIT]
    return {"resolving_today": today, "week_pool": week}


# --- Persistence -------------------------------------------------------------

def output_dir() -> str:
    return DRY_RUNS_DIR if DRY_RUN else DIGESTS_DIR


def persist_digest(digest_date: str, run_id: str, content: dict) -> None:
    """Upsert the digest row (published). No-op in DRY_RUN."""
    if DRY_RUN:
        log("digest_persist_skipped_dry_run", digest_date=digest_date)
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO digests (digest_date, run_id, subject, intro,
                                     content_json, status, published_at)
                VALUES (%s, %s, %s, %s, %s, 'published', NOW())
                ON CONFLICT (digest_date) DO UPDATE SET
                    run_id       = EXCLUDED.run_id,
                    subject      = EXCLUDED.subject,
                    intro        = EXCLUDED.intro,
                    content_json = EXCLUDED.content_json,
                    status       = 'published',
                    published_at = NOW()
            """, (
                digest_date, run_id, content["subject"], content.get("intro", ""),
                json.dumps(content),
            ))
        conn.commit()
    finally:
        conn.close()


# --- Orchestration -----------------------------------------------------------

def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    digest_date = datetime.now(timezone.utc).date().isoformat()
    log("digest_run_start", run_id=run_id, digest_date=digest_date, dry_run=DRY_RUN)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1

    candidates = fetch_candidates()
    n_today = len(candidates["resolving_today"])
    n_week = len(candidates["week_pool"])
    log("digest_candidates", run_id=run_id, resolving_today=n_today, week_pool=n_week)
    if n_today == 0 and n_week == 0:
        log("digest_noop", run_id=run_id, reason="no candidates")
        return 0

    # PICK
    selection = run_claude_json(PICK_PROMPT, json.dumps(candidates, default=str))
    by_slug = {c["event_slug"]: c
               for c in candidates["resolving_today"] + candidates["week_pool"]}
    today_picks = [by_slug[p["event_slug"]]
                   for p in selection.get("resolving_today", [])
                   if p.get("event_slug") in by_slug]
    week_picks = [by_slug[p["event_slug"]]
                  for p in selection.get("top_this_week", [])
                  if p.get("event_slug") in by_slug][:WEEK_PICKS_MAX]
    log("digest_picked", run_id=run_id,
        today=len(today_picks), week=len(week_picks))
    if not today_picks and not week_picks:
        log("digest_noop", run_id=run_id, reason="nothing picked")
        return 0

    # WRITE
    write_payload = json.dumps(
        {"resolving_today": today_picks, "top_this_week": week_picks}, default=str)
    write_out = run_claude_json(WRITE_PROMPT, write_payload)
    content = assemble_content(write_out, today_picks, week_picks)

    # Render email file
    os.makedirs(output_dir(), exist_ok=True)
    html_path = os.path.join(output_dir(), f"digest-{digest_date}.html")
    with open(html_path, "w") as f:
        f.write(render_email_html(content))
    log("digest_email_written", run_id=run_id, path=html_path)

    # Publish to website
    persist_digest(digest_date, run_id, content)
    log("digest_run_done", run_id=run_id, digest_date=digest_date,
        published=not DRY_RUN, email=html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd storybot && python -m pytest test_digestbot.py -v`
Expected: PASS (15 passed).

- [ ] **Step 5: Smoke-test the script end to end (DRY_RUN)**

Run:
```bash
source venv/bin/activate
DRY_RUN=true python storybot/digestbot.py
```
Expected: JSON log lines; an HTML file at `storybot/dry_runs/digest-<today>.html`; no DB write. (Requires `DATABASE_URL` in `.env` and the `claude` CLI logged in. If there are no candidates, expect a `digest_noop` log and no file — that is a valid pass.)

- [ ] **Step 6: Commit**

```bash
git add storybot/digestbot.py storybot/test_digestbot.py
git commit -m "feat(digest): candidate queries, upsert persistence, main()"
```

---

## Task 7: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add the client functions** (after `fetchScoreboard`, around line 88):

```javascript
export function fetchDigests() {
  return request("/api/digests");
}

export function fetchDigest(date) {
  return request(`/api/digest/${encodeURIComponent(date)}`);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(digest): fetchDigests + fetchDigest API client"
```

---

## Task 8: Frontend digest index page (`/digest`)

**Files:**
- Create: `frontend/src/app/digest/page.jsx`

- [ ] **Step 1: Create `frontend/src/app/digest/page.jsx`** (mirrors `articles/page.jsx` data-fetch + theme conventions):

```jsx
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

export const metadata = {
  title: "Daily Digest",
  description:
    "PolySpotter daily digest — markets resolving today and the top smart-money plays this week on Polymarket.",
  alternates: { canonical: "/digest" },
  openGraph: {
    title: "Daily Digest · PolySpotter",
    description:
      "Markets resolving today and the top smart-money plays this week on Polymarket.",
    url: `${SITE_URL}/digest`,
    type: "website",
  },
};

async function getDigests() {
  try {
    const res = await fetch(`${API_URL}/api/digests`, { next: { revalidate: 60 } });
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return [];
  }
}

function formatLongDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function DigestIndexPage() {
  const digests = await getDigests();

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          Daily Digest
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
          Filed each morning — what resolves today and the top plays this week.
        </p>
      </header>

      {digests.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No digests yet — check back soon.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {digests.map((d) => (
            <li key={d.digest_date}>
              <Link
                href={`/digest/${d.digest_date}`}
                className="block rounded-xl p-4 transition-colors"
                style={{
                  background: "var(--surface-card)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {formatLongDate(d.digest_date)}
                </div>
                <div className="mt-1 font-semibold" style={{ color: "var(--text-primary)" }}>
                  {d.subject}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
```

- [ ] **Step 2: Build to verify it compiles**

Run: `cd frontend && npm run build 2>&1 | tail -8`
Expected: build completes; `/digest` appears in the route list.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/digest/page.jsx
git commit -m "feat(digest): /digest index page"
```

---

## Task 9: Frontend digest detail page (`/digest/[date]`)

**Files:**
- Create: `frontend/src/app/digest/[date]/page.jsx`
- Create: `frontend/src/app/digest/[date]/not-found.jsx`

- [ ] **Step 1: Create `frontend/src/app/digest/[date]/not-found.jsx`**:

```jsx
import Link from "next/link";

export default function DigestNotFound() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-20 text-center">
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        Digest not found
      </h1>
      <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
        That daily digest doesn&rsquo;t exist (yet).
      </p>
      <Link
        href="/digest"
        className="mt-6 inline-block text-sm font-semibold"
        style={{ color: "var(--accent)" }}
      >
        ← All digests
      </Link>
    </main>
  );
}
```

- [ ] **Step 2: Create `frontend/src/app/digest/[date]/page.jsx`** (renders from `content_json`):

```jsx
import Link from "next/link";
import { notFound } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

async function getDigest(date) {
  try {
    const res = await fetch(`${API_URL}/api/digest/${encodeURIComponent(date)}`, {
      next: { revalidate: 60 },
    });
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function formatLongDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export async function generateMetadata({ params }) {
  const { date } = await params;
  const digest = await getDigest(date);
  if (!digest) return { title: "Digest not found" };
  return {
    title: digest.subject,
    description: digest.intro || "PolySpotter daily digest.",
    alternates: { canonical: `/digest/${date}` },
    openGraph: {
      title: digest.subject,
      description: digest.intro || "PolySpotter daily digest.",
      url: `${SITE_URL}/digest/${date}`,
      type: "article",
    },
  };
}

export default async function DigestDetailPage({ params }) {
  const { date } = await params;
  const digest = await getDigest(date);
  if (!digest) notFound();

  const sections = digest.content_json?.sections || [];

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <Link
        href="/digest"
        className="text-sm font-semibold"
        style={{ color: "var(--accent)" }}
      >
        ← All digests
      </Link>

      <header className="mb-8 mt-4">
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {formatLongDate(digest.digest_date)}
        </div>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          {digest.subject}
        </h1>
        {digest.intro ? (
          <p className="mt-3 text-base" style={{ color: "var(--text-secondary)" }}>
            {digest.intro}
          </p>
        ) : null}
      </header>

      {sections.map((section) => (
        <section key={section.key} className="mb-10">
          <h2
            className="mb-4 text-sm font-bold uppercase tracking-wide"
            style={{ color: "var(--text-muted)" }}
          >
            {section.title}
          </h2>
          <div className="flex flex-col gap-4">
            {section.items.map((item) => (
              <article
                key={item.event_slug}
                className="rounded-xl p-4"
                style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
              >
                <h3 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                  {item.headline}
                </h3>
                <div
                  className="mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-bold"
                  style={{ background: "var(--surface-1)", color: "var(--accent)" }}
                >
                  Leaning: {item.leaning}
                </div>
                <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {item.blurb}
                </p>
                {item.url ? (
                  <a
                    href={item.url}
                    className="mt-2 inline-block text-sm font-semibold"
                    style={{ color: "var(--accent)" }}
                  >
                    View market →
                  </a>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd frontend && npm run build 2>&1 | tail -8`
Expected: build completes; `/digest/[date]` appears in the route list.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/digest/[date]/page.jsx frontend/src/app/digest/[date]/not-found.jsx
git commit -m "feat(digest): /digest/[date] detail page"
```

---

## Final verification

- [ ] **Backend suite green:** `cd backend && python -m pytest -q`
- [ ] **Script suite green:** `cd storybot && python -m pytest test_digestbot.py -q`
- [ ] **Frontend builds:** `cd frontend && npm run build 2>&1 | tail -8`
- [ ] **End-to-end dry run:** `source venv/bin/activate && DRY_RUN=true python storybot/digestbot.py` → inspect `storybot/dry_runs/digest-<today>.html` in a browser.
- [ ] **Live run (when ready):** `python storybot/digestbot.py` → confirm `storybot/digests/digest-<today>.html` exists and `GET https://api.polyspotter.com/api/digest/<today>` returns the digest; open `/digest/<today>` on the site.

---

## Operator workflow (recap)

```bash
source venv/bin/activate
DRY_RUN=true python storybot/digestbot.py     # preview HTML in storybot/dry_runs/
python storybot/digestbot.py                  # writes storybot/digests/digest-<date>.html + publishes /digest/<date>
# open the .html, copy, paste into Gmail, BCC recipients, send
```

---

## Self-Review Notes

- **Spec coverage:** `digests` table + migration (Task 1) ✓; API endpoints (Task 2) ✓; two-pass `claude -p --model opus` PICK→WRITE (Tasks 4, 6) ✓; resolving-today + mixed week pool (Task 6, three SQL pools deduped) ✓; leaning/conviction from `llm_copy_action`/`composite_score` (Task 3) ✓; styled inline email file (Task 5) ✓; publish-immediately with DRY_RUN preview (Task 6) ✓; `/digest` + `/digest/[date]` (Tasks 8, 9) ✓; receipts excluded ✓.
- **Factual integrity:** leaning + URL + title come from DB picks, not the LLM (Task 5 `assemble_content`), preventing hallucinated prices/links.
- **Type consistency:** candidate dict shape (`event_slug`, `title`, `market_url`, `leaning`, `composite_score`) is produced by `shape_candidate` (Task 3) and consumed unchanged by `assemble_content` (Task 5) and `main()` (Task 6); `content_json` shape (`subject`/`intro`/`sections[].items[]`) matches between the renderer (Task 5), the persisted row (Task 6), the API model `DigestDetail` (Task 2), and the frontend pages (Tasks 8, 9).
- **No placeholders:** every step contains complete, runnable code/commands.
```
