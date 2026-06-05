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
