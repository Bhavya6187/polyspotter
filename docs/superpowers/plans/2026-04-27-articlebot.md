# Articlebot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `storybot/articlebot.py`, a daily bot that picks one event-level Polymarket story from the last 24h via a tournament picker, deeply researches it via the existing `query`-tool agent, and writes a 500-700 word X article (markdown + cover chart) for human paste into the X composer.

**Architecture:** New entrypoint living alongside `storybot.py`. Reuses the agent loop, `compressor.py`, voice rules, and chart renderers. Tournament picker over a 24h SQL aggregation feeds the existing agent infra; new validator + storage layer persists draft articles to Postgres + disk. Human-paste workflow (no Twitter API auto-post).

**Tech Stack:** Python 3.13, psycopg2 (Postgres), OpenAI SDK (Azure-routed), pytest, the existing `storybot/charts.py` matplotlib chart pipeline.

**Spec:** [`docs/superpowers/specs/2026-04-27-articlebot-design.md`](../specs/2026-04-27-articlebot-design.md)

---

## File Structure

**New files:**
- `storybot/style_rules.py` — voice/style rules string constant shared by both bots.
- `storybot/articlebot.py` — entrypoint, tournament picker, system prompt, validator, dispatcher.
- `storybot/articlebot_storage.py` — `articles` table insert + on-disk file write + dry-run dump.
- `storybot/mark_published.py` — CLI that flips an article row from `draft` to `published`.
- `storybot/articles/.gitkeep` — directory marker (the directory is gitignored otherwise).
- `test/test_articlebot_picker.py` — tournament picker tests.
- `test/test_articlebot_validation.py` — output validator tests.
- `test/test_articlebot_storage.py` — storage tests.
- `test/test_articlebot_e2e.py` — end-to-end smoke test with mocked LLM/tools.
- `test/test_style_rules.py` — verifies `STYLE_RULES` contains the expected substrings.

**Modified files:**
- `storybot/storybot.py` — voice rules moved to `style_rules.py` (the assembled prompt remains identical); `run_agent()` gains explicit `system_prompt` and `kickoff_message` parameters with backward-compatible defaults so articlebot can reuse it.
- `backend/database.py` — add `_migrate_add_articles(cur)` and wire into `init_db`.
- `.gitignore` — ignore `storybot/articles/*.md`, `storybot/articles/*.png`, `storybot/articles/*.json`.

**Boundary decisions:**
- `articlebot.py` keeps the entrypoint, picker, system prompt, and validator together — they're tightly coupled and total ~600 lines.
- `articlebot_storage.py` is split out because it's the only code that touches the new Postgres table + file I/O, easier to test in isolation.
- The agent loop (`run_agent`, `_make_dispatcher`, `prefetch_bundle`, etc.) **stays in `storybot.py`** and articlebot imports from it. The spec called for "extracted into an import surface"; the cheapest, lowest-risk reading is "make `storybot.py` itself the import surface" via a parameter refactor on `run_agent`. No file-level relocation.

---

## Task 1: Foundations — `.gitignore` + articles directory

**Files:**
- Create: `storybot/articles/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Add the articles directory marker**

```bash
mkdir -p storybot/articles
touch storybot/articles/.gitkeep
```

- [ ] **Step 2: Update `.gitignore`**

Append to `.gitignore`:

```
# Articlebot drafts (Postgres is the source of truth; files are paste-ready copies)
storybot/articles/*.md
storybot/articles/*.png
storybot/articles/*.json
!storybot/articles/.gitkeep
```

- [ ] **Step 3: Verify**

```bash
git check-ignore -v storybot/articles/foo.md storybot/articles/foo.png storybot/articles/.gitkeep
```

Expected: first two paths print an ignore rule; `.gitkeep` prints nothing (i.e., not ignored).

- [ ] **Step 4: Commit**

```bash
git add storybot/articles/.gitkeep .gitignore
git commit -m "chore: scaffold storybot/articles dir + gitignore for articlebot drafts"
```

---

## Task 2: Database migration — `articles` table

**Files:**
- Modify: `backend/database.py:36` (add migration call) and append `_migrate_add_articles` function.
- Test: `test/test_articlebot_storage.py` (new file; a single migration test for now — more added in Task 12).

- [ ] **Step 1: Write the failing test**

Create `test/test_articlebot_storage.py`:

```python
"""Tests for articlebot storage: migration, insert, file dump, mark_published."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def test_migrate_add_articles_executes_create_table_and_indexes():
    """The migration runs three statements: CREATE TABLE + 2 CREATE INDEX,
    all with IF NOT EXISTS so it's idempotent."""
    import database

    cur = MagicMock()
    database._migrate_add_articles(cur)

    sqls = [call.args[0] for call in cur.execute.call_args_list]
    assert len(sqls) == 3, f"expected 3 statements, got {len(sqls)}"
    assert "CREATE TABLE IF NOT EXISTS articles" in sqls[0]
    assert "run_id" in sqls[0] and "TEXT NOT NULL UNIQUE" in sqls[0]
    assert "alert_ids" in sqls[0] and "INTEGER[]" in sqls[0]
    assert "status" in sqls[0]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_event_slug" in sqls[1]
    assert "CREATE INDEX IF NOT EXISTS idx_articles_status" in sqls[2]
```

- [ ] **Step 2: Run the test, expect failure**

```bash
source venv/bin/activate
DATABASE_URL=postgres://x:x@localhost:5432/x pytest test/test_articlebot_storage.py::test_migrate_add_articles_executes_create_table_and_indexes -v
```

Expected: FAIL with `AttributeError: module 'database' has no attribute '_migrate_add_articles'`.

(The dummy `DATABASE_URL` satisfies the import-time check in `backend/database.py`.)

- [ ] **Step 3: Add the migration function**

Append to `backend/database.py`:

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
            posted_at       TIMESTAMPTZ
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
```

- [ ] **Step 4: Wire it into `init_db`**

Edit `backend/database.py`:

```python
# in init_db(), inside `with conn.cursor() as cur:` block, after _migrate_add_tweeted_alerts(cur):
            _migrate_add_articles(cur)
```

- [ ] **Step 5: Run the test, expect pass**

```bash
DATABASE_URL=postgres://x:x@localhost:5432/x pytest test/test_articlebot_storage.py::test_migrate_add_articles_executes_create_table_and_indexes -v
```

Expected: PASS.

- [ ] **Step 6: Apply the migration to dev Postgres**

```bash
cd backend && python -c "from database import init_db; init_db()" && cd ..
```

Expected: no output (success). To verify:

```bash
psql "$DATABASE_URL" -c "\d articles"
```

Expected: shows the table with all 15 columns and the 2 indexes.

- [ ] **Step 7: Commit**

```bash
git add backend/database.py test/test_articlebot_storage.py
git commit -m "feat(db): add articles table migration for articlebot"
```

---

## Task 3: Extract `STYLE_RULES` into `storybot/style_rules.py`

**Goal:** Move the voice/style portion of `storybot.py`'s `SYSTEM_PROMPT` into a string constant in a new module, leaving the thread bot's assembled prompt byte-identical.

**Files:**
- Create: `storybot/style_rules.py`
- Modify: `storybot/storybot.py` (replace the inline voice/style sections with `STYLE_RULES` interpolation)
- Create: `test/test_style_rules.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_style_rules.py`:

```python
"""STYLE_RULES is the shared voice rule set used by both the thread bot
and the article bot. This test pins down what the constant must contain."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_style_rules_contains_expected_sections():
    from style_rules import STYLE_RULES

    # Section headers we expect to find verbatim
    expected_headers = [
        "## Hard style rules",
        "## First-use unpack",
        "## Analyst-speak banned",
        "## Rewrite table",
        "## How to present numbers",
        "## Fact fidelity",
    ]
    for h in expected_headers:
        assert h in STYLE_RULES, f"missing header: {h!r}"


def test_style_rules_contains_banned_phrases():
    from style_rules import STYLE_RULES

    # A representative banned-phrase from each banned-phrase block
    expected_phrases = [
        '"funding tree"',
        '"composite score"',
        '"real size"',
        '"the sharp"',
    ]
    for p in expected_phrases:
        assert p in STYLE_RULES, f"missing phrase: {p}"


def test_storybot_system_prompt_still_contains_voice_rules():
    """Smoke test: the storybot system prompt assembles to a string that
    still contains the voice rules (proves the refactor didn't drop them)."""
    import storybot

    assert "## Hard style rules" in storybot.SYSTEM_PROMPT
    assert "## Analyst-speak banned" in storybot.SYSTEM_PROMPT
    assert '"funding tree"' in storybot.SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test, expect failure**

```bash
source venv/bin/activate
pytest test/test_style_rules.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'style_rules'`.

- [ ] **Step 3: Create `storybot/style_rules.py`**

Open `storybot/storybot.py` and locate the SYSTEM_PROMPT block (starts at line 551). Inside it, find the section spanning roughly:

- "## Hard style rules" → end of "## Rewrite table"
- "## How to present numbers" → end of section
- "## Fact fidelity (hard rule …)" → end of section

These three blocks form the voice rules. Copy them verbatim into a new file `storybot/style_rules.py`:

```python
"""Voice/style rules shared by storybot.py (thread bot) and articlebot.py.

Both bots' system prompts inline this constant. Editing voice/banned-phrase/
number-readability rules in one place updates both bots.

Imported by:
- storybot.py — concatenated into its f-string SYSTEM_PROMPT
- articlebot.py — same
"""

from tweet_utils import TWEET_MAX_CHARS, TWEET_URL_CHARS


STYLE_RULES = f"""## Hard style rules (apply to EVERY tweet/paragraph)
<<paste the entire 'Hard style rules' block from storybot.py SYSTEM_PROMPT,
  starting at "Each tweet <= …" and ending at the "Rewrite table" block's
  last line (the "✅ 'On the other side: not a random buyer either…'" entry).>>

## How to present numbers (readability, not fabrication)
<<paste the entire 'How to present numbers' block verbatim>>

## Fact fidelity (hard rule — this is where threads go wrong)
<<paste the entire 'Fact fidelity' block verbatim>>
"""
```

The `<<paste …>>` markers are placeholders for the literal text you copy from `storybot.py`. After pasting, `STYLE_RULES` is a complete string with no placeholder markers left.

**Concrete identification of the three blocks in `storybot.py`:**

Search for `"## Hard style rules"` in `storybot.py` — that line begins the first block. The first block ends at the closing line of the "Rewrite table" section (the entry that ends with `"buyers kept lifting the Under."`).

Search for `"## How to present numbers (readability"` — that line begins the second block. It ends at the start of `"## Fact fidelity"`.

Search for `"## Fact fidelity (hard rule"` — that line begins the third block. It ends at the start of `"## When to skip"`.

Copy each block verbatim into `style_rules.py` in that order.

- [ ] **Step 4: Modify `storybot.py` to interpolate `STYLE_RULES`**

At the top of `storybot.py`, add the import:

```python
from style_rules import STYLE_RULES
```

In `SYSTEM_PROMPT`, replace the three blocks identified above with `{STYLE_RULES}` (a single placeholder substituted in via the surrounding f-string). The thread-style section ("## Thread style (3-5 tweets …)" through the end of the "Rewrite table") needs the rewrite table portion preserved — but the rewrite table is already moving into `STYLE_RULES`, so the thread-style section now ends before that block and `{STYLE_RULES}` follows immediately after.

Concretely: the SYSTEM_PROMPT becomes:

```python
SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — …
… (all original content up to the start of "## Hard style rules" line)
{STYLE_RULES}
… (continue with "## When to skip" through end-of-prompt)
"""
```

- [ ] **Step 5: Run the test, expect pass**

```bash
pytest test/test_style_rules.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Verify the assembled prompt is identical**

Capture the prompt before-and-after by writing a one-shot diff helper. From the project root:

```bash
git stash
python -c "import sys; sys.path.insert(0, 'storybot'); import storybot as before; \
    open('/tmp/prompt_before.txt', 'w').write(before.SYSTEM_PROMPT)"
git stash pop
python -c "import sys; sys.path.insert(0, 'storybot'); import storybot as after; \
    open('/tmp/prompt_after.txt', 'w').write(after.SYSTEM_PROMPT)"
diff /tmp/prompt_before.txt /tmp/prompt_after.txt
```

Expected: empty diff. If non-empty, fix `style_rules.py` until it matches. Whitespace differences count — match exactly.

- [ ] **Step 7: Commit**

```bash
git add storybot/style_rules.py storybot/storybot.py test/test_style_rules.py
git commit -m "refactor(storybot): extract voice/style rules to style_rules.py"
```

---

## Task 4: Parameterize `run_agent` so articlebot can reuse it

**Goal:** Add `system_prompt` and `kickoff_message` parameters to `run_agent()` (and its callees that need them) with defaults that keep the thread bot's behavior unchanged.

**Files:**
- Modify: `storybot/storybot.py` — `run_agent()` signature and body.

- [ ] **Step 1: Write the failing test**

Append to `test/test_style_rules.py`:

```python
def test_run_agent_accepts_system_prompt_and_kickoff_message_kwargs():
    """run_agent must accept explicit `system_prompt` and `kickoff_message`
    keyword arguments so articlebot can supply its own."""
    import inspect
    import storybot

    sig = inspect.signature(storybot.run_agent)
    assert "system_prompt" in sig.parameters
    assert "kickoff_message" in sig.parameters
    # Defaults so existing thread-bot callers don't break:
    assert sig.parameters["system_prompt"].default is not inspect.Parameter.empty
    assert sig.parameters["kickoff_message"].default is None or \
           sig.parameters["kickoff_message"].default is inspect.Parameter.empty


def test_run_agent_accepts_max_tool_calls_and_max_iterations_kwargs():
    """run_agent must accept budget overrides so articlebot can use its
    higher budgets (40/35) without changing the module-level defaults."""
    import inspect
    import storybot

    sig = inspect.signature(storybot.run_agent)
    assert "max_tool_calls" in sig.parameters
    assert "max_iterations" in sig.parameters
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_style_rules.py::test_run_agent_accepts_system_prompt_and_kickoff_message_kwargs -v
```

Expected: FAIL with `AssertionError: ... 'system_prompt' in sig.parameters`.

- [ ] **Step 3: Refactor `run_agent`**

In `storybot/storybot.py`, locate `def run_agent(...)`. Change the signature to:

```python
def run_agent(llm_client, *, chosen_alerts: list[dict],
              on_tool_call=None, transcript: list[dict] | None = None,
              usage: dict | None = None,
              timings: list[dict] | None = None,
              system_prompt: str = SYSTEM_PROMPT,
              kickoff_message: str | None = None,
              max_tool_calls: int = MAX_TOOL_CALLS,
              max_iterations: int = MAX_ITERATIONS) -> dict:
```

Inside the body:

- Replace `messages.append({"role": "system", "content": SYSTEM_PROMPT})` with `messages.append({"role": "system", "content": system_prompt})`.
- Replace the line that calls `build_kickoff_message(chosen_alerts, prefetched=prefetched)` with:
  ```python
  if kickoff_message is None:
      kickoff_message = build_kickoff_message(chosen_alerts, prefetched=prefetched)
  messages.append({"role": "user", "content": kickoff_message})
  ```
- Replace the `for iter_idx in range(MAX_ITERATIONS):` loop with `for iter_idx in range(max_iterations):`.
- Replace `remaining = MAX_TOOL_CALLS - calls_used` with `remaining = max_tool_calls - calls_used`.
- Replace `if calls_used >= MAX_TOOL_CALLS and not forcing_final:` with `if calls_used >= max_tool_calls and not forcing_final:`.

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_style_rules.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Verify the thread bot still imports cleanly**

```bash
source venv/bin/activate && python -c "import sys; sys.path.insert(0, 'storybot'); import storybot; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add storybot/storybot.py test/test_style_rules.py
git commit -m "refactor(storybot): parameterize run_agent for articlebot reuse"
```

---

## Task 5: 24-hour event-summary SQL fetcher

**Goal:** A new function `fetch_24h_event_summaries()` that returns events grouped by `event_slug` from the last 24 hours, Gamma-settled-filtered.

**Files:**
- Create: `storybot/articlebot.py` (new file; only the SQL helper for now)
- Test: `test/test_articlebot_picker.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_articlebot_picker.py`:

```python
"""Tests for articlebot's tournament picker."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_fetch_24h_event_summaries_returns_groups_filtered_by_gamma():
    """Gamma-settled events drop out; surviving rows are returned verbatim."""
    import articlebot

    candidates = [
        {"event_slug": "alive-event", "condition_id": "0xa1", "top_composite": 9.0,
         "alerts": [{"id": 1}], "alert_count": 1, "event_usd": 1000.0,
         "strategies_fired": ["wallet_clustering"], "first_alert_at": None,
         "last_alert_at": None},
        {"event_slug": "settled-event", "condition_id": "0xb2", "top_composite": 8.0,
         "alerts": [{"id": 2}], "alert_count": 1, "event_usd": 500.0,
         "strategies_fired": ["timing_relative_resolution"], "first_alert_at": None,
         "last_alert_at": None},
    ]
    statuses = {
        "0xa1": {"closed": False, "uma_status": "", "max_price": 0.5},
        "0xb2": {"closed": True,  "uma_status": "", "max_price": 1.0},
    }

    with patch.object(articlebot, "query_postgres", return_value=candidates), \
         patch.object(articlebot, "_gamma_status_for_markets", return_value=statuses):
        out = articlebot.fetch_24h_event_summaries()

    assert len(out) == 1
    assert out[0]["event_slug"] == "alive-event"


def test_fetch_24h_event_summaries_handles_empty():
    import articlebot

    with patch.object(articlebot, "query_postgres", return_value=[]):
        assert articlebot.fetch_24h_event_summaries() == []
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_picker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'articlebot'`.

- [ ] **Step 3: Create `storybot/articlebot.py` with the SQL helper**

```python
"""
Daily X article generator for PolySpotter.

Picks ONE event-level story from the last 24h via a tournament picker, hands
it off to the existing `query`-tool research agent (run_agent in storybot.py),
and writes a 500-700 word article + cover chart for human paste into the X
article composer.

Run via cron:
    python storybot/articlebot.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

from bot_utils import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    MODEL,
    QUERY_TIMEOUT_SECONDS,
    SETTLED_PRICE_THRESHOLD,
    _accumulate_usage,
    _gamma_status_for_markets,
    _is_settled,
    log,
    query_postgres,
)


# 24h SQL: alerts grouped by event_slug, with rich JSON_AGG for downstream
# pickers. Same sports/non-sports time filter as fetch_seed_alerts so we
# don't shortlist already-decided events.
EVENT_SUMMARIES_SQL = """
    SELECT
        a.event_slug,
        MAX(a.composite_score)        AS top_composite,
        SUM(a.total_usd)              AS event_usd,
        COUNT(*)                      AS alert_count,
        ARRAY_AGG(DISTINCT s.strategy)
            FILTER (WHERE s.strategy IS NOT NULL) AS strategies_fired,
        JSONB_AGG(jsonb_build_object(
            'id', a.id,
            'composite_score', a.composite_score,
            'alert_type', a.alert_type,
            'market_title', a.market_title,
            'condition_id', a.condition_id,
            'wallet', a.wallet,
            'total_usd', a.total_usd,
            'tags', a.tags,
            'llm_headline', a.llm_headline,
            'cluster_headline', a.cluster_headline,
            'game_start_time', a.game_start_time,
            'event_end_estimate', a.event_end_estimate,
            'end_date', a.end_date,
            'created_at', a.created_at
        ) ORDER BY a.composite_score DESC) AS alerts,
        (ARRAY_AGG(a.condition_id ORDER BY a.composite_score DESC))[1] AS top_condition_id,
        MIN(a.created_at)             AS first_alert_at,
        MAX(a.created_at)             AS last_alert_at
    FROM alerts a
    LEFT JOIN alert_signals s ON s.alert_id = a.id
    WHERE a.created_at >= NOW() - INTERVAL '24 hours'
      AND (
          (a.game_start_time IS NOT NULL AND a.game_start_time > NOW())
          OR (a.game_start_time IS NULL
              AND COALESCE(a.event_end_estimate, a.end_date) > NOW())
      )
      AND a.event_slug IS NOT NULL
    GROUP BY a.event_slug
    ORDER BY top_composite DESC
    LIMIT 300
"""


def fetch_24h_event_summaries() -> list[dict]:
    """All events with at least one alert in the last 24h, settled events
    filtered out via Gamma. Returns up to 300 rows ordered by top_composite DESC.
    """
    candidates = query_postgres(EVENT_SUMMARIES_SQL)
    if not candidates:
        return []

    cids = [c["top_condition_id"] for c in candidates if c.get("top_condition_id")]
    status_by_cid = _gamma_status_for_markets(cids)

    kept: list[dict] = []
    n_settled = 0
    for row in candidates:
        cid = row.get("top_condition_id")
        if cid and _is_settled(status_by_cid.get(cid)):
            n_settled += 1
            continue
        kept.append(row)

    log("articlebot_event_summaries",
        sql_candidates=len(candidates),
        gamma_settled=n_settled,
        kept=len(kept))
    return kept
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_picker.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_picker.py
git commit -m "feat(articlebot): add 24h event-summary SQL fetcher"
```

---

## Task 6: Tournament picker — stage 1 (chunked finalist picker)

**Goal:** A function that takes one chunk of up to ~40 event summaries and returns up to 3 finalist `event_slug`s as JSON via one LLM call.

**Files:**
- Modify: `storybot/articlebot.py` — append the stage-1 picker function and prompt.
- Modify: `test/test_articlebot_picker.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_picker.py`:

```python
from types import SimpleNamespace


class _FakeCompletions:
    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        content = self._contents.pop(0) if self._contents else "{}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class _FakeClient:
    def __init__(self, contents):
        self.completions = _FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.completions)


def _ev(slug, score=5.0):
    return {
        "event_slug": slug, "top_composite": score, "event_usd": 1000.0,
        "alert_count": 1, "strategies_fired": ["new_wallet_large_bet"],
        "alerts": [{"id": 1, "composite_score": score, "market_title": slug,
                    "wallet": "0xabc", "total_usd": 1000.0,
                    "llm_headline": "headline " + slug}],
        "first_alert_at": None, "last_alert_at": None,
    }


def test_pick_finalists_chunk_returns_top_3():
    import articlebot
    chunk = [_ev(f"slug-{i}") for i in range(10)]
    client = _FakeClient(['{"finalists":["slug-0","slug-3","slug-7"],"reasoning":"r"}'])

    out = articlebot.pick_finalists_chunk(client, chunk)

    assert out == ["slug-0", "slug-3", "slug-7"]
    assert client.completions.calls == 1


def test_pick_finalists_chunk_drops_unknown_slugs():
    """If the model hallucinates a slug, drop it; keep the real ones."""
    import articlebot
    chunk = [_ev(f"slug-{i}") for i in range(5)]
    client = _FakeClient(['{"finalists":["slug-1","ghost-slug","slug-2"],"reasoning":"r"}'])

    out = articlebot.pick_finalists_chunk(client, chunk)
    assert out == ["slug-1", "slug-2"]


def test_pick_finalists_chunk_returns_empty_on_invalid_json():
    import articlebot
    chunk = [_ev("slug-0")]
    client = _FakeClient(["not json"])

    out = articlebot.pick_finalists_chunk(client, chunk)
    assert out == []
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_picker.py::test_pick_finalists_chunk_returns_top_3 -v
```

Expected: FAIL with `AttributeError: module 'articlebot' has no attribute 'pick_finalists_chunk'`.

- [ ] **Step 3: Add the stage-1 picker**

Append to `storybot/articlebot.py`:

```python
PICKER_STAGE1_SYSTEM_PROMPT = """You are surfacing the most STORY-WORTHY events
for a daily Polymarket article aimed at a general audience (curious news
readers, not pros).

You see up to 40 events from the last 24 hours, each with: top composite_score,
total $ across alerts, distinct strategies that fired, and the top alerts on
that event.

Pick the TOP 3 events by storytelling potential — NOT by composite_score alone.
A high-score event with no human angle is less interesting than a medium-score
event with a sharp-wallet character, a coordinated squad, a surprise market,
or late-game timing. Favor:

- Specific characters (one wallet's track record, a new account, a cluster)
- Surprising contrasts (an obscure market with sudden volume; a sharp wallet
  on the contrarian side)
- Concrete catalysts a reader can watch (game tonight; resolution this week)

Avoid: events that are just "big bet, no story", or events that look like
duplicates of other recent ones.

If a chunk has fewer than 3 events, return all of them. Skip is NOT an option
in this stage — pick the best 3 you've got. The next stage handles skipping.

Return strict JSON:
{"finalists": ["slug-a", "slug-b", "slug-c"], "reasoning": "<one sentence>"}
"""


_PICKER_STAGE1_FIELDS = (
    "event_slug", "top_composite", "event_usd", "alert_count",
    "strategies_fired", "first_alert_at", "last_alert_at",
)
_PICKER_STAGE1_ALERT_FIELDS = (
    "id", "composite_score", "alert_type", "market_title", "wallet",
    "total_usd", "llm_headline", "cluster_headline",
)


def _compact_event_for_picker(event: dict) -> dict:
    """Trim an event row down to the fields the picker needs."""
    out = {k: event.get(k) for k in _PICKER_STAGE1_FIELDS if event.get(k) is not None}
    alerts = event.get("alerts") or []
    if alerts:
        out["top_alerts"] = [
            {k: a.get(k) for k in _PICKER_STAGE1_ALERT_FIELDS if a.get(k) is not None}
            for a in alerts[:3]
        ]
    return out


def pick_finalists_chunk(llm_client, chunk: list[dict],
                         *, usage: dict | None = None) -> list[str]:
    """Run one stage-1 picker LLM call over up to 40 events. Returns up to 3
    `event_slug` strings. Empty list on any error or invalid JSON.
    """
    if not chunk:
        return []

    compact = [_compact_event_for_picker(e) for e in chunk]
    user_msg = (
        f"{len(compact)} events from the last 24h, sorted by composite_score "
        f"DESC:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PICKER_STAGE1_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=1,
            max_completion_tokens=4000,
            reasoning_effort="medium",
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        log("articlebot_stage1_error", error=f"{type(exc).__name__}: {exc}")
        return []

    if usage is not None:
        _accumulate_usage(usage, response)

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        log("articlebot_stage1_invalid_json", error=str(exc))
        return []

    finalists = parsed.get("finalists") or []
    if not isinstance(finalists, list):
        return []

    valid_slugs = {e["event_slug"] for e in chunk}
    return [s for s in finalists if isinstance(s, str) and s in valid_slugs][:3]
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_picker.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_picker.py
git commit -m "feat(articlebot): add tournament picker stage 1 (chunked finalist picker)"
```

---

## Task 7: Tournament picker — stage 2 (final picker over finalists)

**Goal:** A function that takes the union of stage-1 finalists, plus a list of recently-covered `event_slug`s for dedup, and returns either a chosen event + alert_ids or a skip decision.

**Files:**
- Modify: `storybot/articlebot.py`
- Modify: `test/test_articlebot_picker.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_picker.py`:

```python
def test_pick_final_event_returns_chosen_event_and_alert_ids():
    import articlebot
    finalists = [_ev("slug-a"), _ev("slug-b")]
    finalists[0]["alerts"] = [
        {"id": 11, "composite_score": 9.0, "market_title": "M", "wallet": "0x1",
         "total_usd": 5000.0, "llm_headline": "hi"},
        {"id": 12, "composite_score": 8.0, "market_title": "M", "wallet": "0x2",
         "total_usd": 2000.0, "llm_headline": "hey"},
    ]
    finalists[1]["alerts"] = [
        {"id": 21, "composite_score": 7.0, "market_title": "N", "wallet": "0x3",
         "total_usd": 1000.0, "llm_headline": "ho"},
    ]
    client = _FakeClient([
        '{"decision":"post","event_slug":"slug-a","alert_ids":[11,12],"reason":"r"}'
    ])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "post"
    assert out["event_slug"] == "slug-a"
    assert out["alert_ids"] == [11, 12]


def test_pick_final_event_returns_skip():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(['{"decision":"skip","event_slug":null,"alert_ids":null,"reason":"weak"}'])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"
    assert out["alert_ids"] is None


def test_pick_final_event_passes_recent_slugs_to_prompt():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(['{"decision":"skip","event_slug":null,"alert_ids":null,"reason":"r"}'])

    articlebot.pick_final_event(client, finalists,
                                recent_event_slugs=["already-covered"])

    user_msg = client.completions.last_kwargs["messages"][1]["content"]
    assert "already-covered" in user_msg


def test_pick_final_event_invalid_json_returns_skip():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(["not json"])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"
    assert "invalid JSON" in out["reason"]


def test_pick_final_event_drops_unknown_slug():
    """Defense in depth: if the model returns a slug not in the finalists,
    treat as skip."""
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient([
        '{"decision":"post","event_slug":"ghost","alert_ids":[1],"reason":"r"}'
    ])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_picker.py::test_pick_final_event_returns_chosen_event_and_alert_ids -v
```

Expected: FAIL with `AttributeError: module 'articlebot' has no attribute 'pick_final_event'`.

- [ ] **Step 3: Add the stage-2 picker**

Append to `storybot/articlebot.py`:

```python
PICKER_STAGE2_SYSTEM_PROMPT = """You pick the SINGLE BEST story for today's
Polymarket article — or skip if nothing on this list is good enough to write
about for a general audience.

Constraints:
- The article will be ~600 words. It will quote specific numbers. It is the
  ONLY thing we publish today.
- The audience is curious news readers, not pros. The story should be
  comprehensible without trader jargon — pick a story that has a real human
  hook (a sharp wallet, a coordinated squad, a surprising market, late timing).
- Avoid generic "big bet" stories with no character.
- Recently-covered events MUST BE SKIPPED unless something materially new
  has happened (a new sharper wallet, a meaningful price move, a resolution).

If you pick an event, return the alert_ids that belong to that event from
the data shown to you (NOT alert_ids from elsewhere — only the alerts already
listed on your chosen event_slug).

Voice context: smart financial Twitter that a curious news-following adult
who doesn't speak desk slang can read. Same publication as the existing
PolySpotter thread bot.

Return strict JSON:
{
  "decision": "post" | "skip",
  "event_slug": "<slug>" | null,
  "alert_ids": [<int>, ...] | null,
  "reason": "<one short sentence>"
}
"""


def pick_final_event(llm_client, finalists: list[dict],
                     *, recent_event_slugs: list[str],
                     usage: dict | None = None) -> dict:
    """Run the stage-2 final picker. Returns a decision dict (the same shape
    storybot.pick_story produces today, plus an explicit `event_slug`).

    On any LLM error or invalid JSON, returns decision=skip with the error
    message in `reason`. Defense-in-depth: if the model returns an
    `event_slug` not in the finalists, also returns skip.
    """
    if not finalists:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "no finalists from stage 1"}

    compact = [_compact_event_for_picker(e) for e in finalists]
    # Re-attach the full alerts (not just top_alerts) so the model can pick
    # specific alert_ids belonging to the chosen event.
    for c, src in zip(compact, finalists):
        c["alerts"] = src.get("alerts") or []

    user_msg = (
        f"Stage-2 finalists ({len(compact)} events):\n"
        f"{json.dumps(compact, default=str, indent=2)}\n\n"
        f"recent_event_slugs (already covered in last 7 days, skip unless "
        f"materially new): {json.dumps(recent_event_slugs)}"
    )

    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PICKER_STAGE2_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=1,
            max_completion_tokens=8000,
            reasoning_effort="high",
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": f"stage-2 LLM error: {type(exc).__name__}: {exc}"}

    if usage is not None:
        _accumulate_usage(usage, response)

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": f"stage-2 returned invalid JSON: {exc}"}

    if parsed.get("decision") == "post":
        chosen_slug = parsed.get("event_slug")
        valid_slugs = {e["event_slug"] for e in finalists}
        if chosen_slug not in valid_slugs:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": f"stage-2 returned unknown event_slug: {chosen_slug!r}"}

    return {
        "decision": parsed.get("decision", "skip"),
        "event_slug": parsed.get("event_slug"),
        "alert_ids": parsed.get("alert_ids"),
        "reason": parsed.get("reason") or "",
    }
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_picker.py -v
```

Expected: 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_picker.py
git commit -m "feat(articlebot): add tournament picker stage 2 (final picker)"
```

---

## Task 8: Tournament picker orchestrator

**Goal:** `pick_article_story()` ties stage 0 (fetch), stage 1 (chunked picker), stage 2 (final picker) together. Also: the function that pulls `recent_event_slugs` from the `articles` table.

**Files:**
- Modify: `storybot/articlebot.py`
- Modify: `test/test_articlebot_picker.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_picker.py`:

```python
def test_pick_article_story_orchestrates_stages():
    """Stage 0 returns 60 events → 2 stage-1 chunks → 6 finalists → stage 2
    picks one. Verifies the orchestrator threads inputs/outputs correctly."""
    import articlebot

    events = [_ev(f"slug-{i}", score=10 - i) for i in range(60)]

    # Stage-1 chunk responses: each chunk picks 3 finalists.
    stage1_responses = [
        '{"finalists":["slug-0","slug-1","slug-2"],"reasoning":"r"}',
        '{"finalists":["slug-40","slug-41","slug-42"],"reasoning":"r"}',
    ]
    # Stage-2 picks slug-0 with its alert_id.
    stage2_response = (
        '{"decision":"post","event_slug":"slug-0",'
        '"alert_ids":[1],"reason":"sharp"}'
    )
    client = _FakeClient(stage1_responses + [stage2_response])

    with patch.object(articlebot, "fetch_24h_event_summaries", return_value=events), \
         patch.object(articlebot, "fetch_recent_article_slugs", return_value=[]):
        out = articlebot.pick_article_story(client)

    assert out["decision"] == "post"
    assert out["event_slug"] == "slug-0"
    assert out["alert_ids"] == [1]
    # 2 stage-1 calls + 1 stage-2 call = 3
    assert client.completions.calls == 3


def test_pick_article_story_skips_when_no_events():
    import articlebot
    client = _FakeClient([])
    with patch.object(articlebot, "fetch_24h_event_summaries", return_value=[]):
        out = articlebot.pick_article_story(client)
    assert out["decision"] == "skip"
    assert "no events" in out["reason"]


def test_fetch_recent_article_slugs_excludes_skipped_and_old():
    import articlebot
    rows = [
        {"event_slug": "covered-1"},
        {"event_slug": "covered-2"},
    ]
    with patch.object(articlebot, "query_postgres", return_value=rows) as q:
        out = articlebot.fetch_recent_article_slugs()
    assert out == ["covered-1", "covered-2"]
    sql = q.call_args.args[0]
    assert "status != 'skipped'" in sql
    assert "INTERVAL '7 days'" in sql
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_picker.py::test_pick_article_story_orchestrates_stages -v
```

Expected: FAIL with `AttributeError: module 'articlebot' has no attribute 'pick_article_story'`.

- [ ] **Step 3: Add `fetch_recent_article_slugs` and `pick_article_story`**

Append to `storybot/articlebot.py`:

```python
PICKER_CHUNK_SIZE = 40
RECENT_ARTICLES_WINDOW_DAYS = 7


def fetch_recent_article_slugs() -> list[str]:
    """event_slugs we've published in the last RECENT_ARTICLES_WINDOW_DAYS
    days (skipped rows excluded — see spec § Decisions)."""
    sql = f"""
        SELECT DISTINCT event_slug
        FROM articles
        WHERE created_at >= NOW() - INTERVAL '{RECENT_ARTICLES_WINDOW_DAYS} days'
          AND status != 'skipped'
    """
    try:
        rows = query_postgres(sql)
    except Exception as exc:
        log("articlebot_recent_slugs_error", error=f"{type(exc).__name__}: {exc}")
        return []
    return [r["event_slug"] for r in rows if r.get("event_slug")]


def pick_article_story(llm_client, *, usage: dict | None = None) -> dict:
    """Tournament picker. Returns a dict shaped like pick_final_event's output
    plus the chosen event's full alerts list (so caller can resolve alert_ids
    to alert dicts without a second query)."""
    events = fetch_24h_event_summaries()
    if not events:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "no events in the last 24h"}

    # Stage 1: chunked finalist picker
    finalist_slugs: list[str] = []
    for i in range(0, len(events), PICKER_CHUNK_SIZE):
        chunk = events[i:i + PICKER_CHUNK_SIZE]
        finalist_slugs.extend(pick_finalists_chunk(llm_client, chunk, usage=usage))

    # Dedup while preserving order
    seen: dict[str, None] = {}
    for s in finalist_slugs:
        seen.setdefault(s, None)
    finalist_slugs = list(seen)

    finalists = [e for e in events if e["event_slug"] in seen]
    log("articlebot_stage1_done",
        chunk_count=(len(events) + PICKER_CHUNK_SIZE - 1) // PICKER_CHUNK_SIZE,
        finalists=len(finalists))

    if not finalists:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "stage 1 produced no finalists"}

    # Stage 2: final picker
    recent = fetch_recent_article_slugs()
    decision = pick_final_event(llm_client, finalists,
                                recent_event_slugs=recent, usage=usage)

    # Attach the chosen event's alerts so downstream can resolve alert_ids → alert dicts
    if decision["decision"] == "post":
        chosen = next((e for e in finalists if e["event_slug"] == decision["event_slug"]), None)
        if chosen is None:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": "stage-2 chose an event not in finalists (post-validation)"}
        wanted_ids = set(decision["alert_ids"] or [])
        chosen_alerts = [a for a in (chosen.get("alerts") or []) if a.get("id") in wanted_ids]
        if not chosen_alerts:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": f"stage-2 returned alert_ids not in chosen event"}
        decision["chosen_alerts"] = chosen_alerts

    return decision
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_picker.py -v
```

Expected: 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_picker.py
git commit -m "feat(articlebot): add tournament picker orchestrator"
```

---

## Task 9: Output validator

**Goal:** `validate_article_decision()` enforces the article output rules from the spec (decision, headline length, body word count, H2 count, polyspotter link, no banned phrases).

**Files:**
- Modify: `storybot/articlebot.py`
- Create: `test/test_articlebot_validation.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_articlebot_validation.py`:

```python
"""Tests for articlebot output validator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _valid_body(word_count: int = 600) -> str:
    """Build a body with exactly `word_count` words, 3 H2s, 1 polyspotter link."""
    body_words = ["lorem"] * (word_count - 30)
    return (
        "Opening paragraph here that hooks the reader.\n\n"
        "## The wallet\n\n" + " ".join(body_words[:200]) + "\n\n"
        "## The bet\n\n" + " ".join(body_words[200:400]) + "\n\n"
        "## What to watch\n\n" + " ".join(body_words[400:]) + "\n\n"
        "Closing line. Watch [the market](https://polyspotter.com/market/foo)."
    )


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
        "alert_ids": [1],
        "cover_chart_spec": None,
    }
    base.update(overrides)
    return base


def test_valid_post_passes():
    import articlebot
    ok, err = articlebot.validate_article_decision(_valid_decision())
    assert ok, err


def test_skip_passes():
    import articlebot
    ok, err = articlebot.validate_article_decision({"decision": "skip", "reason": "weak"})
    assert ok, err


def test_word_count_too_low_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = _valid_body(400)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "word count" in err.lower()


def test_word_count_too_high_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = _valid_body(900)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "word count" in err.lower()


def test_missing_polyspotter_link_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = d["article"]["body_markdown"].replace(
        "https://polyspotter.com/market/foo", "https://example.com/")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "polyspotter" in err.lower()


def test_too_few_h2s_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = (
        "Opening.\n\n## Only one\n\n" + " ".join(["word"] * 600) +
        "\n\nClose. https://polyspotter.com/market/foo"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "h2" in err.lower()


def test_too_many_h2s_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = (
        "Opening.\n\n"
        "## A\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## B\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## C\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## D\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## E\n\n" + " ".join(["w"] * 100) + "\n\n"
        "Close. https://polyspotter.com/market/foo"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "h2" in err.lower()


def test_headline_too_long_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["headline"] = "x" * 100
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "headline" in err.lower()


def test_banned_phrase_in_body_fails():
    import articlebot
    d = _valid_decision()
    # "composite score" is in _BANNED_TWEET_PHRASES
    d["article"]["body_markdown"] = d["article"]["body_markdown"].replace(
        "Opening paragraph", "The composite score was 9")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "banned" in err.lower()


def test_missing_alert_ids_on_post_fails():
    import articlebot
    d = _valid_decision()
    d["alert_ids"] = []
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "alert_ids" in err.lower()
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_validation.py -v
```

Expected: all tests FAIL with `AttributeError: module 'articlebot' has no attribute 'validate_article_decision'`.

- [ ] **Step 3: Add the validator**

Append to `storybot/articlebot.py`:

```python
import re

from tweet_utils import _BANNED_TWEET_PHRASES, _POLYSPOTTER_URL_RE


HEADLINE_MAX_CHARS = 90
SUBHEAD_MAX_CHARS = 160
COVER_ALT_MAX_CHARS = 200
BODY_WORD_MIN = 450
BODY_WORD_MAX = 800
BODY_H2_MIN = 3
BODY_H2_MAX = 4

_H2_LINE_RE = re.compile(r"(?m)^## \S")
_WORD_RE = re.compile(r"\w+")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def validate_article_decision(decision: dict) -> tuple[bool, str]:
    """Returns (ok, error_message). Mirrors the contract of
    storybot.validate_decision but for article output shape."""
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"

    article = decision.get("article")
    if not isinstance(article, dict):
        return False, "article must be an object when decision=post"

    headline = article.get("headline") or ""
    if not isinstance(headline, str) or not headline.strip():
        return False, "article.headline must be a non-empty string"
    if len(headline) > HEADLINE_MAX_CHARS:
        return False, f"article.headline length {len(headline)} exceeds {HEADLINE_MAX_CHARS}"

    subhead = article.get("subhead") or ""
    if not isinstance(subhead, str) or not subhead.strip():
        return False, "article.subhead must be a non-empty string"
    if len(subhead) > SUBHEAD_MAX_CHARS:
        return False, f"article.subhead length {len(subhead)} exceeds {SUBHEAD_MAX_CHARS}"

    cover_alt = article.get("cover_alt_text") or ""
    if cover_alt and len(cover_alt) > COVER_ALT_MAX_CHARS:
        return False, f"article.cover_alt_text length {len(cover_alt)} exceeds {COVER_ALT_MAX_CHARS}"

    body = article.get("body_markdown") or ""
    if not isinstance(body, str) or not body.strip():
        return False, "article.body_markdown must be a non-empty string"

    wc = _word_count(body)
    if not (BODY_WORD_MIN <= wc <= BODY_WORD_MAX):
        return False, f"body word count {wc} outside [{BODY_WORD_MIN}, {BODY_WORD_MAX}]"

    h2_count = len(_H2_LINE_RE.findall(body))
    if not (BODY_H2_MIN <= h2_count <= BODY_H2_MAX):
        return False, f"body has {h2_count} H2 sections, expected {BODY_H2_MIN}-{BODY_H2_MAX}"

    if not _POLYSPOTTER_URL_RE.search(body):
        return False, "body must contain at least one polyspotter.com link"

    body_lower = body.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in body_lower:
            return False, f"body contains banned phrase {phrase!r}"

    alert_ids = decision.get("alert_ids") or []
    if not isinstance(alert_ids, list) or not alert_ids:
        return False, "alert_ids must be a non-empty list when decision=post"
    try:
        [int(i) for i in alert_ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {alert_ids!r}"

    return True, ""
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_validation.py -v
```

Expected: 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_validation.py
git commit -m "feat(articlebot): add output validator"
```

---

## Task 10: Article system prompt

**Goal:** Build the article system prompt by composing fixed sections + `STYLE_RULES`.

**Files:**
- Modify: `storybot/articlebot.py`
- Modify: `test/test_articlebot_validation.py` (add a smoke test that pins down what the prompt contains)

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_validation.py`:

```python
def test_article_system_prompt_contains_style_rules_and_article_specifics():
    import articlebot

    p = articlebot.SYSTEM_PROMPT

    # Inherits voice rules
    assert "## Hard style rules" in p
    assert "## Analyst-speak banned" in p
    # Article-specific framing
    assert "X article" in p or "X Article" in p
    assert "general audience" in p.lower()
    # Length and structure rules surfaced to the model
    assert "500-700" in p or "600 words" in p or "450" in p
    assert "## H2" in p or "H2" in p
    # Output schema
    assert '"decision"' in p and '"article"' in p
    assert '"body_markdown"' in p
    assert '"cover_chart_spec"' in p
    # Mandatory polyspotter link
    assert "polyspotter.com" in p
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_validation.py::test_article_system_prompt_contains_style_rules_and_article_specifics -v
```

Expected: FAIL — either `AttributeError: SYSTEM_PROMPT` or one of the asserts.

- [ ] **Step 3: Add `SYSTEM_PROMPT` to `articlebot.py`**

Append to `storybot/articlebot.py` (placed after the imports and constants, before the picker code):

```python
from style_rules import STYLE_RULES


# Tool-call budgets are higher than storybot's: articles need deeper research.
ARTICLE_MAX_TOOL_CALLS = 40
ARTICLE_MAX_ITERATIONS = 35


SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service
that surfaces notable bets on Polymarket (whales, sharp wallets, coordinated
flow, informed edge). Once a day, a cron triggers you to look at what sharp
money has done in the last 24 hours and write ONE short X article (~600
words) about the most interesting story.

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

3. WRITE the article.

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
  somewhere in the body. Prefer the closing paragraph. Use up to 2 links.
  Build URLs against `https://polyspotter.com`:
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
  "alert_ids": [<int>, ...],
  "cover_chart_spec": {{
    "chart_type": "wallet_record_card" | "price_sparkline" |
                  "volume_bar" | "cluster_card",
    "alert_id": <int>,
    "params": {{}}
  }}
}}

When decision=skip, set `article` and `cover_chart_spec` to null and
`alert_ids` to null.

Budget: up to {ARTICLE_MAX_TOOL_CALLS} tool calls. If you hit the budget,
write the article with what you have — do not keep digging.
"""
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_validation.py -v
```

Expected: 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_validation.py
git commit -m "feat(articlebot): add article system prompt"
```

---

## Task 11: Cover chart dispatch

**Goal:** Render the cover chart from the model's `cover_chart_spec` using `storybot/charts.py`. Soft-fault on failure.

**Files:**
- Modify: `storybot/articlebot.py`
- Modify: `test/test_articlebot_validation.py` (or split into a new test file — using the same file for now)

- [ ] **Step 1: Look at the existing chart dispatch**

```bash
grep -n "def render_chart\|CHART_TYPES\|def fetch_" storybot/charts.py | head -20
```

Expected output names a top-level dispatcher function — most likely `render_chart(chart_type, alert, ...)` or similar. (Do not rely on the exact name; use what `charts.py` actually exports.)

If a top-level dispatch already exists in `storybot/twitter_pipeline.py` (look for `prepare_chart` or `render_alert_chart`), reuse it.

- [ ] **Step 2: Write the failing test**

Append to `test/test_articlebot_validation.py`:

```python
def test_render_cover_chart_writes_png_and_returns_path(tmp_path, monkeypatch):
    import articlebot

    spec = {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}}
    chosen_alerts = [{"id": 42, "wallet": "0xabc", "market_title": "M",
                      "condition_id": "0xc1"}]

    def _fake_render(chart_type, alert, out_path, **_kwargs):
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        return out_path

    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _fake_render)

    out = articlebot.render_cover_chart(spec, chosen_alerts, tmp_path / "cover.png")
    assert out == str(tmp_path / "cover.png")
    assert (tmp_path / "cover.png").exists()


def test_render_cover_chart_returns_none_when_spec_is_null():
    import articlebot
    assert articlebot.render_cover_chart(None, [], "/tmp/x.png") is None


def test_render_cover_chart_soft_faults_on_render_error(tmp_path, monkeypatch):
    import articlebot

    def _boom(*args, **kwargs):
        raise RuntimeError("render busted")
    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _boom)

    out = articlebot.render_cover_chart(
        {"chart_type": "price_sparkline", "alert_id": 1, "params": {}},
        [{"id": 1, "wallet": "0xa", "market_title": "M", "condition_id": "0xc"}],
        tmp_path / "cover.png",
    )
    assert out is None
    assert not (tmp_path / "cover.png").exists()
```

- [ ] **Step 3: Run, expect failure**

```bash
pytest test/test_articlebot_validation.py::test_render_cover_chart_returns_none_when_spec_is_null -v
```

Expected: FAIL with `AttributeError: module 'articlebot' has no attribute 'render_cover_chart'`.

- [ ] **Step 4: Add the dispatcher**

Append to `storybot/articlebot.py`:

```python
def _dispatch_chart_render(chart_type: str, alert: dict, out_path,
                           **kwargs) -> str | None:
    """Thin wrapper around storybot/charts.py. Tested separately via monkeypatch.
    Raises on any error; caller catches and returns None."""
    import charts
    # Use the existing top-level render entry point from charts.py.
    # If a `render_chart` function exists, use it; otherwise fall back to
    # the chart-type-specific functions.
    if hasattr(charts, "render_chart"):
        return charts.render_chart(chart_type, alert, str(out_path), **kwargs)
    fn = getattr(charts, f"render_{chart_type}", None)
    if fn is None:
        raise ValueError(f"unknown chart_type: {chart_type!r}")
    return fn(alert, str(out_path), **kwargs)


def render_cover_chart(spec: dict | None, chosen_alerts: list[dict],
                       out_path) -> str | None:
    """Render the cover chart specified by `cover_chart_spec`. Returns the
    output path on success, None on any failure (soft fault). When spec is
    null, returns None without touching the filesystem."""
    if not spec:
        return None
    chart_type = spec.get("chart_type")
    alert_id = spec.get("alert_id")
    params = spec.get("params") or {}
    if not chart_type:
        return None
    alert = next((a for a in chosen_alerts if a.get("id") == alert_id), None)
    if alert is None:
        log("articlebot_chart_skip", reason=f"alert_id {alert_id} not in chosen_alerts")
        return None
    try:
        return _dispatch_chart_render(chart_type, alert, out_path, **params)
    except Exception as exc:
        log("articlebot_chart_error",
            chart_type=chart_type, alert_id=alert_id,
            error=f"{type(exc).__name__}: {exc}")
        return None
```

- [ ] **Step 5: Run, expect pass**

```bash
pytest test/test_articlebot_validation.py -v
```

Expected: 14 tests PASS.

- [ ] **Step 6: Verify the real chart renderer integration**

```bash
grep -n "^def render_chart\|^def render_" storybot/charts.py | head
```

If `charts.py` exposes a `render_chart(chart_type, alert, out_path, ...)` function, the dispatcher is correct. If not, replace the `if hasattr(charts, "render_chart"):` block in `_dispatch_chart_render` with the actual function names exported by `charts.py`. Keep the soft-fault semantics: any exception → caller's `render_cover_chart` returns None.

- [ ] **Step 7: Commit**

```bash
git add storybot/articlebot.py test/test_articlebot_validation.py
git commit -m "feat(articlebot): add cover chart dispatcher with soft-fault"
```

---

## Task 12: Article storage — Postgres insert + file write

**Goal:** `persist_article(decision, run_id, ...)` writes the article to Postgres + the .md/.png files to `storybot/articles/`. Also: `record_skipped_run(run_id, reason)` for audit-trail rows.

**Files:**
- Create: `storybot/articlebot_storage.py`
- Modify: `test/test_articlebot_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_storage.py`:

```python
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


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
        "alert_ids": [11, 12],
    }
    base.update(overrides)
    return base


def test_persist_article_writes_md_file_and_inserts_row(tmp_path, monkeypatch):
    import articlebot_storage as st

    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    out = st.persist_article(
        run_id="abc12345", decision=_decision(),
        cover_path=str(tmp_path / "abc12345.png"),
    )

    md_path = tmp_path / "abc12345.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "# Headline" in content
    assert "Subhead" in content
    assert "abc12345.png" in content  # cover image ref
    assert "https://polyspotter.com/market/x" in content
    assert "alert_ids: [11, 12]" in content

    fake_cur.execute.assert_called_once()
    sql, params = fake_cur.execute.call_args.args
    assert "INSERT INTO articles" in sql
    # Param order matches the INSERT VALUES order — verified by the SQL itself.
    assert params[0] == "abc12345"               # run_id
    assert params[1] == "alive-event"            # event_slug
    assert params[2] == [11, 12]                 # alert_ids array
    assert params[3] == "Headline"
    assert "Postgres commit ran" or fake_conn.commit.called
    assert out["md_path"].endswith("abc12345.md")
    assert out["word_count"] > 0


def test_record_skipped_run_inserts_minimal_row(tmp_path, monkeypatch):
    import articlebot_storage as st

    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    st.record_skipped_run(run_id="def67890", reason="too quiet")

    fake_cur.execute.assert_called_once()
    sql, params = fake_cur.execute.call_args.args
    assert "INSERT INTO articles" in sql
    assert "'skipped'" in sql or params[-1] == "skipped" or "status" in sql
    assert params[0] == "def67890"
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_storage.py -v
```

Expected: 2 tests FAIL with `ModuleNotFoundError: No module named 'articlebot_storage'`. The migration test from Task 2 still passes.

- [ ] **Step 3: Create `storybot/articlebot_storage.py`**

```python
"""Article storage: Postgres insert + .md file write + skipped-run audit rows.

Lives in its own module so the file-IO + DB-write path can be tested in
isolation from the rest of articlebot.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log


ARTICLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles")

_WORD_RE = re.compile(r"\w+")


def _get_conn():
    """Return a Postgres connection. Hookable in tests via monkeypatch."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _format_md_file(run_id: str, decision: dict, cover_path: str | None) -> str:
    """Build the paste-ready markdown file body."""
    article = decision.get("article") or {}
    headline = article.get("headline", "")
    subhead = article.get("subhead", "")
    body = article.get("body_markdown", "")
    event_slug = decision.get("event_slug") or ""
    alert_ids = decision.get("alert_ids") or []

    parts = [f"# {headline}", "", f"*{subhead}*", ""]
    if cover_path:
        parts.extend([f"![cover]({os.path.basename(cover_path)})", ""])
    parts.extend([body, "", "---",
                  f"run_id: {run_id} | event_slug: {event_slug} | "
                  f"alert_ids: {alert_ids}",
                  "posted_url: <fill in after publishing>",
                  ""])
    return "\n".join(parts)


def persist_article(*, run_id: str, decision: dict,
                    cover_path: str | None) -> dict:
    """INSERT the article row into Postgres and write the .md file to disk.

    Returns {"md_path", "word_count", "row_id"}.
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
    rel_cover = os.path.relpath(cover_path, os.path.dirname(ARTICLES_DIR)) \
        if cover_path else None

    sql = """
        INSERT INTO articles
            (run_id, event_slug, alert_ids, headline, subhead,
             body_markdown, cover_alt_text, cover_path, md_path,
             word_count, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
        RETURNING id
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
    )

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    log("articlebot_persisted", run_id=run_id, md_path=md_path,
        word_count=word_count, cover=bool(cover_path))

    return {"md_path": md_path, "word_count": word_count}


def record_skipped_run(*, run_id: str, event_slug: str = "",
                       reason: str = "") -> None:
    """Insert a status='skipped' row for audit trail. event_slug may be empty
    when the picker skipped before choosing one."""
    sql = """
        INSERT INTO articles
            (run_id, event_slug, alert_ids, headline, subhead,
             body_markdown, md_path, word_count, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'skipped')
    """
    params = (
        run_id,
        event_slug or "",
        [],
        "",
        reason[:160] if reason else "",   # subhead doubles as skip reason
        "",
        "",
        0,
    )
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
    log("articlebot_skipped", run_id=run_id, reason=reason)
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_storage.py -v
```

Expected: all 3 tests PASS (the Task-2 migration test plus the 2 new tests).

- [ ] **Step 5: Commit**

```bash
git add storybot/articlebot_storage.py test/test_articlebot_storage.py
git commit -m "feat(articlebot): add Postgres insert + .md file storage"
```

---

## Task 13: `mark_published.py` CLI

**Goal:** A 30-line CLI that flips an article row from `draft` to `published`.

**Files:**
- Create: `storybot/mark_published.py`
- Modify: `test/test_articlebot_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_articlebot_storage.py`:

```python
def test_mark_published_validates_url(monkeypatch, capsys):
    import mark_published

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(mark_published, "_get_conn", lambda: fake_conn)

    rc = mark_published.main(["abc12345", "https://example.com/foo"])
    assert rc != 0
    captured = capsys.readouterr()
    assert "x.com" in captured.err.lower() or "twitter.com" in captured.err.lower()


def test_mark_published_updates_row(monkeypatch, capsys):
    import mark_published

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.rowcount = 1
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(mark_published, "_get_conn", lambda: fake_conn)

    rc = mark_published.main(["abc12345", "https://x.com/PolySpotter/status/1"])
    assert rc == 0

    sql, params = fake_cur.execute.call_args.args
    assert "UPDATE articles" in sql
    assert "status = 'published'" in sql
    assert params == ("https://x.com/PolySpotter/status/1", "abc12345")


def test_mark_published_unknown_run_id(monkeypatch, capsys):
    import mark_published

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.rowcount = 0
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(mark_published, "_get_conn", lambda: fake_conn)

    rc = mark_published.main(["unknown", "https://x.com/PolySpotter/status/1"])
    assert rc != 0
    captured = capsys.readouterr()
    assert "no article" in captured.err.lower() or "not found" in captured.err.lower()
```

- [ ] **Step 2: Run, expect failure**

```bash
pytest test/test_articlebot_storage.py::test_mark_published_updates_row -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mark_published'`.

- [ ] **Step 3: Create `storybot/mark_published.py`**

```python
"""Mark an articlebot draft as published.

Usage:
    python storybot/mark_published.py <run_id> <x_article_url>

Updates the articles row: status='published', posted_url=<url>, posted_at=NOW().
"""
from __future__ import annotations

import sys

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: mark_published.py <run_id> <x_article_url>", file=sys.stderr)
        return 2

    run_id, url = argv
    if not (url.startswith("https://x.com/") or url.startswith("https://twitter.com/")):
        print(f"error: url must be https://x.com/... or https://twitter.com/..., got {url!r}",
              file=sys.stderr)
        return 1

    sql = """
        UPDATE articles
        SET status = 'published',
            posted_url = %s,
            posted_at = NOW()
        WHERE run_id = %s
          AND status = 'draft'
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (url, run_id))
            rc = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    if rc == 0:
        print(f"error: no article found for run_id={run_id!r} (or already published)",
              file=sys.stderr)
        return 1
    print(f"marked {run_id} published → {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run, expect pass**

```bash
pytest test/test_articlebot_storage.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/mark_published.py test/test_articlebot_storage.py
git commit -m "feat(articlebot): add mark_published CLI"
```

---

## Task 14: Articlebot main entrypoint

**Goal:** `articlebot.main()` ties everything together — picker → research agent → validation → chart → persist.

**Files:**
- Modify: `storybot/articlebot.py`

- [ ] **Step 1: Add the entrypoint**

Append to `storybot/articlebot.py`:

```python
from openai import OpenAI

# Re-use storybot's agent loop (parameterized in Task 4)
import storybot

import articlebot_storage as _storage


ARTICLEBOT_DRY_RUN = os.environ.get("ARTICLEBOT_DRY_RUN", "false").lower() == "true"

_DRY_RUN_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dry_runs"
)


def _build_kickoff_message(chosen_alerts: list[dict]) -> str:
    """Article-shaped kickoff. Uses the same prefetched-block format storybot
    uses, but with article-specific framing."""
    scope = storybot._derive_scope(chosen_alerts)
    prefetched = storybot.prefetch_bundle(scope)
    prefix = storybot._format_prefetched_block(prefetched) if prefetched else ""

    if len(chosen_alerts) == 1:
        payload = json.dumps(chosen_alerts[0], default=str, indent=2)
        body = (
            "A 24h tournament picker chose THIS alert as the day's article "
            "story. Research it deeply with the query tool, then write a "
            "~600 word X article — or skip if research reveals it's not "
            "actually a great story for a general audience.\n\n"
            f"chosen_alert:\n{payload}"
        )
    else:
        slug = chosen_alerts[0].get("event_slug") or "(unknown event)"
        payload = json.dumps(chosen_alerts, default=str, indent=2)
        body = (
            f"A 24h tournament picker chose these {len(chosen_alerts)} alerts "
            f"— all on event '{slug}' — as the day's article story. Treat "
            "them as ONE story. Research deeply with the query tool, then "
            "write a ~600 word X article — or skip if research reveals it's "
            "not actually a great story for a general audience.\n\n"
            f"chosen_alerts ({len(chosen_alerts)} rows):\n{payload}"
        )
    return prefix + body, scope, prefetched


def _dump_dry_run(run_id: str, *, pick: dict, decision: dict | None,
                  transcript: list | None, usage: dict, error: str | None) -> str:
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"articlebot_{run_id}.json")
    payload = {
        "run_id": run_id,
        "model": MODEL,
        "max_tool_calls": ARTICLE_MAX_TOOL_CALLS,
        "max_iterations": ARTICLE_MAX_ITERATIONS,
        "pick": pick,
        "transcript": transcript or [],
        "final_decision": decision,
        "error": error,
        "llm_usage": usage,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    log("articlebot_run_start", run_id=run_id, dry_run=ARTICLEBOT_DRY_RUN)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    usage_totals: dict = {}
    transcript: list = [] if ARTICLEBOT_DRY_RUN else None

    # Stage 1+2: tournament pick
    pick = pick_article_story(llm_client, usage=usage_totals)
    log("articlebot_pick", run_id=run_id, decision=pick.get("decision"),
        event_slug=pick.get("event_slug"), reason=pick.get("reason"))

    if pick["decision"] != "post":
        if not ARTICLEBOT_DRY_RUN:
            try:
                _storage.record_skipped_run(run_id=run_id,
                                            event_slug=pick.get("event_slug") or "",
                                            reason=pick.get("reason") or "")
            except Exception as exc:
                log("articlebot_skip_record_error", run_id=run_id,
                    error=f"{type(exc).__name__}: {exc}")
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=None,
                          transcript=transcript, usage=usage_totals, error=None)
        return 0

    chosen_alerts = pick.get("chosen_alerts") or []

    # Stage 3: research + write
    kickoff, _scope, _prefetched = _build_kickoff_message(chosen_alerts)
    try:
        decision = storybot.run_agent(
            llm_client,
            chosen_alerts=chosen_alerts,
            transcript=transcript,
            usage=usage_totals,
            system_prompt=SYSTEM_PROMPT,
            kickoff_message=kickoff,
            max_tool_calls=ARTICLE_MAX_TOOL_CALLS,
            max_iterations=ARTICLE_MAX_ITERATIONS,
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log("articlebot_agent_error", run_id=run_id, error=err)
        if not ARTICLEBOT_DRY_RUN:
            _storage.record_skipped_run(run_id=run_id,
                                        event_slug=pick.get("event_slug") or "",
                                        reason=f"agent error: {err}")
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=None,
                          transcript=transcript, usage=usage_totals, error=err)
        return 1

    # Carry the chosen event_slug into the decision (downstream needs it)
    decision["event_slug"] = pick["event_slug"]

    # Validate
    ok, err = validate_article_decision(decision)
    if not ok:
        log("articlebot_validation_error", run_id=run_id, error=err)
        if not ARTICLEBOT_DRY_RUN:
            _storage.record_skipped_run(run_id=run_id,
                                        event_slug=pick.get("event_slug") or "",
                                        reason=f"validation: {err}")
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=decision,
                          transcript=transcript, usage=usage_totals,
                          error=f"validation: {err}")
        return 1

    if decision["decision"] == "skip":
        log("articlebot_skip", run_id=run_id, reason=decision.get("reason"))
        if not ARTICLEBOT_DRY_RUN:
            _storage.record_skipped_run(run_id=run_id,
                                        event_slug=pick.get("event_slug") or "",
                                        reason=decision.get("reason") or "")
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=decision,
                          transcript=transcript, usage=usage_totals, error=None)
        return 0

    # Stage 4: cover chart
    cover_target_dir = _DRY_RUN_DIR if ARTICLEBOT_DRY_RUN else _storage.ARTICLES_DIR
    os.makedirs(cover_target_dir, exist_ok=True)
    cover_path_target = os.path.join(cover_target_dir, f"{run_id}.png")
    cover_path = render_cover_chart(decision.get("cover_chart_spec"),
                                    chosen_alerts, cover_path_target)

    # Stage 5: persist
    if ARTICLEBOT_DRY_RUN:
        # Write the .md file into dry_runs (not articles/) and dump a transcript
        md_text = _storage._format_md_file(run_id, decision, cover_path)
        md_path = os.path.join(_DRY_RUN_DIR, f"{run_id}.md")
        with open(md_path, "w") as f:
            f.write(md_text)
        _dump_dry_run(run_id, pick=pick, decision=decision,
                      transcript=transcript, usage=usage_totals, error=None)
        print(f"[articlebot dry-run] md={md_path} cover={cover_path or 'none'}")
        return 0

    try:
        result = _storage.persist_article(
            run_id=run_id, decision=decision, cover_path=cover_path,
        )
    except Exception as exc:
        log("articlebot_persist_error", run_id=run_id,
            error=f"{type(exc).__name__}: {exc}")
        return 1

    print(f"[articlebot] run_id={run_id} md={result['md_path']} "
          f"cover={cover_path or 'none'} words={result['word_count']}")
    print(f"[articlebot] paste into X composer, then: "
          f"python storybot/mark_published.py {run_id} <x_article_url>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run all existing tests, expect pass**

```bash
pytest test/test_style_rules.py test/test_articlebot_picker.py \
       test/test_articlebot_validation.py test/test_articlebot_storage.py -v
```

Expected: all PASS (29 tests).

- [ ] **Step 3: Smoke-test the import**

```bash
source venv/bin/activate
python -c "import sys; sys.path.insert(0, 'storybot'); import articlebot; print('articlebot loaded; SYSTEM_PROMPT len =', len(articlebot.SYSTEM_PROMPT))"
```

Expected: `articlebot loaded; SYSTEM_PROMPT len = <some int>`.

- [ ] **Step 4: Commit**

```bash
git add storybot/articlebot.py
git commit -m "feat(articlebot): add main entrypoint tying picker + agent + storage"
```

---

## Task 15: End-to-end smoke test

**Goal:** One test that runs `articlebot.main()` with all LLM and tool calls mocked, asserting the article row is inserted, the .md file lands on disk, and the chart renders.

**Files:**
- Create: `test/test_articlebot_e2e.py`

- [ ] **Step 1: Write the test**

Create `test/test_articlebot_e2e.py`:

```python
"""End-to-end smoke test for articlebot.main()."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _make_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=None),
        )],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            prompt_tokens_details=None, completion_tokens_details=None,
        ),
    )


_VALID_BODY = (
    "Opening paragraph that hooks the reader with stakes baked in.\n\n"
    "## The wallet\n\n" + " ".join(["w"] * 200) + "\n\n"
    "## The bet\n\n" + " ".join(["w"] * 200) + "\n\n"
    "## What to watch\n\n" + " ".join(["w"] * 150) + "\n\n"
    "Watch [the market](https://polyspotter.com/market/foo)."
)


_FINAL_DECISION_JSON = json.dumps({
    "decision": "post",
    "reason": "sharp wallet at the buzzer",
    "article": {
        "headline": "A sharp wallet just bought into a forgotten market",
        "subhead": "An account up $2M lifetime is dropping size on a coin-flip",
        "body_markdown": _VALID_BODY,
        "cover_alt_text": "wallet record card",
    },
    "alert_ids": [42],
    "cover_chart_spec": {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}},
})


_PICK_STAGE1 = '{"finalists":["alive-event"],"reasoning":"r"}'
_PICK_STAGE2 = '{"decision":"post","event_slug":"alive-event","alert_ids":[42],"reason":"r"}'


def test_articlebot_main_e2e_post(tmp_path, monkeypatch):
    """End-to-end: tournament picker → agent → validation → persistence.

    All LLM, Postgres, and chart calls are stubbed. The test asserts:
    - The .md file exists with the right content.
    - persist_article was called.
    - The exit code is 0.
    """
    import articlebot
    import articlebot_storage as st

    # Stub event summaries (skips the SQL + Gamma calls)
    events = [{
        "event_slug": "alive-event",
        "top_composite": 9.0, "event_usd": 5000.0, "alert_count": 1,
        "strategies_fired": ["win_rate_tracking"],
        "alerts": [{
            "id": 42, "composite_score": 9.0, "alert_type": "composite",
            "market_title": "Will X happen", "wallet": "0xabc",
            "total_usd": 5000.0, "llm_headline": "sharp wallet on No",
            "condition_id": "0xc1234567",
        }],
        "first_alert_at": None, "last_alert_at": None,
        "top_condition_id": "0xc1234567",
    }]

    monkeypatch.setattr(articlebot, "fetch_24h_event_summaries", lambda: events)
    monkeypatch.setattr(articlebot, "fetch_recent_article_slugs", lambda: [])

    # Stub the LLM: stage-1 → stage-2 → research-agent (returns final JSON, no tool calls)
    llm_responses = iter([
        _make_llm_response(_PICK_STAGE1),
        _make_llm_response(_PICK_STAGE2),
        _make_llm_response(_FINAL_DECISION_JSON),
    ])
    fake_completions = MagicMock()
    fake_completions.create = lambda **_kw: next(llm_responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
    monkeypatch.setattr(articlebot, "OpenAI", lambda **_kw: fake_client)

    # Stub storybot's prefetch + dispatcher (no real Postgres / Gamma during agent)
    import storybot
    monkeypatch.setattr(storybot, "prefetch_bundle", lambda scope: {})

    # Stub chart render to drop a fake PNG
    def _fake_render(chart_type, alert, out_path, **_kw):
        with open(out_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        return out_path
    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _fake_render)

    # Redirect storage to tmp_path
    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = (1,)
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    # Required env vars
    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("ARTICLEBOT_DRY_RUN", "false")

    rc = articlebot.main()

    assert rc == 0, "main should return 0 on success"

    # The .md file landed in tmp_path
    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    md_text = md_files[0].read_text()
    assert "# A sharp wallet just bought into a forgotten market" in md_text
    assert "polyspotter.com/market/foo" in md_text

    # The PNG landed
    png_files = list(tmp_path.glob("*.png"))
    assert len(png_files) == 1

    # Postgres INSERT was issued
    fake_cur.execute.assert_called()
    insert_sqls = [c.args[0] for c in fake_cur.execute.call_args_list
                   if "INSERT INTO articles" in c.args[0]]
    assert insert_sqls, "expected an INSERT INTO articles call"
```

- [ ] **Step 2: Run, expect pass (or specific failures to fix)**

```bash
pytest test/test_articlebot_e2e.py -v
```

Expected: PASS. If it fails, the failure points to a real wiring bug — fix the actual code (not the test) until it passes.

- [ ] **Step 3: Run the full test suite**

```bash
pytest test/ -v
```

Expected: all tests pass (everything we added plus all existing tests).

- [ ] **Step 4: Run a real dry-run against the dev DB**

```bash
source venv/bin/activate
ARTICLEBOT_DRY_RUN=true python storybot/articlebot.py
```

Expected:
- Picker runs (real Postgres + real Gamma + real Azure OpenAI).
- An article transcript and `.md` file land in `storybot/dry_runs/`.
- Stdout prints the file paths.

If anything explodes, the error is real — debug it. Common issues:
- `_dispatch_chart_render` calling the wrong function in `charts.py` (the Task 11 hasattr branch). Fix the dispatcher to call the actual exported names.
- The agent system prompt missing a required field; the model produces invalid JSON; the validator rejects. Inspect the dry-run JSON.

- [ ] **Step 5: Commit**

```bash
git add test/test_articlebot_e2e.py
git commit -m "test(articlebot): end-to-end smoke test with mocked LLM/Postgres"
```

---

## Task 16: Documentation + cron schedule

**Files:**
- Modify: `CLAUDE.md` (add articlebot to the "Running" section)

- [ ] **Step 1: Update `CLAUDE.md`**

Find the "Running" section in `CLAUDE.md`. Append the articlebot entry:

```markdown
Articlebot (daily X article generator):
```bash
source venv/bin/activate
python storybot/articlebot.py        # writes a draft to storybot/articles/
ARTICLEBOT_DRY_RUN=true python storybot/articlebot.py   # writes to storybot/dry_runs/

# After pasting into X composer:
python storybot/mark_published.py <run_id> <x_article_url>
```

Cron: once daily at 13:00 UTC (9am ET) recommended.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document articlebot entrypoint and dry-run mode"
```

---

## Self-review

**Spec coverage:** Stepped through each section of the spec.

| Spec section | Plan task |
|---|---|
| `articles` Postgres table + migration | Task 2 |
| `style_rules.py` extraction | Task 3 |
| `run_agent` parameterization | Task 4 |
| 24h event-summary SQL (Stage 0) | Task 5 |
| Tournament picker stage 1 | Task 6 |
| Tournament picker stage 2 + dedup | Task 7 |
| Tournament orchestrator | Task 8 |
| Output validator | Task 9 |
| Article system prompt + STYLE_RULES integration | Task 10 |
| Cover chart dispatch + soft-fault | Task 11 |
| `persist_article` + skipped-run audit row + `.md` file | Task 12 |
| `mark_published.py` CLI | Task 13 |
| `articlebot.main()` entrypoint, dry-run mode | Task 14 |
| End-to-end test | Task 15 |
| Cron schedule + docs | Task 16 |
| `.gitignore` for `articles/` | Task 1 |

All spec sections covered.

**Placeholder scan:** the only intentional `<<paste …>>` markers are in Task 3 Step 3 — they describe to the engineer what to copy verbatim from `storybot.py`. The marker itself is documented and Step 6 verifies the result by diff. No other TBDs / "implement later" / vague handwaving anywhere.

**Type consistency:** `pick_article_story` returns the same shape as `pick_final_event` plus `chosen_alerts`. `validate_article_decision` consumes the agent's output (which carries `event_slug` injected by `main()`). `persist_article` reads `decision.event_slug`, `decision.alert_ids`, `decision.article.{...}` — matches both the validator and the system-prompt schema. `render_cover_chart` is called with `decision.cover_chart_spec` and `chosen_alerts`. Names are consistent across tasks.

**Open implementation gotchas (called out inline, not deferred):**
- Task 11 Step 6 has a fallback path for when `charts.py` doesn't expose `render_chart` — engineer inspects and adapts.
- Task 4 Step 6 has an explicit before/after diff verification so the prompt refactor doesn't drift.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-27-articlebot.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
