"""Tests for the seed-alert quality floor applied before stage 1.

The floor drops alerts that don't meet at least one of:
  - total_usd >= QUALITY_FLOOR_MIN_USD
  - non-sports event (game_start_time is None)
  - >=QUALITY_FLOOR_MIN_WIN_RATE win-rate-strategy headline
  - >=QUALITY_FLOOR_MIN_PRICE_MOVE price-impact-strategy headline
Goal: cut posting volume so only surprising alerts reach Twitter.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


def _sports_alert(**overrides):
    """A baseline sports alert that fails every floor criterion."""
    base = {
        "id": 1,
        "total_usd": 5000.0,
        "game_start_time": datetime(2026, 5, 11, tzinfo=timezone.utc),
        "signals": [],
    }
    base.update(overrides)
    return base


def test_floor_passes_on_dollar_threshold():
    alert = _sports_alert(total_usd=25_000.0)
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert ok
    assert "total_usd" in reason


def test_floor_passes_on_dollar_above_threshold():
    alert = _sports_alert(total_usd=100_000.0)
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert ok


def test_floor_rejects_below_dollar_threshold():
    alert = _sports_alert(total_usd=24_999.0)
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert not ok
    assert reason == ""


def test_floor_passes_non_sports_regardless_of_size():
    alert = _sports_alert(total_usd=500.0, game_start_time=None)
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert ok
    assert reason == "non_sports"


def test_floor_passes_high_win_rate_strategy():
    alert = _sports_alert(signals=[{
        "strategy": "win_rate_tracking",
        "severity": 4,
        "headline": "92% win rate (resolved+open) at avg odds 51% (+41% edge)",
    }])
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert ok
    assert "win_rate" in reason


def test_floor_passes_exactly_90_win_rate():
    alert = _sports_alert(signals=[{
        "strategy": "win_rate_tracking",
        "severity": 3,
        "headline": "90% win rate (resolved)",
    }])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert ok


def test_floor_rejects_89_win_rate():
    alert = _sports_alert(signals=[{
        "strategy": "win_rate_tracking",
        "severity": 2,
        "headline": "89% win rate (resolved)",
    }])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert not ok


def test_floor_passes_big_price_move():
    alert = _sports_alert(signals=[{
        "strategy": "price_impact",
        "severity": 3,
        "headline": "rapid price UP 18.50% in 60s (Yes)",
    }])
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert ok
    assert "price_move" in reason


def test_floor_passes_exactly_15c_price_move():
    alert = _sports_alert(signals=[{
        "strategy": "price_impact",
        "severity": 3,
        "headline": "rapid price DOWN 15.00% in 90s (No)",
    }])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert ok


def test_floor_rejects_small_price_move():
    alert = _sports_alert(signals=[{
        "strategy": "price_impact",
        "severity": 1,
        "headline": "rapid price UP 8.00% in 60s (Yes)",
    }])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert not ok


def test_floor_ignores_other_strategies():
    """A volume_spike or clustering signal alone doesn't satisfy the floor —
    the floor only credits the four named criteria."""
    alert = _sports_alert(signals=[
        {"strategy": "pre_event_volume_spike", "severity": 5,
         "headline": "10x usual volume"},
        {"strategy": "concentrated_one_sided", "severity": 4,
         "headline": "3 wallets, $5k, share funder (linked)"},
    ])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert not ok


def test_floor_handles_missing_signals():
    """An alert with no signals shouldn't crash — just fails the floor."""
    alert = _sports_alert(signals=None)
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert not ok


def test_floor_handles_missing_total_usd():
    """Alert rows can have NULL total_usd from old data — skip the dollar
    check and fall through to other criteria."""
    alert = _sports_alert(total_usd=None, game_start_time=None)
    ok, reason = twitter_pipeline._passes_quality_floor(alert)
    assert ok
    assert reason == "non_sports"


def test_floor_handles_malformed_signal_entry():
    """A non-dict signal entry shouldn't crash the loop."""
    alert = _sports_alert(signals=["not a dict", None, 42])
    ok, _ = twitter_pipeline._passes_quality_floor(alert)
    assert not ok


def test_apply_floor_returns_stats():
    seeds = [
        _sports_alert(id=1, total_usd=100_000),               # passes: usd
        _sports_alert(id=2, total_usd=5_000),                 # drops
        _sports_alert(id=3, game_start_time=None),            # passes: non_sports
        _sports_alert(id=4, signals=[{
            "strategy": "win_rate_tracking",
            "headline": "94% win rate (resolved)"}]),         # passes: win_rate
        _sports_alert(id=5, signals=[{
            "strategy": "price_impact",
            "headline": "rapid price UP 20.0% in 60s (Yes)"}]),  # passes: price_move
        _sports_alert(id=6, total_usd=1_000),                 # drops
    ]
    kept, stats = twitter_pipeline._apply_quality_floor(seeds)
    assert [a["id"] for a in kept] == [1, 3, 4, 5]
    assert stats["dropped"] == 2
    assert stats["total_usd"] == 1
    assert stats["non_sports"] == 1
    assert stats["win_rate"] == 1
    assert stats["price_move"] == 1


def test_apply_floor_empty_input():
    kept, stats = twitter_pipeline._apply_quality_floor([])
    assert kept == []
    assert stats["dropped"] == 0


def test_apply_floor_all_drop():
    seeds = [_sports_alert(id=i, total_usd=1_000) for i in range(10)]
    kept, stats = twitter_pipeline._apply_quality_floor(seeds)
    assert kept == []
    assert stats["dropped"] == 10
