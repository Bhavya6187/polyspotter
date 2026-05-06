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
    fake_cur.rowcount = 1

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


def test_sync_run_zero_rowcount_aborts_no_commit(tmp_path, monkeypatch):
    """Defensive WHERE clause didn't match (race: row flipped to 'published'
    between SELECT and UPDATE). Must rollback, exit 1, and NOT commit."""
    import sync_article_from_md as sync
    import pytest

    monkeypatch.setattr(sync, "ARTICLES_DIR", str(tmp_path))
    md_path = tmp_path / "abc12345.md"
    md_path.write_text(_build_md(
        body=(
            "Opening hook line that pulls the reader in.\n\n"
            "## The wallet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## The bet\n\n" + " ".join(["lorem"] * 200) + "\n\n"
            "## What to watch\n\n" + " ".join(["lorem"] * 170) + "\n\n"
            "Closing line. https://polyspotter.com/market/x"
        ),
    ))
    fake_conn, fake_cur = _patch_conn(
        monkeypatch, ("abc12345", "draft", "alt", [11, 12])
    )
    # Status was 'draft' at SELECT time, but a parallel writer flipped it
    # to 'published' before our UPDATE landed → rowcount=0.
    fake_cur.rowcount = 0

    with pytest.raises(SystemExit) as exc:
        sync.sync_run("abc12345")
    assert exc.value.code == 1
    fake_conn.commit.assert_not_called()
    fake_conn.rollback.assert_called_once()
