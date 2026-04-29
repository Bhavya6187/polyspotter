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
