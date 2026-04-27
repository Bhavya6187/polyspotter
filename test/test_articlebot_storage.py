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


import os
from unittest.mock import MagicMock

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
    assert fake_conn.commit.called
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
    # status is set in SQL (`'skipped'` literal) or in params — accept either
    assert "'skipped'" in sql or "skipped" in str(params)
    assert params[0] == "def67890"


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
