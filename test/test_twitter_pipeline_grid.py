"""End-to-end test: prepare_chart_grid composes a 1200x675 PNG."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402
import tweet_utils  # noqa: E402


def test_prepare_chart_grid_returns_canvas_sized_png():
    alert = {"id": 1, "wallet": "0xabc", "market_title": "Lakers vs Rockets",
             "total_usd": 7_000}
    facts_bundle = {
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
    fake_data = {
        "market_title": "Lakers vs Rockets: O/U 206.5",
        "record_str": "24-1",
        "win_pct": 0.96,
        "bet_count": 25,
        "bet_size_usd": 7_000,
        "outcome_side": "Under",
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=fake_data):
        png = tweet_utils.prepare_chart_grid(
            "wallet_record_card", alert, facts_bundle=facts_bundle,
        )
    assert png is not None
    img = Image.open(BytesIO(png))
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
