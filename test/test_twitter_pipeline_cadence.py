"""Tests for the peak-window cadence gate applied at the top of main().

The gate keeps the bot posting ~1-2 tweets/day, only inside peak ET windows,
at most once per window. All helpers are pure (now + recent_tweets in).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


def _tw(iso):
    """A minimal recent-tweet row — only tweeted_at matters to the gate."""
    return {"tweet": "x", "condition_ids": [], "tweeted_at": iso}


# --- _current_peak_window -------------------------------------------------

def test_current_peak_window_morning_est():
    # Jan 15 2026 14:00 UTC = 09:00 ET (EST, UTC-5) — inside morning [8,10).
    now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_evening_est():
    # Jan 16 2026 00:00 UTC = 19:00 ET Jan 15 (EST) — inside evening [18,22).
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "evening"


def test_current_peak_window_outside_overnight():
    # Jan 15 2026 08:00 UTC = 03:00 ET — no window.
    now = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) is None


def test_current_peak_window_between_windows():
    # Jan 15 2026 16:00 UTC = 11:00 ET — between morning and midday.
    now = datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) is None


def test_current_peak_window_dst_discriminator_summer():
    # Jul 15 2026 12:30 UTC: EDT (UTC-4) = 08:30 ET -> morning.
    # A fixed UTC-5 impl would compute 07:30 ET -> None. Proves DST handling.
    now = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_dst_discriminator_winter():
    # Jan 15 2026 14:30 UTC: EST (UTC-5) = 09:30 ET -> morning.
    # A fixed UTC-4 impl would compute 10:30 ET -> None. Proves DST handling.
    now = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_naive_treated_as_utc():
    now = datetime(2026, 1, 15, 14, 0)  # naive -> assumed UTC -> 09:00 ET
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_boundaries_are_half_open():
    # 08:00 ET (window start) is IN morning; 10:00 ET (window end) is OUT.
    # Jan 2026 -> EST (UTC-5): 08:00 ET = 13:00 UTC, 10:00 ET = 15:00 UTC.
    start = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(start) == "morning"
    assert twitter_pipeline._current_peak_window(end) is None


# --- _posts_today ---------------------------------------------------------

def test_posts_today_counts_same_et_day():
    # now = Jan 15 2026 18:00 UTC = 13:00 ET Jan 15.
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    recent = [
        _tw("2026-01-15T14:00:00+00:00"),  # 09:00 ET Jan 15 — today
        _tw("2026-01-15T20:00:00+00:00"),  # 15:00 ET Jan 15 — today
        _tw("2026-01-14T20:00:00+00:00"),  # 15:00 ET Jan 14 — yesterday
    ]
    assert twitter_pipeline._posts_today(recent, now) == 2


def test_posts_today_ignores_bad_or_missing_timestamp():
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    recent = [_tw(None), _tw("not-a-date"), {"tweet": "x"}]
    assert twitter_pipeline._posts_today(recent, now) == 0


def test_posts_today_empty():
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._posts_today([], now) == 0
