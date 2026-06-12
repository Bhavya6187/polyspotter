"""Tests for storybot/result_store.py."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_store as rs  # noqa: E402


def test_todays_posted_outcomes_filters_to_et_day_and_maps_wins(monkeypatch):
    # _run returns rows of (posted_at, outcome). The function should keep only
    # rows on the same ET calendar day as `now` and map outcome -> is_win.
    now = datetime(2026, 6, 4, 18, 0, tzinfo=timezone.utc)  # 2pm ET
    rows = [
        {"posted_at": datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc),
         "outcome": "cashed"},   # same ET day -> win
        {"posted_at": datetime(2026, 6, 4, 16, 0, tzinfo=timezone.utc),
         "outcome": "burned"},   # same ET day -> loss
        {"posted_at": datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc),
         "outcome": "cashed"},   # previous ET day -> excluded
    ]
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: rows)
    assert rs.todays_posted_outcomes(now) == [True, False]


def test_record_result_passes_unique_conflict_sql(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    rs.record_result(
        original_tweet_id="111", result_tweet_id="222",
        alert_ids=[1, 2], condition_ids=["0xabc"],
        n_won=3, n_lost=1, net_pl_usd=31000.0,
        total_invested_usd=20000.0, outcome="cashed",
        event_label="Padres-Phillies Over 7.5",
    )
    assert "ON CONFLICT (original_tweet_id)" in captured["query"]
    assert captured["params"][0] == "111"
    # Binding contract: arrays/ints/floats are coerced for psycopg2.
    assert captured["params"][2] == [1, 2]          # alert_ids -> list[int]
    assert captured["params"][3] == ["0xabc"]       # condition_ids -> list[str]


def test_todays_posted_outcomes_handles_naive_now_and_skips_null_rows(monkeypatch):
    # Naive `now` (assumed UTC) exercises the tzinfo-fill branch; rows with a
    # None posted_at/outcome must be skipped / treated as a non-win.
    now = datetime(2026, 6, 4, 18, 0)  # naive -> UTC -> 2pm ET
    rows = [
        {"posted_at": datetime(2026, 6, 4, 13, 0),  # naive same ET day
         "outcome": "cashed"},                      # -> win
        {"posted_at": None, "outcome": "cashed"},   # skipped (no timestamp)
        {"posted_at": datetime(2026, 6, 4, 15, 0, tzinfo=timezone.utc),
         "outcome": None},                          # same ET day, None -> loss
    ]
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: rows)
    assert rs.todays_posted_outcomes(now) == [True, False]


def test_follower_snapshot_exists_true_when_row(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [{"?column?": 1}])
    from datetime import date
    assert rs.follower_snapshot_exists(date(2026, 6, 11)) is True


def test_follower_snapshot_exists_false_when_empty(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [])
    from datetime import date
    assert rs.follower_snapshot_exists(date(2026, 6, 11)) is False


def test_record_follower_snapshot_uses_conflict_do_nothing(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    from datetime import date
    rs.record_follower_snapshot(snapshot_date=date(2026, 6, 11),
                                followers_count=73, tweet_count=385)
    assert "ON CONFLICT (snapshot_date) DO NOTHING" in captured["query"]
    assert captured["params"] == (date(2026, 6, 11), 73, 385)


def test_recent_record_maps_outcome_counts(monkeypatch):
    monkeypatch.setattr(rs, "_run",
                        lambda q, p, fetch=True: [{"n_cashed": 11, "n_burned": 4}])
    assert rs.recent_record() == (11, 4)


def test_recent_record_empty_table(monkeypatch):
    monkeypatch.setattr(rs, "_run",
                        lambda q, p, fetch=True: [{"n_cashed": 0, "n_burned": 0}])
    assert rs.recent_record(days=30) == (0, 0)


def test_weekly_scoreboard_exists(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [{"?column?": 1}])
    assert rs.weekly_scoreboard_exists("2026-W24") is True
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [])
    assert rs.weekly_scoreboard_exists("2026-W24") is False


def test_record_weekly_scoreboard_conflict_do_nothing(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    rs.record_weekly_scoreboard(iso_week="2026-W24", tweet_id="999",
                                n_cashed=11, n_burned=4, net_pl_usd=58000.0)
    assert "ON CONFLICT (iso_week) DO NOTHING" in captured["query"]
    assert captured["params"] == ("2026-W24", "999", 11, 4, 58000.0)


def test_weekly_aggregate_maps_row(monkeypatch):
    monkeypatch.setattr(
        rs, "_run",
        lambda q, p, fetch=True: [{"n_cashed": 5, "n_burned": 2,
                                   "net_pl_usd": 12345.6}])
    agg = rs.weekly_aggregate()
    assert agg == {"n_cashed": 5, "n_burned": 2, "net_pl_usd": 12345.6}
