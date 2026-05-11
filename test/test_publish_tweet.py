"""Tests for storybot/publish_tweet.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


_TWEET_BODY = (
    "A 31-day-old wallet just dropped $80k at 12c on a coin-flip. "
    "Resolution hits in 14 hours."
)


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
