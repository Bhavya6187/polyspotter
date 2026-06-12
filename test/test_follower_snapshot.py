"""Tests for result_pipeline.maybe_snapshot_followers (Delta 5)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_pipeline as rp  # noqa: E402

NOW = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)  # 2pm ET


def _fake_client(followers=73, tweets=385):
    metrics = {"followers_count": followers, "tweet_count": tweets}
    return SimpleNamespace(
        get_me=lambda user_fields: SimpleNamespace(
            data=SimpleNamespace(public_metrics=metrics)))


def test_snapshot_skips_when_row_exists(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: True)
    called = {"client": False}
    monkeypatch.setattr(rp, "_build_twitter_client",
                        lambda: called.__setitem__("client", True))
    rp.maybe_snapshot_followers(NOW)
    assert called["client"] is False  # no API call when already snapshotted


def test_snapshot_records_on_first_run_of_day(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: False)
    monkeypatch.setattr(rp, "_build_twitter_client", _fake_client)
    captured = {}
    monkeypatch.setattr(rp.result_store, "record_follower_snapshot",
                        lambda **kw: captured.update(kw))
    rp.maybe_snapshot_followers(NOW)
    assert captured["followers_count"] == 73
    assert captured["tweet_count"] == 385
    assert str(captured["snapshot_date"]) == "2026-06-11"


def test_snapshot_never_raises(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: False)

    def boom():
        raise RuntimeError("api down")
    monkeypatch.setattr(rp, "_build_twitter_client", boom)
    rp.maybe_snapshot_followers(NOW)  # must not raise


def test_snapshot_noop_in_dry_run(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", True)
    called = {"exists": False}
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: called.__setitem__("exists", True) or False)
    rp.maybe_snapshot_followers(NOW)
    assert called["exists"] is False
