# Twitter pipeline claude-edit-publish workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `twitter_pipeline.py` into a draft-only step, add a `publish_tweet.py` poster, and rewrite `run_twitter_pipeline_loop.sh` to chain draft → `claude -p` edit → publish on every iteration.

**Architecture:** `twitter_pipeline.py` stops posting; it writes the tweet body to `storybot/twitter_drafts/<run_id>.txt` and augments the existing `storybot/live_runs/twitter_pipeline_<run_id>.json` transcript with a `publish_meta` block (alert_ids, chart_type, target_alert_id, chart_png_path, recent_openers, recent_tweets). A new `publish_tweet.py` loads the draft `.txt`, re-runs `validate_tweet`, builds twitter clients, calls `post_tweet`, then `record_tweet`. The loop shell greps the pipeline's stdout for `[twitter_pipeline] draft run_id=<hex>`, invokes `claude -p` with a prompt pointing at the `.txt` and transcript, and on claude exit-0 runs `publish_tweet.py`. Any sub-step failure logs and falls through to `sleep` — the outer loop never aborts.

**Tech Stack:** Python 3.13, pytest, bash (screen), tweepy (already wired via `tweet_utils.py`), psycopg2 (already wired via `record_tweet`).

**Reference files (read-only context for the implementer):**
- `storybot/articlebot.py`, `storybot/publish_article.py`, `storybot/sync_article_from_md.py` — the article-workflow analog this is modeled on
- `storybot/run_full_workflow.sh` — the shell pattern this loop mirrors
- `test/test_publish_article.py` — the test pattern `test_publish_tweet.py` mirrors
- Spec: `docs/superpowers/specs/2026-05-10-twitter-pipeline-claude-edit-publish-workflow-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `storybot/twitter_pipeline.py` | Modify | Stop posting. Persist tweet body to disk. Add `publish_meta` to transcript. Print `draft run_id=` marker. |
| `storybot/publish_tweet.py` | **Create** | Load draft + metadata, re-validate, post, record. The only path that posts. |
| `storybot/run_twitter_pipeline_loop.sh` | Modify | Chain pipeline → claude → publish per iteration. Never abort on sub-step failure. |
| `test/test_publish_tweet.py` | **Create** | Happy path + missing-draft + missing-transcript + validation-fail + no-chart-png + record-fail-soft-fails. |
| `test/test_twitter_pipeline_draft.py` | **Create** | `_write_draft` writes to correct dir under live and DRY_RUN. |

---

## Task 1: Add draft-writing helper to `twitter_pipeline.py`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (add helpers near `_dump_transcript` at line ~1778)
- Create: `test/test_twitter_pipeline_draft.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_twitter_pipeline_draft.py`:

```python
"""Tests for the draft-writing helper in twitter_pipeline.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_write_draft_live_writes_to_twitter_drafts_dir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(tmp_path / "live"))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", False)

    tp._write_draft("abc12345", "Hello, world.\n")

    written = (tmp_path / "live" / "abc12345.txt").read_text()
    assert written == "Hello, world.\n"
    assert not (tmp_path / "dry" / "abc12345.txt").exists()


def test_write_draft_dry_run_writes_to_dry_runs_subdir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(tmp_path / "live"))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", True)

    tp._write_draft("abc12345", "Dry run tweet body")

    written = (tmp_path / "dry" / "abc12345.txt").read_text()
    assert written == "Dry run tweet body"
    assert not (tmp_path / "live" / "abc12345.txt").exists()


def test_write_draft_creates_parent_dir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    target = tmp_path / "nested" / "twitter_drafts"
    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(target))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", False)

    tp._write_draft("xyz98765", "body")

    assert (target / "xyz98765.txt").read_text() == "body"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_draft.py -v`
Expected: FAIL with `AttributeError: module 'twitter_pipeline' has no attribute '_TWITTER_DRAFTS_DIR'` (or similar — the helpers don't exist yet).

- [ ] **Step 3: Add helpers in `twitter_pipeline.py`**

Add these constants near the existing `_LIVE_RUN_DIR` / `_RUN_OUTPUT_DIR` block (lines ~32–34) so they sit next to the other path constants:

```python
_TWITTER_DRAFTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "twitter_drafts"
)
_DRY_RUN_TWITTER_DRAFTS_DIR = os.path.join(
    _DRY_RUN_DIR, "twitter_drafts"
)
```

Add the helper directly above `_dump_transcript` (line ~1778):

```python
def _write_draft(run_id: str, tweet: str) -> str:
    """Persist the drafted tweet body so publish_tweet.py can pick it up.

    Returns the absolute path written. Picks dry_runs/twitter_drafts/ when
    DRY_RUN, else twitter_drafts/. Creates the parent dir if missing.
    """
    out_dir = _DRY_RUN_TWITTER_DRAFTS_DIR if DRY_RUN else _TWITTER_DRAFTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{run_id}.txt")
    with open(path, "w") as f:
        f.write(tweet)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_twitter_pipeline_draft.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_draft.py
git commit -m "feat(twitter): add _write_draft helper for pre-publish persistence"
```

---

## Task 2: Drop the post block from `twitter_pipeline.py` and persist draft + publish_meta

**Files:**
- Modify: `storybot/twitter_pipeline.py:1799–1804` (imports) and `storybot/twitter_pipeline.py:2008–2056` (post block + run_end)

This task removes the posting code path entirely and replaces it with the draft-persistence path. It is the largest single change in the plan. No new test — Task 1 covers `_write_draft`; the rest is removal + a print statement.

- [ ] **Step 1: Update the local `tweet_utils` import in `main()` (line ~1799)**

Current:

```python
    from tweet_utils import (
        _build_twitter_api_v1, _build_twitter_client,
        fetch_recent_tweet_openers, fetch_recent_tweets,
        filter_posted_alerts, post_tweet, prepare_chart_grid, record_tweet,
        strip_polyspotter_url,
    )
```

Replace with:

```python
    from tweet_utils import (
        fetch_recent_tweet_openers, fetch_recent_tweets,
        filter_posted_alerts, prepare_chart_grid, strip_polyspotter_url,
    )
```

Rationale: `_build_twitter_api_v1`, `_build_twitter_client`, `post_tweet`, `record_tweet` are no longer used by this module — they move to `publish_tweet.py`.

- [ ] **Step 2: Replace the post block (lines ~2008–2056) with the draft-persistence block**

Current block to delete (the "Post" section in `main()`, starting at the `_dump_transcript(run_id, transcript)` call):

```python
    _dump_transcript(run_id, transcript)

    # Post
    try:
        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
        tweet_id = post_tweet(
            tweet, twitter_client=twitter_client, twitter_api_v1=twitter_api_v1,
            media_png=chart_png, dry_run=DRY_RUN,
        )
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    log("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=pick["alert_ids"],
        tweet_length=len(tweet))
    print(f"\n--- Tweet ({len(tweet)} chars) ---\n{tweet}\n", flush=True)

    if DRY_RUN:
        try:
            answer = input("\nPost this tweet for real? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
                elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
            return 0
        try:
            tweet_id = post_tweet(
                tweet, twitter_client=twitter_client, twitter_api_v1=twitter_api_v1,
                media_png=chart_png, dry_run=False,
            )
        except Exception as exc:
            log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
            return 1
        log("posted_after_confirm", run_id=run_id, tweet_id=tweet_id,
            alert_ids=pick["alert_ids"], tweet_length=len(tweet))

    try:
        record_tweet([int(i) for i in pick["alert_ids"]], tweet_id, tweet)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0
```

Replacement block (everything from `_dump_transcript` onward):

```python
    # publish_meta — everything publish_tweet.py needs to post without
    # recomputing what the pipeline already decided. Keeping it inside the
    # transcript JSON (rather than a separate file) means there is one
    # source-of-truth artifact per run that claude can read for context.
    chart_png_path: str | None = None
    if chart_png is not None:
        chart_png_path = os.path.join(
            _RUN_OUTPUT_DIR, f"twitter_pipeline_{run_id}.png"
        )
    transcript["publish_meta"] = {
        "alert_ids": pick["alert_ids"],
        "chart_type": chart_pick["chart_type"],
        "target_alert_id": target_alert_id,
        "chart_png_path": chart_png_path,
        "recent_openers": recent_openers,
        "recent_tweets": recent_tweets,
    }

    _dump_transcript(run_id, transcript)

    draft_path = _write_draft(run_id, tweet)
    log("draft_written", run_id=run_id, path=draft_path, tweet_length=len(tweet))
    print(f"[twitter_pipeline] draft run_id={run_id}", flush=True)
    print(f"\n--- Tweet ({len(tweet)} chars) ---\n{tweet}\n", flush=True)

    log("run_end", run_id=run_id, drafted=True, run_id_marker=run_id,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0
```

Three behaviors changed:
- No twitter client, no `post_tweet`, no `record_tweet` — all moved to `publish_tweet.py`.
- No interactive `input()` DRY_RUN confirm — the path is gone. DRY_RUN now only affects which `twitter_drafts/` subdir the `.txt` lands in (and via `_dump_transcript`, where the transcript JSON lands). To "preview" you read the file from disk.
- The `[twitter_pipeline] draft run_id=<hex>` marker is printed on stdout for the loop shell to grep.

- [ ] **Step 3: Run the existing twitter_pipeline tests to confirm no regression**

Run: `pytest test/test_twitter_pipeline_facts_bundle.py test/test_twitter_pipeline_grid.py test/test_twitter_pipeline_pick_chart.py test/test_twitter_pipeline_pick_event.py test/test_twitter_pipeline_quality_floor.py test/test_twitter_pipeline_validation.py test/test_twitter_pipeline_draft.py -v`

Expected: all PASS. None of these tests exercise `main()`'s post block, so they should be unaffected. If anything fails, it's an import or symbol-removal error — re-check Step 1's import list.

- [ ] **Step 4: Smoke check that the module still imports cleanly**

Run: `python -c "import sys; sys.path.insert(0, 'storybot'); import twitter_pipeline; print('ok')"`
Expected: prints `ok`. If it raises, an import was over-trimmed in Step 1.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py
git commit -m "refactor(twitter): drop post block; persist draft + publish_meta instead"
```

---

## Task 3: Create `storybot/publish_tweet.py`

**Files:**
- Create: `storybot/publish_tweet.py`
- Create: `test/test_publish_tweet.py`

- [ ] **Step 1: Write the failing tests**

Create `test/test_publish_tweet.py`:

```python
"""Tests for storybot/publish_tweet.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


_TWEET_BODY = "A 31-day-old wallet just dropped $80k at 12c on a coin-flip."


def _write_fixture_files(tmp_path, run_id, *, tweet=_TWEET_BODY,
                         publish_meta=None, write_chart=True):
    """Lay out a draft .txt + transcript .json (+ optional chart .png) on
    disk under tmp_path and return the dir paths so the test can monkeypatch
    publish_tweet's constants to point here."""
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()

    (drafts_dir / f"{run_id}.txt").write_text(tweet)

    chart_path = None
    if write_chart:
        chart_path = str(live_dir / f"twitter_pipeline_{run_id}.png")
        Path(chart_path).write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")

    pm = publish_meta if publish_meta is not None else {
        "alert_ids": [42, 43],
        "chart_type": "fresh_wallet_card",
        "target_alert_id": 42,
        "chart_png_path": chart_path,
        "recent_openers": [],
        "recent_tweets": [],
    }
    transcript = {"run_id": run_id, "stages": {}, "publish_meta": pm}
    (live_dir / f"twitter_pipeline_{run_id}.json").write_text(json.dumps(transcript))

    return drafts_dir, live_dir


def _patch_publisher(monkeypatch, drafts_dir, live_dir):
    import publish_tweet as pt
    monkeypatch.setattr(pt, "TWITTER_DRAFTS_DIR", str(drafts_dir))
    monkeypatch.setattr(pt, "LIVE_RUNS_DIR", str(live_dir))
    return pt


def test_publish_tweet_happy_path_posts_and_records(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())

    posted = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        posted["text"] = text
        posted["media_png"] = media_png
        posted["dry_run"] = dry_run
        return "1234567890"
    monkeypatch.setattr(pt, "post_tweet", fake_post_tweet)

    recorded = {}
    def fake_record_tweet(alert_ids, tweet_id, tweet_text):
        recorded["alert_ids"] = alert_ids
        recorded["tweet_id"] = tweet_id
        recorded["tweet_text"] = tweet_text
    monkeypatch.setattr(pt, "record_tweet", fake_record_tweet)

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert posted["text"] == _TWEET_BODY
    assert posted["media_png"] == b"\x89PNG\r\n\x1a\nfakebytes"
    assert posted["dry_run"] is False
    assert recorded == {
        "alert_ids": [42, 43],
        "tweet_id": "1234567890",
        "tweet_text": _TWEET_BODY,
    }


def test_publish_tweet_missing_draft_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["nodraft9"])
    assert rc == 1


def test_publish_tweet_missing_transcript_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    (drafts_dir / "abc12345.txt").write_text(_TWEET_BODY)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["abc12345"])
    assert rc == 1


def test_publish_tweet_missing_publish_meta_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    (drafts_dir / "abc12345.txt").write_text(_TWEET_BODY)
    (live_dir / "twitter_pipeline_abc12345.json").write_text(
        json.dumps({"run_id": "abc12345", "stages": {}})  # no publish_meta
    )
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["abc12345"])
    assert rc == 1


def test_publish_tweet_validation_failure_does_not_post(tmp_path, monkeypatch):
    # Tweet over 280 chars — validate_tweet should reject.
    long_tweet = "x" * 281
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", tweet=long_tweet, write_chart=False,
    )
    # Update the transcript's chart_png_path to null since we didn't write one.
    transcript_path = live_dir / "twitter_pipeline_abc12345.json"
    transcript = json.loads(transcript_path.read_text())
    transcript["publish_meta"]["chart_png_path"] = None
    transcript_path.write_text(json.dumps(transcript))

    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    called = {"post": False}
    monkeypatch.setattr(pt, "post_tweet",
                        lambda *a, **kw: called.__setitem__("post", True) or "x")
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())

    rc = pt.main(["abc12345"])
    assert rc == 1
    assert called["post"] is False


def test_publish_tweet_no_chart_png_path_posts_without_media(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", write_chart=False,
    )
    transcript_path = live_dir / "twitter_pipeline_abc12345.json"
    transcript = json.loads(transcript_path.read_text())
    transcript["publish_meta"]["chart_png_path"] = None
    transcript_path.write_text(json.dumps(transcript))

    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    v1_built = {"built": False}
    def fake_v1():
        v1_built["built"] = True
        return MagicMock()
    monkeypatch.setattr(pt, "_build_twitter_api_v1", fake_v1)

    posted = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        posted["media_png"] = media_png
        posted["v1"] = twitter_api_v1
        return "1234567890"
    monkeypatch.setattr(pt, "post_tweet", fake_post_tweet)
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert posted["media_png"] is None
    assert posted["v1"] is None
    assert v1_built["built"] is False


def test_publish_tweet_record_failure_is_soft_fail(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")
    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(pt, "record_tweet", boom)

    rc = pt.main(["abc12345"])
    assert rc == 0  # tweet is live; record failure must not exit non-zero


def test_publish_tweet_bad_argv_returns_2(monkeypatch):
    import publish_tweet as pt
    assert pt.main([]) == 2
    assert pt.main(["a", "b"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_publish_tweet.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'publish_tweet'`.

- [ ] **Step 3: Create `storybot/publish_tweet.py`**

```python
"""Publish a drafted twitter_pipeline tweet.

Reads the draft .txt that twitter_pipeline.py left on disk, re-runs
validate_tweet (defensive — claude may have edited it), then posts the
tweet (with chart png if present) and records it in tweeted_alerts.

Usage:
    python storybot/publish_tweet.py <run_id>

Exit codes:
    0  posted (record may have soft-failed but tweet is live)
    1  no draft / no transcript / missing publish_meta / validation failed /
       post raised
    2  bad argv
"""
from __future__ import annotations

import json
import os
import sys

# Make project root importable so `import db` and friends work when this
# script runs directly via cron / the loop shell.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


_STORYBOT_DIR = os.path.dirname(os.path.abspath(__file__))
TWITTER_DRAFTS_DIR = os.path.join(_STORYBOT_DIR, "twitter_drafts")
LIVE_RUNS_DIR = os.path.join(_STORYBOT_DIR, "live_runs")

_REQUIRED_PUBLISH_META_KEYS = (
    "alert_ids", "chart_type", "target_alert_id", "chart_png_path",
)


# Imported at module level (not inside main) so tests can monkeypatch these.
from bot_utils import log
from twitter_pipeline import validate_tweet
from tweet_utils import (
    _build_twitter_api_v1, _build_twitter_client, post_tweet, record_tweet,
)


def _draft_path(run_id: str) -> str:
    return os.path.join(TWITTER_DRAFTS_DIR, f"{run_id}.txt")


def _transcript_path(run_id: str) -> str:
    return os.path.join(LIVE_RUNS_DIR, f"twitter_pipeline_{run_id}.json")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: publish_tweet.py <run_id>", file=sys.stderr)
        return 2
    run_id = argv[0]

    log("publish_tweet_start", run_id=run_id)

    draft_path = _draft_path(run_id)
    if not os.path.exists(draft_path):
        print(f"error: no draft found at {draft_path}", file=sys.stderr)
        log("publish_tweet_no_draft", run_id=run_id, path=draft_path)
        return 1
    with open(draft_path) as f:
        tweet_text = f.read().rstrip("\n")

    transcript_path = _transcript_path(run_id)
    if not os.path.exists(transcript_path):
        print(f"error: no transcript at {transcript_path}", file=sys.stderr)
        log("publish_tweet_no_transcript", run_id=run_id, path=transcript_path)
        return 1
    with open(transcript_path) as f:
        transcript = json.load(f)

    pm = transcript.get("publish_meta")
    if not isinstance(pm, dict):
        print("error: transcript missing publish_meta block", file=sys.stderr)
        log("publish_tweet_no_publish_meta", run_id=run_id)
        return 1
    missing = [k for k in _REQUIRED_PUBLISH_META_KEYS if k not in pm]
    if missing:
        print(f"error: publish_meta missing keys: {missing}", file=sys.stderr)
        log("publish_tweet_publish_meta_missing_keys",
            run_id=run_id, missing=missing)
        return 1
    alert_ids = pm["alert_ids"]
    chart_png_path = pm["chart_png_path"]

    chart_png: bytes | None = None
    if chart_png_path:
        if not os.path.exists(chart_png_path):
            print(
                f"error: chart_png_path in publish_meta does not exist: "
                f"{chart_png_path}",
                file=sys.stderr,
            )
            log("publish_tweet_chart_png_missing",
                run_id=run_id, path=chart_png_path)
            return 1
        with open(chart_png_path, "rb") as f:
            chart_png = f.read()

    ok, err = validate_tweet(tweet_text)
    if not ok:
        print(f"error: validate_tweet failed: {err}", file=sys.stderr)
        log("publish_tweet_validation_error", run_id=run_id, error=err)
        return 1

    twitter_client = _build_twitter_client()
    twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
    try:
        tweet_id = post_tweet(
            tweet_text,
            twitter_client=twitter_client,
            twitter_api_v1=twitter_api_v1,
            media_png=chart_png,
            dry_run=False,
        )
    except Exception as exc:
        log("publish_tweet_post_error",
            run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        print(
            f"error: post_tweet raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    log("publish_tweet_posted",
        run_id=run_id, tweet_id=tweet_id, alert_ids=alert_ids,
        tweet_length=len(tweet_text))

    try:
        record_tweet([int(i) for i in alert_ids], tweet_id, tweet_text)
    except Exception as exc:
        # Tweet is already live; failing to record is a soft fail so the
        # shell loop doesn't treat this as a publish failure.
        log("publish_tweet_record_error",
            run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("publish_tweet_done",
            run_id=run_id, tweet_id=tweet_id, recorded=False)
        print(
            f"[publish_tweet] posted tweet_id={tweet_id} but record_tweet "
            f"raised — dedup may miss this on the next run.",
            file=sys.stderr,
        )
        return 0

    log("publish_tweet_done",
        run_id=run_id, tweet_id=tweet_id, recorded=True)
    print(f"[publish_tweet] published run_id={run_id} tweet_id={tweet_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_publish_tweet.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/publish_tweet.py test/test_publish_tweet.py
git commit -m "feat(twitter): add publish_tweet.py — re-validate, post, record"
```

---

## Task 4: Rewrite `storybot/run_twitter_pipeline_loop.sh`

**Files:**
- Modify: `storybot/run_twitter_pipeline_loop.sh` (whole file)

Shell scripts don't get a pytest harness — verification is by reading and running the script. The replacement preserves the outer loop (signal trap, log, sleep, `screen` ergonomics) and adds the draft → claude → publish chain inside the body.

- [ ] **Step 1: Replace the file contents**

Overwrite `storybot/run_twitter_pipeline_loop.sh` with:

```bash
#!/usr/bin/env bash
# Runs storybot/twitter_pipeline.py every 5 hours, then has Claude Code
# review/edit the draft, then publishes via storybot/publish_tweet.py.
# Five hours of wake-up gap yields ~4-5 wake-ups per day; with the picker
# skipping duplicate or weak-story windows, the actual ship rate lands in
# the 3-5 tweets/day target.
# Intended to be launched inside a screen/tmux session:
#     screen -S twitter
#     ./storybot/run_twitter_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r twitter
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline. Note
# that DRY_RUN drafts land in storybot/dry_runs/twitter_drafts/ and are
# NOT picked up by publish_tweet.py — the chain stops after drafting.

set -u

INTERVAL_SECONDS="${INTERVAL_SECONDS:-18000}"  # 5 hours

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/storybot/logs"
LOG_FILE="$LOG_DIR/twitter_pipeline.log"

mkdir -p "$LOG_DIR"

# shellcheck disable=SC1091
source "$PROJECT_ROOT/venv/bin/activate"

cd "$PROJECT_ROOT"

# Make Ctrl-C terminate the loop cleanly instead of just the current python run.
trap 'echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] loop interrupted, exiting" | tee -a "$LOG_FILE"; exit 0' INT TERM

while true; do
    {
        echo ""
        echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    } | tee -a "$LOG_FILE"

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    # `output` captures stdout so we can grep the draft run_id marker.
    output=$(stdbuf -oL -eL python storybot/twitter_pipeline.py 2>&1 | tee -a "$LOG_FILE")
    pipeline_status="${PIPESTATUS[0]}"

    if [[ "$pipeline_status" -ne 0 ]]; then
        echo "[loop] twitter_pipeline.py exited $pipeline_status — skipping this iteration" | tee -a "$LOG_FILE"
    else
        run_id=$(echo "$output" \
            | grep -oP '\[twitter_pipeline\] draft run_id=\K[a-f0-9]+' || true)
        if [[ -z "$run_id" ]]; then
            echo "[loop] no draft produced (pipeline skipped). Sleeping." | tee -a "$LOG_FILE"
        else
            echo "[loop] draft run_id=$run_id — invoking claude to edit" | tee -a "$LOG_FILE"

            prompt="Review and edit the twitter pipeline draft with run_id=$run_id.

The draft tweet is at @storybot/twitter_drafts/$run_id.txt — edit this file directly. Keep it postable: the workflow runs @storybot/publish_tweet.py right after you finish and will re-validate before posting. If the draft is fine, leave it alone; if it has problems, fix them.

The full transcript with every stage's input and output (event picker, data bundle, facts bundle, chart picker, writer attempts, recent tweets the picker saw) is at @storybot/live_runs/twitter_pipeline_$run_id.json — open it whenever you need to verify a claim in the tweet.

The chart that will be attached is at @storybot/live_runs/twitter_pipeline_$run_id.png — open it to confirm the tweet's hook actually anchors to what the image shows.

Fix these before finishing:

1. FACT FIDELITY. Every concrete number in the tweet (dollar amounts, win-loss tuples like 'X-Y', percentages, ROI %, cents prices, cluster sizes, minutes-to-resolution) must be reachable in the transcript's facts_bundle, trades, or chosen_alerts. The bot has a known habit of inflating wallet records and inventing cluster sizes. If you can't verify a number in the transcript, either replace it with the actual value from there or rewrite the line to drop the specific stat.

2. CHART ANCHOR. The tweet's lede must match the chart that will be attached. transcript.stages.3_chart_picker.hook_anchor tells you what the chart was chosen to anchor — the tweet's opening must reference the same subject (the specific wallet, the specific price move, the specific cluster). Don't open with an unrelated angle.

3. LENGTH AND BANNED PHRASES. publish_tweet.py re-runs validate_tweet, which rejects: tweet length > TWEET_MAX_CHARS (twitter-counted, not raw len) and any banned phrase from _BANNED_TWEET_PHRASES (see @storybot/tweet_utils.py for the exact list). Stay under length and avoid the banned phrasing.

4. OPENER FRESHNESS. The transcript's publish_meta.recent_openers field has the last 5 tweet openers we've shipped. The first ~6 words of this tweet must not be a near-paraphrase of any of them — we don't want a feed that all sounds the same.

Refer to validate_tweet and validate_tweet_anchor in @storybot/twitter_pipeline.py for the exact validator rules if anything is unclear. publish_tweet.py runs immediately after you finish, so the tweet must be in a postable state."

            if claude -p "$prompt" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
                if python storybot/publish_tweet.py "$run_id" 2>&1 | tee -a "$LOG_FILE"; then
                    echo "[loop] published run_id=$run_id" | tee -a "$LOG_FILE"
                else
                    echo "[loop] publish_tweet failed for run_id=$run_id — draft preserved on disk" | tee -a "$LOG_FILE"
                fi
            else
                echo "[loop] claude edit failed for run_id=$run_id — not publishing. Draft remains on disk." | tee -a "$LOG_FILE"
            fi
        fi
    fi

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (pipeline_exit=$pipeline_status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    sleep "$INTERVAL_SECONDS"
done
```

Key invariants preserved/changed:
- Same `INTERVAL_SECONDS`, same log file, same `screen`-friendly buffering, same SIGINT/SIGTERM trap.
- No `set -e` in the loop body — every sub-step failure (pipeline crash, claude error, publish error) logs and falls through to the next sleep. The outer loop never exits on failure.
- `output=$(... | tee -a "$LOG_FILE")` captures stdout so we can grep the draft marker; the `tee` still mirrors output to the log file so the operator's `tail -f` view is unchanged.
- The prompt is interpolated with shell `$run_id` — `claude -p` receives a fully expanded prompt.

- [ ] **Step 2: Lint with bash itself**

Run: `bash -n storybot/run_twitter_pipeline_loop.sh`
Expected: no output (clean syntax). If anything fails, fix and re-run.

- [ ] **Step 3: If `shellcheck` is installed, run it**

Run: `command -v shellcheck >/dev/null && shellcheck storybot/run_twitter_pipeline_loop.sh || echo "shellcheck not installed, skipping"`
Expected: clean, or `shellcheck not installed, skipping`. SC2034 / SC1091 false-positives on `LOG_DIR` and the `source` line can be ignored — the original script already had these.

- [ ] **Step 4: Commit**

```bash
git add storybot/run_twitter_pipeline_loop.sh
git commit -m "feat(twitter): chain draft → claude edit → publish in loop shell"
```

---

## Task 5: Manual smoke test of the full chain

This task has no code — it's an operator playbook so the implementer doesn't ship without exercising the new chain end-to-end. Each step is a manual action with a concrete expected result.

- [ ] **Step 1: DRY_RUN-only smoke test of the pipeline split**

Run: `DRY_RUN=true python storybot/twitter_pipeline.py`
Expected: pipeline finishes 0; `storybot/dry_runs/twitter_drafts/<run_id>.txt` exists and contains a tweet body; `storybot/dry_runs/twitter_pipeline_<run_id>.json` exists and the JSON has a top-level `publish_meta` key with `alert_ids`, `chart_type`, `target_alert_id`, `chart_png_path`, `recent_openers`, `recent_tweets`; stdout contains `[twitter_pipeline] draft run_id=<run_id>`.

If the pipeline skips on the skip path (no alerts cleared, all deduped, picker chose skip), that's also fine — confirm there's NO `draft run_id=` line in stdout, NO draft .txt was written, and the pipeline exited 0.

- [ ] **Step 2: Confirm publish_tweet refuses DRY_RUN drafts**

Run (using the same run_id from Step 1, if it actually drafted): `python storybot/publish_tweet.py <run_id>`
Expected: exits 1 with `error: no draft found at storybot/twitter_drafts/<run_id>.txt`. The publisher only reads from the live drafts dir, so DRY_RUN drafts are invisible by design.

- [ ] **Step 3: Live one-shot smoke test**

Run: `python storybot/twitter_pipeline.py` (no DRY_RUN). If the pipeline drafts (it may also skip — that's a content decision):
1. Confirm `storybot/twitter_drafts/<run_id>.txt` exists.
2. Confirm `storybot/live_runs/twitter_pipeline_<run_id>.json` has `publish_meta`.
3. Optionally hand-edit the .txt to a known-good tweet body.
4. Run: `python storybot/publish_tweet.py <run_id>`
5. Confirm the tweet posts (check `https://x.com/<your_handle>` ).
6. Confirm `record_tweet` ran — check the `tweeted_alerts` table for a row keyed to one of the `alert_ids`.

- [ ] **Step 4: Loop shell smoke test (one iteration)**

Edit a copy of `storybot/run_twitter_pipeline_loop.sh` to set `INTERVAL_SECONDS=30` (so you don't wait 5 hours after the first run for the test to finish).

Run in foreground (no screen) for one iteration: `INTERVAL_SECONDS=30 ./storybot/run_twitter_pipeline_loop.sh &` then watch `tail -f storybot/logs/twitter_pipeline.log` and verify:
- `===== run started ... =====` line appears.
- Either `[twitter_pipeline] draft run_id=<hex>` line appears and is followed by `[loop] draft run_id=<hex> — invoking claude to edit`, the claude run output, `[publish_tweet] published run_id=<hex> tweet_id=<num>`, and `[loop] published run_id=<hex>`; OR `[loop] no draft produced (pipeline skipped). Sleeping.` for the skip path.
- After the first iteration, `sleeping 30s until next run` appears.
- After 30s, a second iteration starts.

Kill the loop: bring it to foreground with `fg` then `Ctrl-C`. Expected: the log shows `loop interrupted, exiting` and the script exits 0.

- [ ] **Step 5: Loop survival test — inject a failure**

With the loop running (still at `INTERVAL_SECONDS=30`), temporarily break the venv: `mv venv venv.bak`. The next iteration will fail at the `source venv/bin/activate` line — but the loop body's `source` is at the top, outside the while loop, so this actually kills the script. Restore: `mv venv.bak venv`.

A more representative test: rename `storybot/publish_tweet.py` to `publish_tweet.py.bak` for one iteration. Expected: pipeline drafts, claude runs and edits, then publish_tweet.py fails to import (or raises). The loop logs `[loop] publish_tweet failed for run_id=<hex> — draft preserved on disk` and proceeds to `sleeping 30s until next run`. Restore the file.

- [ ] **Step 6: Cleanup smoke run leftovers (optional)**

Any orphan drafts in `storybot/twitter_drafts/` from failed smoke runs can be deleted with `rm storybot/twitter_drafts/<run_id>.txt`. They aren't load-bearing — the next iteration starts fresh.

- [ ] **Step 7: Commit nothing**

No code changes from this task; nothing to commit. If the smoke tests turned up issues, go back to the relevant Task above and fix.

---

## Self-Review Findings

(Run by the planner before handing this plan off.)

**Spec coverage:**
- Spec § "Goals" — every bullet covered: draft → claude → publish chain (Task 4), Claude edits .txt only (Task 2 writes .txt; Task 4 prompt points only at .txt), edits flow through (Task 3 reads .txt for tweet body), validate_tweet runs in publisher (Task 3 Step 3 includes the call), failures are per-iteration not loop-killing (Task 4 has no `set -e` in body), pipeline becomes draft-only (Task 2 removes post block).
- Spec § "Non-goals" — none implemented (LLM re-validation: not done; tweet_drafts table: not done; interactive DRY_RUN: removed; DRAFT_ONLY env: not done).
- Spec § "Architecture" — file map matches Tasks 1–4.
- Spec § "Error handling" table — every row exercised: pipeline exit ≠ 0 (Task 4 first if branch), no draft marker (Task 4 grep returns empty), claude exit ≠ 0 (Task 4 else branch on `if claude -p`), validate_tweet fail (Task 3 test `test_publish_tweet_validation_failure_does_not_post`), post_tweet raises (Task 3 publisher catches, exits 1), record_tweet raises (Task 3 test `test_publish_tweet_record_failure_is_soft_fail`).
- Spec § "Testing" — Task 5 manual playbook covers smoke + DRY_RUN + loop + survival.

**Placeholder scan:** No TBD / TODO / "implement later" / "add error handling" / "similar to Task N". Every code block is complete.

**Type/symbol consistency:**
- `_write_draft(run_id, tweet) -> str` — defined in Task 1; called in Task 2 with the same signature.
- `TWITTER_DRAFTS_DIR`, `LIVE_RUNS_DIR` — module-level constants in `publish_tweet.py` (Task 3); test patches them by the same names.
- `_REQUIRED_PUBLISH_META_KEYS` — defined and used inside `publish_tweet.py`.
- `validate_tweet` — imported from `twitter_pipeline` in Task 3; defined at `twitter_pipeline.py:980` (verified during planning).
- `publish_meta` keys (`alert_ids`, `chart_type`, `target_alert_id`, `chart_png_path`, `recent_openers`, `recent_tweets`) — written by Task 2, read by Task 3 (required keys are the first four; openers/tweets are claude-only context), referenced in Task 4 prompt as `publish_meta.recent_openers`. Consistent across all three tasks.

No issues found; plan is ready.
