"""Unit tests for chart_grid.select_tiles — pure function over facts_bundle."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402


def _bundle(**overrides):
    """Default-zero bundle, overridable per test."""
    base = {
        "distinct_wallets": 0,
        "total_usd": 0.0,
        "trade_count": 0,
        "time_span_minutes": 0,
        "biggest_price_move": None,
        "peak_hour_volume_usd": None,
        "has_sharp_wallet": None,
        "has_fresh_wallet": None,
        "cluster_size": None,
        "has_volume_spike": False,
        "minutes_to_resolution": None,
        "volume_multiplier_x": None,
    }
    base.update(overrides)
    return base


def test_clock_wins_when_set():
    fb = _bundle(minutes_to_resolution=11, total_usd=50_000)
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert [t.kind for t in tiles][0] == "clock"


def test_dedup_sharp_record_when_hero_is_wallet_record_card():
    fb = _bundle(has_sharp_wallet={"record": "24-1", "win_pct": 0.96})
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert "sharp_record" not in [t.kind for t in tiles]


def test_dedup_cluster_tiles_when_hero_is_cluster_card():
    fb = _bundle(total_usd=200_000, cluster_size=7)
    tiles = chart_grid.select_tiles("cluster_card", fb)
    kinds = [t.kind for t in tiles]
    assert "cluster_total" not in kinds
    assert "linked_accounts" not in kinds


def test_dedup_volume_when_hero_is_volume_bar():
    fb = _bundle(has_volume_spike=True, volume_multiplier_x=12.0)
    tiles = chart_grid.select_tiles("volume_bar", fb)
    assert "volume_x" not in [t.kind for t in tiles]


def test_dedup_price_when_hero_is_price_sparkline():
    fb = _bundle(biggest_price_move={"from": 0.32, "to": 0.41})
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert "price_move" not in [t.kind for t in tiles]


def test_cluster_total_dropped_below_threshold():
    fb = _bundle(total_usd=10_000)  # below $25k
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert "cluster_total" not in [t.kind for t in tiles]


def test_price_move_dropped_below_threshold():
    fb = _bundle(biggest_price_move={"from": 0.50, "to": 0.51})  # 1c, < 3c
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert "price_move" not in [t.kind for t in tiles]


def test_priority_order_caps_at_three():
    """All eight tiles eligible — only the top 3 by priority should appear."""
    fb = _bundle(
        minutes_to_resolution=11,             # 1: clock
        total_usd=200_000,                    # 2: cluster_total
        has_volume_spike=True,                # 3: volume_x
        volume_multiplier_x=12.0,
        biggest_price_move={"from": 0.30, "to": 0.40},  # 4: price_move
        cluster_size=7,                       # 5: linked_accounts
        has_sharp_wallet={"record": "24-1"},  # 6: sharp_record
        has_fresh_wallet={"wallet": "0xa"},   # 7: fresh_wallet
        distinct_wallets=15,                  # 8: wallets
    )
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    # price_sparkline hero suppresses price_move at slot 4, but slot 4 was
    # never going to fit anyway — top 3 are clock, cluster_total, volume_x.
    assert [t.kind for t in tiles] == ["clock", "cluster_total", "volume_x"]


def test_zero_eligible_returns_empty_list():
    fb = _bundle()
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert tiles == []
