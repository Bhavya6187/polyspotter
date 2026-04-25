"""
Chart rendering for storybot/twitter_simple.py.

Four chart types are supported. Each has a typed-dict input, a fetcher that
pulls the data from Postgres / CLOB / Polymarket Data API, and a renderer
that returns PNG bytes. A dispatcher picks the right pair by chart_type.

Visual house style is dark (#0E1117), 1200x675 (16:9 — fits Twitter's
1.91:1 in-feed preview without crop), no gridlines, no chartjunk.
"""
from __future__ import annotations

from io import BytesIO
from typing import TypedDict, Sequence

import matplotlib
matplotlib.use("Agg")  # headless, no display required
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


# ----------------------- House style -----------------------

CHART_TYPES = (
    "price_sparkline",
    "volume_bar",
    "wallet_record_card",
    "cluster_card",
    "none",
)

CANVAS_W_PX = 1200
CANVAS_H_PX = 675
DPI = 100  # 12.0 x 6.75 inches at DPI=100

BG = "#0E1117"
FG = "#FFFFFF"
ACCENT = "#22C55E"   # brand green / size-up / wins
LOSS = "#EF4444"     # red / losses
MUTED = "#9CA3AF"    # axis labels, footer text


def _new_figure() -> tuple[Figure, "plt.Axes"]:
    """Create a 1200x675 figure with the house background. Caller adds content."""
    fig = Figure(figsize=(CANVAS_W_PX / DPI, CANVAS_H_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=MUTED, length=0)
    return fig, ax


def _figure_to_png_bytes(fig: Figure) -> bytes:
    """Serialize a Figure to PNG bytes and close it."""
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=DPI)
    plt.close(fig)
    return buf.getvalue()
