"""Smoke tests for chart_grid.compose_chart — assembles hero + tiles into 1200×675."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

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
        "wallet_age_days": 412,
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
            cluster_context={"cluster_total_usd": 220_000, "cluster_size": 7},
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
