"""Tests for prepare_chart in twitter_simple.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_simple  # noqa: E402


def test_prepare_chart_returns_none_for_skip_decision():
    decision = {"decision": "skip", "alert_ids": [], "chart_type": "none"}
    result = twitter_simple.prepare_chart(decision, [])
    assert result is None


def test_prepare_chart_returns_none_when_alert_id_not_in_seed():
    decision = {"decision": "post", "alert_ids": [99], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}]
    result = twitter_simple.prepare_chart(decision, seed)
    assert result is None


def test_prepare_chart_calls_dispatcher_with_correct_alert():
    decision = {"decision": "post", "alert_ids": [1], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}, {"id": 2, "wallet": "0xdef"}]
    with patch("twitter_simple.charts.render_chart_for_alert", return_value=b"fakepng") as m:
        result = twitter_simple.prepare_chart(decision, seed)
    assert result == b"fakepng"
    m.assert_called_once_with("wallet_record_card", seed[0])


def test_prepare_chart_swallows_exceptions():
    decision = {"decision": "post", "alert_ids": [1], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}]
    with patch("twitter_simple.charts.render_chart_for_alert",
               side_effect=RuntimeError("boom")):
        result = twitter_simple.prepare_chart(decision, seed)
    assert result is None


def test_post_tweet_uploads_media_when_provided():
    fake_v1 = type("FakeAPI", (), {})()
    fake_v1.media_upload = lambda filename, file: type("M", (), {"media_id": 1234567})()
    fake_v2 = type("FakeClient", (), {})()
    captured = {}
    def create_tweet(text, media_ids=None):
        captured["text"] = text
        captured["media_ids"] = media_ids
        return type("R", (), {"data": {"id": "555"}})()
    fake_v2.create_tweet = create_tweet

    tweet_id = twitter_simple.post_tweet(
        "Hello", twitter_client=fake_v2, twitter_api_v1=fake_v1,
        media_png=b"\x89PNG\x00fakepng", dry_run=False,
    )
    assert tweet_id == "555"
    assert captured["media_ids"] == [1234567]
    assert captured["text"] == "Hello"


def test_post_tweet_skips_media_when_none():
    fake_v2 = type("FakeClient", (), {})()
    captured = {}
    def create_tweet(text, media_ids=None):
        captured["media_ids"] = media_ids
        return type("R", (), {"data": {"id": "777"}})()
    fake_v2.create_tweet = create_tweet

    tweet_id = twitter_simple.post_tweet(
        "Hello", twitter_client=fake_v2, twitter_api_v1=None,
        media_png=None, dry_run=False,
    )
    assert tweet_id == "777"
    assert captured["media_ids"] is None
