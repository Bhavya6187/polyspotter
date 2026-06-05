import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import publish_result as pub  # noqa: E402


def test_publish_skips_when_already_recorded(monkeypatch):
    # If result_store says this original tweet is already settled, do not post.
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: True)
    posted = {"called": False}
    monkeypatch.setattr(pub, "post_tweet",
                        lambda *a, **k: posted.__setitem__("called", True) or "x")
    rc = pub.publish(original_tweet_id="111", artifact={
        "original_tweet": "x", "result_tweet": "ok", "result_draft_path": None,
        "scorecard_png_path": None, "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 1, "n_lost": 0, "net_pl_usd": 5.0,
                      "total_invested_usd": 10.0},
        "outcome": "cashed", "event_label": "E",
    }, dry_run=True)
    assert rc == 0
    assert posted["called"] is False  # dedup short-circuits before posting


def test_publish_rejects_invalid_tweet(monkeypatch):
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: False)
    # A tweet with a URL must be rejected by validate_tweet.
    rc = pub.publish(original_tweet_id="222", artifact={
        "result_tweet": "Cashed +$31k https://polyspotter.com/alert/1",
        "result_draft_path": None, "scorecard_png_path": None,
        "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 1, "n_lost": 0, "net_pl_usd": 5.0,
                      "total_invested_usd": 10.0},
        "outcome": "cashed", "event_label": "E",
    }, dry_run=True)
    assert rc == 1  # validation failure


def test_publish_happy_path_records_and_returns_zero(monkeypatch):
    captured = {}
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: False)
    monkeypatch.setattr(pub, "post_tweet",
                        lambda *a, **k: "tweet-id-123")
    monkeypatch.setattr(pub.result_store, "record_result",
                        lambda **kw: captured.update(kw))
    rc = pub.publish(original_tweet_id="333", artifact={
        "result_tweet": "Cashed +$31k on the Over. Sharp read confirmed.",
        "result_draft_path": None, "scorecard_png_path": None,
        "alert_ids": [1, 2], "condition_ids": ["0xabc"],
        "aggregate": {"n_won": 3, "n_lost": 1, "net_pl_usd": 31000.0,
                      "total_invested_usd": 20000.0},
        "outcome": "cashed", "event_label": "Padres-Phillies Over 7.5",
    }, dry_run=True)
    assert rc == 0
    assert captured["original_tweet_id"] == "333"
    assert captured["result_tweet_id"] == "tweet-id-123"
    assert captured["n_won"] == 3 and captured["n_lost"] == 1


def test_publish_returns_2_when_record_fails_after_retry(monkeypatch):
    # Tweet posts, but record_result keeps raising -> posted-but-unrecorded.
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: False)
    monkeypatch.setattr(pub, "post_tweet", lambda *a, **k: "tid-9")

    def always_raises(**kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(pub.result_store, "record_result", always_raises)
    rc = pub.publish(original_tweet_id="444", artifact={
        "result_tweet": "Burned -$28k on the spread. Tough one.",
        "result_draft_path": None, "scorecard_png_path": None,
        "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 1, "n_lost": 3, "net_pl_usd": -28000.0,
                      "total_invested_usd": 28000.0},
        "outcome": "burned", "event_label": "E",
    }, dry_run=True)
    assert rc == 2  # posted but not recorded


def test_main_missing_artifact_returns_1(monkeypatch, tmp_path):
    # main() with no artifact file on disk returns 1.
    monkeypatch.setattr(pub, "_RUN_OUTPUT_DIR", str(tmp_path))
    rc = pub.main(["publish_result.py", "no-such-id"])
    assert rc == 1
