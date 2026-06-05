# Articlebot Claude-Edit-Publish Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single command runs articlebot.py → claude -p editing pass → sync edits back to Postgres → publish_article.py, so a daily PolySpotter article ships with no manual review steps.

**Architecture:** Extend the existing `<run_id>.md` review file to include the tweet text in a delimited `## Tweet` section, making the .md the single human-editable surface. Add a new `sync_article_from_md.py` that parses the .md, validates with the existing `validate_article_decision`, and `UPDATE`s the `articles` row's `headline / subhead / body_markdown / tweet_text / word_count`. A shell script `run_full_workflow.sh` chains articlebot → claude -p → sync → publish, aborting on any failure before posting.

**Tech Stack:** Python 3.13, psycopg2, regex-based markdown parsing (no markdown library), bash (`set -euo pipefail`), Claude Code CLI (`claude -p`), pytest.

**Spec:** `docs/superpowers/specs/2026-05-06-articlebot-claude-edit-publish-workflow-design.md`

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `storybot/articlebot_storage.py` | Modify `_format_md_file` (lines 31-48) | Emit `## Tweet` section + tweet text bracketed by `---` rules |
| `storybot/sync_article_from_md.py` | Create | Parse `.md`, validate, UPDATE `articles` row. CLI entry point. |
| `storybot/run_full_workflow.sh` | Create (chmod +x) | Chain: articlebot → claude -p → sync → publish |
| `test/test_articlebot_storage.py` | Modify (extend `test_persist_article_writes_md_file_and_inserts_row`) | Cover new tweet section in .md output |
| `test/test_sync_article_from_md.py` | Create | Parser happy/error paths, validation, DB UPDATE, status guards |

No changes to: `articlebot.py`, `publish_article.py`, schema, frontend, validator.

---

## Task 1: Add tweet section to `_format_md_file`

**Files:**
- Modify: `storybot/articlebot_storage.py:31-48`
- Modify: `test/test_articlebot_storage.py:60-102`

The .md file currently contains the article body but no tweet, so any edits to the tweet have nowhere to live. We'll insert a `## Tweet` block between the body and the metadata footer, bracketed by `---` rules so the parser in Task 2 can locate it deterministically. The tweet block goes AFTER the article footer rule (preserving the article-then-footer structure readers already see) and BEFORE a second rule that opens the metadata block.

- [ ] **Step 1: Update the existing storage test to assert the new layout**

In `test/test_articlebot_storage.py`, replace lines 78-86 (the assertions inside `test_persist_article_writes_md_file_and_inserts_row` after `md_path = tmp_path / "abc12345.md"`) with:

```python
    md_path = tmp_path / "abc12345.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "# Headline" in content
    assert "Subhead" in content
    assert "abc12345.png" in content
    assert "https://polyspotter.com/market/x" in content
    assert "alert_ids: [11, 12]" in content
    # New: tweet section bracketed by --- rules
    assert "## Tweet" in content
    assert "An account up $2M just stacked $80k on a coin-flip." in content
    # The .md must contain exactly 2 horizontal rules: one before tweet,
    # one after tweet (opening the metadata footer). Anything else means
    # the parser in sync_article_from_md.py will reject the file.
    assert content.count("\n---\n") == 2
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_articlebot_storage.py::test_persist_article_writes_md_file_and_inserts_row -v`

Expected: FAIL on `assert "## Tweet" in content` (current `_format_md_file` does not emit a tweet section).

- [ ] **Step 3: Update `_format_md_file` to emit the tweet section**

Replace `storybot/articlebot_storage.py` lines 31-48 with:

```python
def _format_md_file(run_id: str, decision: dict, cover_path: str | None) -> str:
    """Build the paste-ready markdown file body.

    Layout (parsed back by sync_article_from_md.py):
        # {headline}

        *{subhead}*

        ![cover](<cover_basename>)   # only if cover_path

        {body_markdown}

        ---

        ## Tweet

        {tweet_text}

        ---

        run_id: ... | event_slug: ... | alert_ids: ...
        posted_url: <fill in after publishing>

    The two `---` rules and the `## Tweet` heading are load-bearing for the
    sync parser; do not change without updating sync_article_from_md.py.
    """
    article = decision.get("article") or {}
    headline = article.get("headline", "")
    subhead = article.get("subhead", "")
    body = article.get("body_markdown", "")
    tweet_text = decision.get("tweet_text") or ""
    event_slug = decision.get("event_slug") or ""
    alert_ids = decision.get("alert_ids") or []

    parts = [f"# {headline}", "", f"*{subhead}*", ""]
    if cover_path:
        parts.extend([f"![cover]({os.path.basename(cover_path)})", ""])
    parts.extend([body, "",
                  "---", "",
                  "## Tweet", "",
                  tweet_text, "",
                  "---", "",
                  f"run_id: {run_id} | event_slug: {event_slug} | "
                  f"alert_ids: {alert_ids}",
                  "posted_url: <fill in after publishing>",
                  ""])
    return "\n".join(parts)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_articlebot_storage.py -v`

Expected: PASS for both `test_persist_article_writes_md_file_and_inserts_row` and `test_record_skipped_run_inserts_minimal_row`.

- [ ] **Step 5: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/articlebot_storage.py test/test_articlebot_storage.py
git commit -m "$(cat <<'EOF'
articlebot: include tweet section in <run_id>.md draft file

Adds a ## Tweet block between the article body and the metadata footer,
bracketed by --- rules. This makes the .md file the single human-editable
surface for both article body and tweet — required for the upcoming
sync_article_from_md.py to push manual edits back into Postgres before
publish_article.py reads them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Build the markdown parser

**Files:**
- Create: `storybot/sync_article_from_md.py`
- Create: `test/test_sync_article_from_md.py`

The parser is a pure function: given the text of a `<run_id>.md` file, return a dict with `headline / subhead / body_markdown / tweet_text`. No I/O, no DB. Regex-based — the format is fully under our control (Task 1) so we don't need a markdown library.

- [ ] **Step 1: Write the failing happy-path test**

Create `test/test_sync_article_from_md.py`:

```python
"""Tests for sync_article_from_md: parser, validation, and DB UPDATE."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _build_md(*, headline="Headline", subhead="Subhead",
              body=None, tweet="Tweet body here", cover_basename="abc.png",
              run_id="abc12345", event_slug="some-event",
              alert_ids=(11, 12)) -> str:
    """Build a .md file matching the format _format_md_file emits."""
    if body is None:
        body = (
            "Opening hook.\n\n"
            "## The wallet\n\n"
            "Wallet paragraph.\n\n"
            "## The bet\n\n"
            "Bet paragraph.\n\n"
            "## What to watch\n\n"
            "Watch paragraph. https://polyspotter.com/market/x\n\n"
            "Closing line."
        )
    parts = [f"# {headline}", "", f"*{subhead}*", ""]
    if cover_basename:
        parts.extend([f"![cover]({cover_basename})", ""])
    parts.extend([body, "", "---", "", "## Tweet", "", tweet, "",
                  "---", "",
                  f"run_id: {run_id} | event_slug: {event_slug} | "
                  f"alert_ids: {list(alert_ids)}",
                  "posted_url: <fill in after publishing>", ""])
    return "\n".join(parts)


def test_parse_md_happy_path():
    import sync_article_from_md as sync

    md = _build_md()
    parsed = sync._parse_md(md)

    assert parsed["headline"] == "Headline"
    assert parsed["subhead"] == "Subhead"
    assert parsed["tweet_text"] == "Tweet body here"
    # Body should NOT contain the cover image line.
    assert "![cover]" not in parsed["body_markdown"]
    # Body SHOULD contain its own H2s and the polyspotter link.
    assert "## The wallet" in parsed["body_markdown"]
    assert "https://polyspotter.com/market/x" in parsed["body_markdown"]
    # Body should not contain the trailing --- or tweet section.
    assert "## Tweet" not in parsed["body_markdown"]
    assert "---" not in parsed["body_markdown"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py::test_parse_md_happy_path -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'sync_article_from_md'`.

- [ ] **Step 3: Create the parser module with `_parse_md`**

Create `storybot/sync_article_from_md.py`:

```python
"""Sync edits from storybot/articles/<run_id>.md back into the Postgres
articles row before publish_article.py runs.

The .md file is the single human-editable surface (article body + tweet
text). publish_article.py reads tweet_text from the DB and the on-site
article reads body_markdown from the DB, so without a sync step Claude's
edits to the .md never reach production. This module parses the .md,
re-validates against the same rules articlebot uses (length, banned
phrases, polyspotter link, etc.), and UPDATEs the row's headline /
subhead / body_markdown / tweet_text / word_count.

Usage:
    python storybot/sync_article_from_md.py <run_id>
"""
from __future__ import annotations

import os
import re
import sys

import psycopg2

from articlebot import validate_article_decision
from articlebot_storage import ARTICLES_DIR, _word_count
from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log


_HEADLINE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_SUBHEAD_RE = re.compile(r"^\*([^*].*?[^*])\*$", re.MULTILINE)
_RULE_RE = re.compile(r"^---$", re.MULTILINE)
_COVER_RE = re.compile(r"^!\[cover\]\([^)]+\)\s*$", re.MULTILINE)
_TWEET_HEADER_RE = re.compile(r"^## Tweet$", re.MULTILINE)


def _parse_md(md_text: str) -> dict:
    """Parse a <run_id>.md file produced by articlebot_storage._format_md_file.

    Returns {"headline", "subhead", "body_markdown", "tweet_text"}.
    Raises ValueError with a specific message on any structural violation.

    The format is under our control (see articlebot_storage._format_md_file).
    The two `---` rules and the `## Tweet` heading are load-bearing.
    """
    m_h = _HEADLINE_RE.search(md_text)
    if not m_h:
        raise ValueError("could not find headline (line starting with '# ')")
    headline = m_h.group(1).strip()

    m_s = _SUBHEAD_RE.search(md_text, m_h.end())
    if not m_s:
        raise ValueError("could not find subhead (line wrapped in *...*) after headline")
    subhead = m_s.group(1).strip()

    rules = list(_RULE_RE.finditer(md_text, m_s.end()))
    if len(rules) != 2:
        raise ValueError(
            f"expected exactly 2 horizontal rules ('---') after subhead, "
            f"found {len(rules)} — Claude may have introduced extra rules in body"
        )

    # Body: between subhead and first rule, with cover image line stripped.
    body_raw = md_text[m_s.end():rules[0].start()]
    body = _COVER_RE.sub("", body_raw).strip()
    if not body:
        raise ValueError("body section is empty between subhead and first '---'")

    # Tweet: between '## Tweet' header and second rule.
    tweet_section = md_text[rules[0].end():rules[1].start()]
    m_t = _TWEET_HEADER_RE.search(tweet_section)
    if not m_t:
        raise ValueError("could not find '## Tweet' heading in tweet section")
    tweet = tweet_section[m_t.end():].strip()
    if not tweet:
        raise ValueError("tweet text is empty after '## Tweet' heading")

    return {
        "headline": headline,
        "subhead": subhead,
        "body_markdown": body,
        "tweet_text": tweet,
    }
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py::test_parse_md_happy_path -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/sync_article_from_md.py test/test_sync_article_from_md.py
git commit -m "$(cat <<'EOF'
articlebot: add sync_article_from_md.py parser scaffold

Pure regex parser that turns a <run_id>.md file back into
{headline, subhead, body_markdown, tweet_text}. Format is under our
control (articlebot_storage._format_md_file); the two `---` rules and the
`## Tweet` heading are load-bearing. Validation and DB UPDATE land in
follow-up commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Cover parser error paths

**Files:**
- Modify: `test/test_sync_article_from_md.py`

The parser already raises `ValueError` for each malformed case. Lock that behavior in with explicit tests so future edits to `_parse_md` can't silently regress.

- [ ] **Step 1: Append the error-path tests**

Append to `test/test_sync_article_from_md.py`:

```python
def test_parse_md_missing_headline_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("# Headline", "Headline")
    with pytest.raises(ValueError, match="could not find headline"):
        sync._parse_md(md)


def test_parse_md_missing_subhead_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("*Subhead*", "Subhead")
    with pytest.raises(ValueError, match="could not find subhead"):
        sync._parse_md(md)


def test_parse_md_missing_tweet_section_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("## Tweet", "## Not Tweet")
    with pytest.raises(ValueError, match="could not find '## Tweet'"):
        sync._parse_md(md)


def test_parse_md_extra_rule_errors():
    """If Claude introduces a stray --- in the body, we must reject — the
    parser would otherwise mis-locate the body/tweet boundary."""
    import sync_article_from_md as sync
    import pytest

    body_with_rule = (
        "Opening.\n\n"
        "## The wallet\n\n"
        "Wallet line.\n\n---\n\n"   # stray rule inside body
        "## The bet\n\n"
        "Bet line.\n\n"
        "## What to watch\n\n"
        "Watch line. https://polyspotter.com/market/x"
    )
    md = _build_md(body=body_with_rule)
    with pytest.raises(ValueError, match="expected exactly 2 horizontal rules"):
        sync._parse_md(md)


def test_parse_md_empty_tweet_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md(tweet="")
    with pytest.raises(ValueError, match="tweet text is empty"):
        sync._parse_md(md)
```

- [ ] **Step 2: Run all parser tests and confirm they pass**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py -v`

Expected: 6 PASSED (1 happy + 5 error).

- [ ] **Step 3: Commit**

```bash
cd /home/bhavya/git/polybot
git add test/test_sync_article_from_md.py
git commit -m "$(cat <<'EOF'
articlebot: cover sync parser error paths with tests

Locks in ValueError messages for missing headline, missing subhead,
missing '## Tweet' heading, stray '---' inside body, and empty tweet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add validation wrapper

**Files:**
- Modify: `storybot/sync_article_from_md.py`
- Modify: `test/test_sync_article_from_md.py`

Reuse `validate_article_decision` from `articlebot.py` so Claude's edits face the same constraints articlebot's own output does. The validator expects a full decision dict; we synthesize one from the parsed .md plus the existing DB row's `cover_alt_text` and `alert_ids` (those are not in the .md and stay as-is).

- [ ] **Step 1: Write the failing validation tests**

Append to `test/test_sync_article_from_md.py`:

```python
def test_validate_synced_passes_for_clean_edit():
    import sync_article_from_md as sync

    parsed = {
        "headline": "Headline",
        "subhead": "Subhead",
        "body_markdown": (
            "Opening hook line that pulls the reader in.\n\n"
            "## The wallet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## The bet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## What to watch\n\n" + " ".join(["lorem"] * 170) + "\n\n"
            "Closing line. https://polyspotter.com/market/x"
        ),
        "tweet_text": "An account up $2M just stacked $80k on a coin-flip.",
    }
    ok, err = sync._validate_synced(
        parsed, alert_ids=[11, 12], cover_alt_text="alt"
    )
    assert ok, f"expected pass, got: {err}"
    assert err == ""


def test_validate_synced_fails_when_body_too_short():
    import sync_article_from_md as sync

    parsed = {
        "headline": "Headline",
        "subhead": "Subhead",
        "body_markdown": (
            "Tiny body.\n\n## A\n\nx.\n\n## B\n\ny.\n\n## C\n\n"
            "Close. https://polyspotter.com/market/x"
        ),
        "tweet_text": "tweet",
    }
    ok, err = sync._validate_synced(
        parsed, alert_ids=[11, 12], cover_alt_text="alt"
    )
    assert not ok
    assert "word count" in err
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py::test_validate_synced_passes_for_clean_edit test/test_sync_article_from_md.py::test_validate_synced_fails_when_body_too_short -v`

Expected: FAIL with `AttributeError: module 'sync_article_from_md' has no attribute '_validate_synced'`.

- [ ] **Step 3: Add `_validate_synced` to sync_article_from_md.py**

Append to `storybot/sync_article_from_md.py`:

```python
def _validate_synced(parsed: dict, *, alert_ids: list,
                     cover_alt_text: str | None) -> tuple[bool, str]:
    """Run the parsed .md through articlebot's existing validator by building
    a synthetic decision dict. cover_alt_text and alert_ids come from the DB
    row (they are not editable via the .md)."""
    decision = {
        "decision": "post",
        "article": {
            "headline": parsed["headline"],
            "subhead": parsed["subhead"],
            "body_markdown": parsed["body_markdown"],
            "cover_alt_text": cover_alt_text or "",
        },
        "tweet_text": parsed["tweet_text"],
        "alert_ids": list(alert_ids),
    }
    return validate_article_decision(decision)
```

- [ ] **Step 4: Run the validation tests and confirm they pass**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py -v`

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/sync_article_from_md.py test/test_sync_article_from_md.py
git commit -m "$(cat <<'EOF'
articlebot: add _validate_synced reusing validate_article_decision

Synthesizes a decision dict from the parsed .md + DB row's cover_alt_text
and alert_ids, then defers to articlebot.validate_article_decision so the
sync step enforces the same word-count, H2-count, polyspotter-link,
banned-phrase, and tweet-length rules articlebot's own output faces.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add DB sync function

**Files:**
- Modify: `storybot/sync_article_from_md.py`
- Modify: `test/test_sync_article_from_md.py`

Reads the existing row, parses the .md, validates, then UPDATEs. Aborts on missing row, status != 'draft', parse failure, or validation failure. Writes a `log()` event in each error path so cron logs make the failure mode obvious.

- [ ] **Step 1: Write the failing DB-sync tests**

Append to `test/test_sync_article_from_md.py`:

```python
from unittest.mock import MagicMock


def _patch_conn(monkeypatch, fetchone_row, *, expect_update=True):
    """Wire a fake psycopg2 connection. Returns (fake_conn, fake_cur)."""
    import sync_article_from_md as sync

    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = fetchone_row
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(sync, "_get_conn", lambda: fake_conn)
    return fake_conn, fake_cur


def test_sync_run_happy_path_updates_db(tmp_path, monkeypatch):
    import sync_article_from_md as sync

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    md_path = tmp_path / "abc12345.md"
    md_path.write_text(_build_md(
        headline="Edited headline",
        tweet="Edited tweet text here.",
        body=(
            "Opening hook line that pulls the reader in.\n\n"
            "## The wallet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## The bet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## What to watch\n\n" + " ".join(["lorem"] * 170) + "\n\n"
            "Closing line. https://polyspotter.com/market/x"
        ),
    ))

    # Existing draft row in DB
    fake_conn, fake_cur = _patch_conn(monkeypatch, (
        "abc12345", "draft", "alt text", [11, 12]
    ))

    sync.sync_run("abc12345")

    # Two cursor calls: SELECT, then UPDATE
    assert fake_cur.execute.call_count == 2
    select_sql = fake_cur.execute.call_args_list[0].args[0]
    update_sql, update_params = fake_cur.execute.call_args_list[1].args
    assert "SELECT" in select_sql.upper()
    assert "UPDATE articles" in update_sql
    assert "headline" in update_sql
    assert "tweet_text" in update_sql
    # Edited values land in params
    assert "Edited headline" in update_params
    assert "Edited tweet text here." in update_params
    assert "abc12345" in update_params
    fake_conn.commit.assert_called_once()


def test_sync_run_missing_row_aborts(tmp_path, monkeypatch):
    import sync_article_from_md as sync
    import pytest

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    (tmp_path / "abc12345.md").write_text(_build_md())
    _patch_conn(monkeypatch, None)  # SELECT returns no row

    with pytest.raises(SystemExit) as exc:
        sync.sync_run("abc12345")
    assert exc.value.code == 1


def test_sync_run_published_status_aborts(tmp_path, monkeypatch):
    import sync_article_from_md as sync
    import pytest

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    (tmp_path / "abc12345.md").write_text(_build_md())
    _patch_conn(monkeypatch, ("abc12345", "published", "alt", [11, 12]))

    with pytest.raises(SystemExit) as exc:
        sync.sync_run("abc12345")
    assert exc.value.code == 1


def test_sync_run_missing_md_file_aborts(tmp_path, monkeypatch):
    import sync_article_from_md as sync
    import pytest

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    # No .md file written
    _patch_conn(monkeypatch, ("abc12345", "draft", "alt", [11, 12]))

    with pytest.raises(SystemExit) as exc:
        sync.sync_run("abc12345")
    assert exc.value.code == 1


def test_sync_run_validation_failure_aborts_no_update(tmp_path, monkeypatch):
    """Body too short → validate_article_decision rejects → no UPDATE issued."""
    import sync_article_from_md as sync
    import pytest

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    md_path = tmp_path / "abc12345.md"
    md_path.write_text(_build_md(body=(
        "Tiny.\n\n## A\n\nx.\n\n## B\n\ny.\n\n## C\n\n"
        "Close. https://polyspotter.com/market/x"
    )))

    fake_conn, fake_cur = _patch_conn(
        monkeypatch, ("abc12345", "draft", "alt", [11, 12])
    )

    with pytest.raises(SystemExit) as exc:
        sync.sync_run("abc12345")
    assert exc.value.code == 1
    # SELECT only — no UPDATE
    assert fake_cur.execute.call_count == 1
    fake_conn.commit.assert_not_called()
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py -v`

Expected: 5 new tests FAIL with `AttributeError: module 'sync_article_from_md' has no attribute 'sync_run'` (or similar).

- [ ] **Step 3: Add `_get_conn` and `sync_run` to sync_article_from_md.py**

Append to `storybot/sync_article_from_md.py`:

```python
def _get_conn():
    """Return a Postgres connection. Hookable in tests via monkeypatch."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def sync_run(run_id: str) -> None:
    """Parse storybot/articles/<run_id>.md, validate, UPDATE the matching
    articles row. Calls sys.exit(1) on any failure (missing row, wrong
    status, missing file, parse error, validation error).

    Only fields editable via the .md are written: headline, subhead,
    body_markdown, tweet_text, word_count. cover_alt_text, alert_ids,
    event_slug, cover_bytes are left as-is.
    """
    md_path = os.path.join(ARTICLES_DIR, f"{run_id}.md")
    if not os.path.exists(md_path):
        log("sync_article_missing_md", run_id=run_id, md_path=md_path)
        print(f"error: no .md file at {md_path}", file=sys.stderr)
        sys.exit(1)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, status, cover_alt_text, alert_ids "
                "FROM articles WHERE run_id = %s LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            log("sync_article_no_row", run_id=run_id)
            print(f"error: no articles row for run_id={run_id!r}", file=sys.stderr)
            sys.exit(1)
        _, status, cover_alt_text, alert_ids = row
        if status != "draft":
            log("sync_article_wrong_status", run_id=run_id, status=status)
            print(
                f"error: row status={status!r}, expected 'draft'. "
                "Refusing to overwrite a published or skipped row.",
                file=sys.stderr,
            )
            sys.exit(1)

        with open(md_path) as f:
            md_text = f.read()

        try:
            parsed = _parse_md(md_text)
        except ValueError as exc:
            log("sync_article_parse_error", run_id=run_id, error=str(exc))
            print(f"error: failed to parse {md_path}: {exc}", file=sys.stderr)
            sys.exit(1)

        ok, err = _validate_synced(parsed, alert_ids=list(alert_ids or []),
                                   cover_alt_text=cover_alt_text)
        if not ok:
            log("sync_article_validation_error", run_id=run_id, error=err)
            print(f"error: edited article failed validation: {err}",
                  file=sys.stderr)
            sys.exit(1)

        word_count = _word_count(parsed["body_markdown"])

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE articles
                SET headline = %s,
                    subhead = %s,
                    body_markdown = %s,
                    tweet_text = %s,
                    word_count = %s
                WHERE run_id = %s AND status = 'draft'
                """,
                (parsed["headline"], parsed["subhead"],
                 parsed["body_markdown"], parsed["tweet_text"],
                 word_count, run_id),
            )
        conn.commit()
    finally:
        conn.close()

    log("sync_article_done", run_id=run_id, word_count=word_count,
        headline_chars=len(parsed["headline"]),
        tweet_chars=len(parsed["tweet_text"]))
    print(f"[sync] run_id={run_id} headline={parsed['headline']!r} "
          f"words={word_count} tweet_chars={len(parsed['tweet_text'])}")
```

- [ ] **Step 4: Run all tests and confirm they pass**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_sync_article_from_md.py -v`

Expected: 13 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/sync_article_from_md.py test/test_sync_article_from_md.py
git commit -m "$(cat <<'EOF'
articlebot: add sync_run() to push edited .md back into Postgres

Parses storybot/articles/<run_id>.md, runs the same validator as
articlebot's own output, then UPDATEs headline / subhead / body_markdown /
tweet_text / word_count on the matching draft row. Aborts (sys.exit(1))
on missing row, status != 'draft', missing file, parse error, or
validation error — pipefail in the workflow shell script then halts the
chain before publish_article runs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: CLI entry point

**Files:**
- Modify: `storybot/sync_article_from_md.py`

Wire up `python storybot/sync_article_from_md.py <run_id>` so the workflow shell script can call it.

- [ ] **Step 1: Append `main()` and `__main__` block**

Append to `storybot/sync_article_from_md.py`:

```python
def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: sync_article_from_md.py <run_id>", file=sys.stderr)
        return 2
    sync_run(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Smoke-test the CLI with a missing run_id**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && python storybot/sync_article_from_md.py 2>&1; echo "exit=$?"`

Expected: prints `usage: sync_article_from_md.py <run_id>` and exits 2.

- [ ] **Step 3: Smoke-test with an obviously-fake run_id**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && python storybot/sync_article_from_md.py nonexistent_xyz 2>&1; echo "exit=$?"`

Expected: prints `error: no .md file at .../storybot/articles/nonexistent_xyz.md` and exits 1.

- [ ] **Step 4: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/sync_article_from_md.py
git commit -m "$(cat <<'EOF'
articlebot: add CLI entry to sync_article_from_md.py

usage: python storybot/sync_article_from_md.py <run_id>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Workflow shell script

**Files:**
- Create: `storybot/run_full_workflow.sh`

The orchestrator. Runs articlebot, parses run_id, invokes `claude -p` non-interactively to edit the .md, syncs, publishes. `set -euo pipefail` ensures any failure aborts before posting a tweet.

- [ ] **Step 1: Create the script**

Create `storybot/run_full_workflow.sh`:

```bash
#!/usr/bin/env bash
# Chained articlebot → claude edit → sync → publish workflow.
#
# 1. Runs `python storybot/articlebot.py` to produce a draft.
# 2. If a draft was produced (skip path produces no draft and exits the
#    workflow cleanly), invokes `claude -p` to edit the .md in-place.
# 3. Runs `python storybot/sync_article_from_md.py <run_id>` to push the
#    edits into Postgres (validates with articlebot's own validator).
# 4. Runs `python storybot/publish_article.py <run_id>` to post the tweet
#    and flip the row to 'published'.
#
# Any non-zero exit in steps 1, 3, or 4 aborts via set -e + pipefail
# before a tweet is posted. Step 2 (`claude -p`) failure also aborts —
# the draft is left in DB as 'draft' so the user can investigate, fix,
# and re-run sync + publish manually.
set -euo pipefail

# Always run from project root so `@storybot/...` mentions in the prompt
# resolve correctly inside Claude.
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source venv/bin/activate

echo "[workflow] running articlebot.py"
output=$(python storybot/articlebot.py 2>&1 | tee /dev/tty)

# `[articlebot] draft run_id=<hex>` is printed only on the post path.
# Skip / error paths produce no such line — the workflow exits cleanly.
run_id=$(echo "$output" \
    | grep -oP '\[articlebot\] draft run_id=\K[a-f0-9]+' || true)

if [[ -z "$run_id" ]]; then
    echo "[workflow] no draft produced (articlebot skipped or errored). Stopping."
    exit 0
fi

echo "[workflow] draft run_id=$run_id — invoking claude to edit"

prompt="can you look at $run_id run of the @storybot/articlebot.py in folder @storybot/articles/ and tell me if there are any improvements we can make to the article there. make your edits to the article directly and improve both the article and the tweet. I want to be able to run @storybot/publish_article.py with this id directly after you are done with your edits"

claude -p "$prompt" --dangerously-skip-permissions

echo "[workflow] syncing edited .md back to Postgres"
python storybot/sync_article_from_md.py "$run_id"

echo "[workflow] publishing"
python storybot/publish_article.py "$run_id"

echo "[workflow] done. run_id=$run_id"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x /home/bhavya/git/polybot/storybot/run_full_workflow.sh`

- [ ] **Step 3: Smoke-test the no-draft path under DRY_RUN**

Note: a fully end-to-end smoke test would burn LLM credits and post a tweet. We just exercise the bash plumbing. Confirm the script parses correctly and the no-draft branch exits 0:

```bash
cd /home/bhavya/git/polybot
bash -n storybot/run_full_workflow.sh && echo "syntax-ok"
```

Expected: prints `syntax-ok`.

- [ ] **Step 4: Commit**

```bash
cd /home/bhavya/git/polybot
git add storybot/run_full_workflow.sh
git commit -m "$(cat <<'EOF'
articlebot: add run_full_workflow.sh chaining draft → claude edit → publish

Single command runs articlebot.py, captures the draft run_id, invokes
`claude -p` non-interactively with --dangerously-skip-permissions to edit
the .md in place, then runs sync_article_from_md.py and publish_article.py.

set -euo pipefail aborts the chain on any failure before a tweet is
posted. Skip path (no draft produced) exits 0 cleanly with a log line.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Final integration check

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full storybot test suite**

Run: `cd /home/bhavya/git/polybot && source venv/bin/activate && pytest test/test_articlebot_storage.py test/test_articlebot_validation.py test/test_articlebot_picker.py test/test_articlebot_e2e.py test/test_publish_article.py test/test_sync_article_from_md.py -v`

Expected: ALL PASS. The articlebot_e2e and articlebot_storage tests now exercise the new tweet section in the .md output.

- [ ] **Step 2: Manually verify end-to-end with DRY_RUN**

Note: this requires real Azure / Polymarket / DB credentials in `.env`. Skip if those aren't available; the unit tests cover the new code paths.

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
DRY_RUN=true python storybot/articlebot.py
```

Expected: produces a `storybot/dry_runs/<run_id>.md` containing a `## Tweet` section bracketed by two `---` rules. No DB writes (DRY_RUN).

- [ ] **Step 3: No commit needed**

Verification only.

---

## Self-review

**1. Spec coverage:**

| Spec section | Implemented in |
|---|---|
| Tweet section in .md | Task 1 |
| Sync script: parser | Tasks 2, 3 |
| Sync script: validation reuse | Task 4 |
| Sync script: DB UPDATE + status guard | Task 5 |
| Sync script: CLI | Task 6 |
| Shell script chaining | Task 7 |
| Error handling table (all rows) | Tasks 5 (sync errors), 7 (shell pipefail), 7 (no-draft path) |
| Tests: roundtrip storage + sync edge cases | Tasks 1, 2, 3, 4, 5 |

No gaps.

**2. Placeholder scan:** No "TBD", no "implement later", no "appropriate error handling" — every step has either explicit code or explicit commands with expected output.

**3. Type consistency:**

- Parser returns dict with keys `headline / subhead / body_markdown / tweet_text` (Tasks 2, 3, 4, 5 all read these keys).
- `_validate_synced` signature: `(parsed: dict, *, alert_ids: list, cover_alt_text: str | None) -> tuple[bool, str]` — used identically in Task 4's tests and Task 5's `sync_run`.
- `sync_run(run_id: str) -> None` — used by Task 5 tests, Task 6 CLI, Task 7 shell.
- `_get_conn()` defined in Task 5, monkeypatched in Task 5 tests via `_patch_conn`.

Consistent across tasks.
