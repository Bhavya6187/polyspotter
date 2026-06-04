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
