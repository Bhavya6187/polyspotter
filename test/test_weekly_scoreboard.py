"""Weekly scoreboard renderer + result_pipeline weekly posting (Delta 4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def _data(n_cashed=11, n_burned=4, net=58000.0):
    return {"n_cashed": n_cashed, "n_burned": n_burned,
            "net_pl_usd": net, "week_label": "Week of Jun 8"}


def test_weekly_scoreboard_renders_png_bytes():
    for net in (58000.0, -12000.0, 0.0):
        png = charts.render_weekly_scoreboard(_data(net=net))
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_weekly_scoreboard_handles_zero_results():
    png = charts.render_weekly_scoreboard(_data(n_cashed=0, n_burned=0, net=0.0))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


from datetime import datetime, timezone  # noqa: E402

import result_pipeline as rp  # noqa: E402

# 2026-06-14 is a Sunday. 22:00 UTC == 18:00 ET (EDT, UTC-4) — in-window.
SUNDAY_EVENING = datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc)
SUNDAY_AFTERNOON = datetime(2026, 6, 14, 18, 0, tzinfo=timezone.utc)  # 2pm ET
THURSDAY = datetime(2026, 6, 11, 22, 0, tzinfo=timezone.utc)


def test_window_open_sunday_evening_et():
    assert rp._weekly_scoreboard_window(SUNDAY_EVENING) == "2026-W24"


def test_window_closed_outside_hours_and_days():
    assert rp._weekly_scoreboard_window(SUNDAY_AFTERNOON) is None
    assert rp._weekly_scoreboard_window(THURSDAY) is None


def test_week_label_is_monday_of_week():
    assert rp._week_label(SUNDAY_EVENING) == "Week of Jun 8"


def test_weekly_tweet_text_passes_validation():
    import twitter_pipeline as tp
    for n_c, n_b, net in [(11, 4, 58000.0), (2, 5, -12000.0), (3, 0, 900.0)]:
        text = rp.format_weekly_scoreboard_tweet(n_c, n_b, net)
        ok, err = tp.validate_tweet(text)
        assert ok, f"{text!r}: {err}"


def test_maybe_post_skips_when_already_posted(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: True)
    called = {"agg": False}
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: called.__setitem__("agg", True) or {})
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert called["agg"] is False


def test_maybe_post_skips_below_min_results(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: False)
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: {"n_cashed": 1, "n_burned": 1,
                                 "net_pl_usd": 100.0})
    posted = {"called": False}
    monkeypatch.setattr(rp, "post_tweet",
                        lambda *a, **k: posted.__setitem__("called", True) or "x")
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert posted["called"] is False


def test_maybe_post_happy_path(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: False)
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: {"n_cashed": 11, "n_burned": 4,
                                 "net_pl_usd": 58000.0})
    monkeypatch.setattr(rp, "_build_twitter_client", lambda: object())
    monkeypatch.setattr(rp, "_build_twitter_api_v1", lambda: object())
    monkeypatch.setattr(rp, "post_tweet", lambda *a, **k: "tid-77")
    captured = {}
    monkeypatch.setattr(rp.result_store, "record_weekly_scoreboard",
                        lambda **kw: captured.update(kw))
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert captured["iso_week"] == "2026-W24"
    assert captured["tweet_id"] == "tid-77"
    assert captured["n_cashed"] == 11 and captured["n_burned"] == 4
