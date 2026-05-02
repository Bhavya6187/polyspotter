"""Smoke tests for chart_grid._draw_tile and the standalone tile render."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402


def test_render_tile_produces_valid_png():
    """Standalone render of a single tile produces a 480×225 PNG."""
    spec = chart_grid.TileSpec("clock", "11 MIN", "to tip", accent=True)
    png = chart_grid.render_tile(spec)
    assert isinstance(png, bytes)
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (chart_grid.TILE_W_PX, chart_grid.TILE_H_PX)


def test_render_tile_handles_long_big_label():
    """Long big-label (e.g. price move "32¢ → 41¢") should still render."""
    spec = chart_grid.TileSpec("price_move", "32¢ → 41¢", "price move", accent=True)
    png = chart_grid.render_tile(spec)
    img = Image.open(BytesIO(png))
    assert img.size == (chart_grid.TILE_W_PX, chart_grid.TILE_H_PX)
