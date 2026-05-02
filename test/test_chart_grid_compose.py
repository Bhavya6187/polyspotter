"""Smoke tests for chart_grid.compose_chart — assembles hero + tiles into 1200×675."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402
import charts  # noqa: E402


def _wallet_record_data():
    return {
        "market_title": "Lakers vs Rockets: O/U 206.5",
        "record_str": "24-1",
        "win_pct": 0.96,
        "bet_count": 25,
        "bet_size_usd": 7_000,
        "outcome_side": "Under",
    }


def test_compose_chart_produces_canvas_sized_png():
    fb = {
        "minutes_to_resolution": 214,
        "total_usd": 220_000,
        "cluster_size": 7,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.60, "to": 0.62},
        "has_sharp_wallet": {"record": "24-1"},
        "has_fresh_wallet": None,
        "distinct_wallets": 15,
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=_wallet_record_data()):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc", "market_title": "Lakers vs Rockets"},
            facts_bundle=fb,
        )
    assert png is not None
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_compose_chart_zero_tiles_falls_back_to_single_chart():
    """No tiles pass thresholds → fall back to the existing single-chart layout."""
    fb = {  # everything zeroed
        "minutes_to_resolution": None,
        "total_usd": 0,
        "cluster_size": None,
        "has_volume_spike": False,
        "volume_multiplier_x": None,
        "biggest_price_move": None,
        "has_sharp_wallet": None,
        "has_fresh_wallet": None,
        "distinct_wallets": 0,
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=_wallet_record_data()):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc"},
            facts_bundle=fb,
        )
    img = Image.open(BytesIO(png))
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_compose_chart_hero_fetch_returns_none_returns_none():
    fb = {"minutes_to_resolution": 11, "total_usd": 200_000, "cluster_size": 7}
    with patch.object(charts, "fetch_wallet_record_card_data", return_value=None):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc"},
            facts_bundle=fb,
        )
    assert png is None


# ---------------------------------------------------------------------------
# Parameterized smoke: every hero type must render a correctly-sized PNG
# ---------------------------------------------------------------------------

_HERO_FAKE_DATA = {
    "wallet_record_card": {
        "market_title": "Lakers vs Rockets: O/U 206.5",
        "record_str": "24-1",
        "win_pct": 0.96,
        "bet_count": 25,
        "bet_size_usd": 7_000,
        "outcome_side": "Under",
    },
    "fresh_wallet_card": {
        "market_title": "Will Brentford FC win on 2026-05-02?",
        "wallet_age_days": 9,
        "bet_size_usd": 80_000,
        "outcome_side": "Yes",
    },
    "volume_bar": {
        "market_title": "Lewandowski to score 2+ goals vs Mallorca",
        "today_volume_usd": 130_000,
        "baseline_avg_usd": 4_000,
        "multiplier": 32.5,
    },
    "cluster_card": {
        "market_title": "Will Brentford FC win on 2026-05-02?",
        "outcome_side": "Yes",
        "wallet_sizes": [("Wallet_0xa1b23", 24_000.0),
                         ("Wallet_0xc4d56", 8_000.0),
                         ("Wallet_0xe7f89", 6_500.0),
                         ("Wallet_0xb1c2d", 3_000.0)],
        "total_usd": 41_500.0,
        "shared_funder": "0xff45ee9988aa1122",
    },
    "price_sparkline": {
        "market_title": "Arsenal FC vs. Fulham FC: O/U 3.5",
        "outcome_side": "Under",
        "times": [1_700_000_000.0 + i * 3600 for i in range(24)],
        "prices": [0.32 + (i % 5) * 0.02 for i in range(24)],
        "trade_times": [1_700_000_000.0 + 12 * 3600],
        "trade_prices": [0.41],
        "trade_sizes_usd": [13_000.0],
    },
}


_HERO_FETCHER_NAMES = {
    "wallet_record_card": "fetch_wallet_record_card_data",
    "fresh_wallet_card":  "fetch_fresh_wallet_card_data",
    "volume_bar":         "fetch_volume_bar_data",
    "cluster_card":       "fetch_cluster_card_data",
    "price_sparkline":    "fetch_price_sparkline_data",
}


@pytest.mark.parametrize("hero_type", list(_HERO_FAKE_DATA.keys()))
def test_compose_chart_renders_canvas_sized_png_for_every_hero(hero_type):
    """Smoke: every hero type composes a 1200x675 PNG with all 3 tiles drawn.

    Uses synthetic facts_bundle that satisfies enough thresholds for 3 tiles
    to fire (clock + cluster_total + volume_x is the typical winning trio
    after hero-dedup), so each hero panel must coexist with the right column
    without clipping or crashing.
    """
    fb = {
        "minutes_to_resolution": 31,
        "total_usd": 130_000,
        "cluster_size": 4,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.30, "to": 0.41},
        "has_sharp_wallet": {"record": "24-1"},
        "has_fresh_wallet": {"wallet": "0xa", "wallet_age_days": 9},
        "distinct_wallets": 9,
    }
    fake_data = _HERO_FAKE_DATA[hero_type]
    fetcher_name = _HERO_FETCHER_NAMES[hero_type]
    with patch.object(charts, fetcher_name, return_value=fake_data):
        png = chart_grid.compose_chart(
            hero_type=hero_type,
            alert={"id": 1, "wallet": "0xabc", "condition_id": "0xc1d",
                   "market_title": fake_data["market_title"]},
            facts_bundle=fb,
        )
    assert png is not None, f"{hero_type} returned None"
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX), (
        f"{hero_type} produced wrong canvas size: {img.size}")
