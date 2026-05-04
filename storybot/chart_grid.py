"""Chart grid: tile selection, tile rendering, and grid composition.

The grid replaces the single chart attachment for twitter_pipeline.py.
Layout: hero panel (~720×675) on the left + 3 stat tiles (~480×225 each)
stacked on the right, all inside one 1200×675 figure.

Tile selection is deterministic, driven by facts_bundle. Hero choice
remains the LLM's job (twitter_pipeline.pick_chart). See
docs/superpowers/specs/2026-05-01-twitter-pipeline-chart-grid-design.md.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

from dataclasses import dataclass
from io import BytesIO

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


@dataclass(frozen=True)
class TileSpec:
    """Describes one stat tile to be drawn into the right column."""
    kind: str          # "clock" | "cluster_total" | ...
    big: str           # "11 MIN" / "$220K" / "12×" — large display value
    label: str         # "to tip" / "cluster flow" / "usual volume"
    accent: bool       # True → ACCENT (green); False → FG (white)


# Convention: dimensions are public (used by tests / external callers to
# verify output sizes); colors, DPI, and other style internals are private
# (mirrored from charts.py to avoid an import cycle, and deliberately not
# part of this module's public surface).

# ---------- thresholds ----------
CLUSTER_TOTAL_MIN_USD = 25_000
PRICE_MOVE_MIN_DELTA = 0.03
MIN_CLUSTER_SIZE_FOR_TILE = 3
WALLETS_FALLBACK_MIN = 5


# ---------- per-tile builders. Return TileSpec or None. ----------

def _tile_clock(fb: dict) -> TileSpec | None:
    m = fb.get("minutes_to_resolution")
    if m is None:
        return None
    if m < 720:
        return TileSpec("clock", f"{m} MIN", "to close/tip", accent=True)
    hours = m // 60
    return TileSpec("clock", f"{hours}h", "to close", accent=True)


def _tile_cluster_total(fb: dict, hero: str) -> TileSpec | None:
    if hero == "cluster_card":
        return None
    total = float(fb.get("total_usd") or 0.0)
    if total < CLUSTER_TOTAL_MIN_USD:
        return None
    return TileSpec("cluster_total", _fmt_usd_big(total), "cluster flow", accent=False)


def _tile_volume_x(fb: dict, hero: str) -> TileSpec | None:
    if hero == "volume_bar":
        return None
    if not fb.get("has_volume_spike"):
        return None
    mult = fb.get("volume_multiplier_x")
    if mult is None or mult <= 0:
        return None
    big = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    return TileSpec("volume_x", big, "usual volume", accent=True)


def _tile_price_move(fb: dict, hero: str) -> TileSpec | None:
    if hero == "price_sparkline":
        return None
    move = fb.get("biggest_price_move")
    if not move:
        return None
    delta = abs(float(move["to"]) - float(move["from"]))
    if delta < PRICE_MOVE_MIN_DELTA:
        return None
    big = f"{int(round(float(move['from'])*100))}¢ → {int(round(float(move['to'])*100))}¢"
    return TileSpec("price_move", big, "price move", accent=float(move["to"]) >= float(move["from"]))


def _tile_linked_accounts(fb: dict, hero: str) -> TileSpec | None:
    if hero == "cluster_card":
        return None
    n = fb.get("cluster_size")
    if n is None or n < MIN_CLUSTER_SIZE_FOR_TILE:
        return None
    return TileSpec("linked_accounts", f"{n} wallets", "one funder", accent=False)


def _tile_sharp_record(fb: dict, hero: str) -> TileSpec | None:
    if hero == "wallet_record_card":
        return None
    sw = fb.get("has_sharp_wallet")
    if not sw:
        return None
    record = sw.get("record") or ""
    if not record:
        return None
    return TileSpec("sharp_record", record, "sharp wallet", accent=True)


def _tile_fresh_wallet(fb: dict, hero: str) -> TileSpec | None:
    if hero == "fresh_wallet_card":
        return None
    fw = fb.get("has_fresh_wallet")
    if not fw:
        return None
    days = fw.get("wallet_age_days")
    if days is None:
        return None
    return TileSpec("fresh_wallet", f"{days} DAY", "old account", accent=True)


def _tile_wallets(fb: dict) -> TileSpec | None:
    n = fb.get("distinct_wallets") or 0
    if n < WALLETS_FALLBACK_MIN:
        return None
    return TileSpec("wallets", f"{n}", "accounts on event", accent=False)


# ---------- public API ----------

def select_tiles(hero_type: str, facts_bundle: dict) -> list[TileSpec]:
    """Return up to 3 TileSpecs in priority order. Filters by per-tile
    threshold + hero-dedup; takes the first 3 that pass."""
    candidates = [
        _tile_clock(facts_bundle),
        _tile_cluster_total(facts_bundle, hero_type),
        _tile_volume_x(facts_bundle, hero_type),
        _tile_price_move(facts_bundle, hero_type),
        _tile_linked_accounts(facts_bundle, hero_type),
        _tile_sharp_record(facts_bundle, hero_type),
        _tile_fresh_wallet(facts_bundle, hero_type),
        _tile_wallets(facts_bundle),
    ]
    return [c for c in candidates if c is not None][:3]


# ---------- helpers ----------

def _fmt_usd_big(amount: float) -> str:
    """USD shorthand with uppercase K (vs charts._format_usd's lowercase k).
    Tiles use the visually heavier uppercase to read at small sizes."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


# ---------- tile rendering ----------

# Same colors as charts.py — kept duplicated to avoid an import cycle.
_BG = "#0E1117"
_FG = "#FFFFFF"
_ACCENT = "#22C55E"
_MUTED = "#9CA3AF"

TILE_W_PX = 480
TILE_H_PX = 225
_DPI = 100


def _draw_tile(ax, spec: TileSpec) -> None:
    """Draw a stat tile into the given Axes. Two text rows (big number,
    label) and a 2px accent underline at the bottom."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(_BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    big_color = _ACCENT if spec.accent else _FG
    # Auto-shrink the big text when it has more than ~6 chars (e.g. "32¢ → 41¢").
    big = spec.big
    fontsize_big = 80 if len(big) <= 6 else 56
    ax.text(0.5, 0.62, big, color=big_color, fontsize=fontsize_big,
            ha="center", va="center", fontweight="bold")

    ax.text(0.5, 0.28, spec.label, color=_MUTED, fontsize=22,
            ha="center", va="center")

    # Thin accent underline at the bottom — visual rhythm between tile rows.
    accent_color = _ACCENT if spec.accent else _MUTED
    ax.add_patch(Rectangle((0.20, 0.06), 0.60, 0.012,
                            color=accent_color, transform=ax.transAxes))


def render_tile(spec: TileSpec) -> bytes:
    """Standalone tile render at 480×225. Used for tests + render_all_charts."""
    fig = Figure(figsize=(TILE_W_PX / _DPI, TILE_H_PX / _DPI), dpi=_DPI)
    fig.patch.set_facecolor(_BG)
    ax = fig.add_subplot(111)
    _draw_tile(ax, spec)
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
    return buf.getvalue()


# ---------- full grid composition ----------

HERO_W_PX = 720
CANVAS_W_PX = 1200
CANVAS_H_PX = 675

# Hero-type → (fetcher, _draw helper) inside charts.py. Mirror of
# charts._CHART_REGISTRY but with the _draw helpers from this refactor.
def _hero_registry():
    import charts
    return {
        "wallet_record_card": (charts.fetch_wallet_record_card_data,
                               charts._draw_wallet_record_card),
        "fresh_wallet_card":  (charts.fetch_fresh_wallet_card_data,
                               charts._draw_fresh_wallet_card),
        "volume_bar":         (charts.fetch_volume_bar_data,
                               charts._draw_volume_bar),
        "cluster_card":       (charts.fetch_cluster_card_data,
                               charts._draw_cluster_card),
        "price_sparkline":    (charts.fetch_price_sparkline_data,
                               charts._draw_price_sparkline),
    }


def compose_chart(*, hero_type: str, alert: dict, facts_bundle: dict,
                  params: dict | None = None) -> bytes | None:
    """Assemble hero + 3 stat tiles into a 1200×675 PNG.

    Returns None when the hero fetcher returns None (caller falls back to
    "no chart attached"). When zero tiles pass thresholds, renders the
    hero across the full 1200×675 canvas (single-chart fallback).
    """
    registry = _hero_registry()
    pair = registry.get(hero_type)
    if pair is None:
        return None
    fetcher, draw_hero = pair

    try:
        data = fetcher(alert, params=params)
    except Exception:
        return None
    if data is None:
        return None

    tiles = select_tiles(hero_type, facts_bundle)

    fig = Figure(figsize=(CANVAS_W_PX / _DPI, CANVAS_H_PX / _DPI), dpi=_DPI)
    fig.patch.set_facecolor(_BG)

    if not tiles:
        # Fallback: hero spans the full canvas (existing single-chart layout).
        ax_full = fig.add_axes((0, 0, 1, 1))
        try:
            draw_hero(ax_full, data)
        except Exception:
            return None
        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
        return buf.getvalue()

    # Hero region: left HERO_W_PX wide, full height.
    hero_w_frac = HERO_W_PX / CANVAS_W_PX
    ax_hero = fig.add_axes((0, 0, hero_w_frac, 1))
    try:
        draw_hero(ax_hero, data)
    except Exception:
        return None

    # Tile column: one slot per surviving tile, stacked from the top.
    col_x = hero_w_frac
    col_w = 1.0 - hero_w_frac
    n_slots = len(tiles)
    slot_h = 1.0 / n_slots
    for i, spec in enumerate(tiles):
        # Slot 0 is the TOP slot — figure y goes 0 (bottom) to 1 (top).
        y_bottom = 1.0 - (i + 1) * slot_h
        ax_tile = fig.add_axes((col_x, y_bottom, col_w, slot_h))
        _draw_tile(ax_tile, spec)

    # Dividers: thin MUTED lines between hero/tiles and between tile slots.
    # Use figure-level Line2D so they sit above the axes without being
    # clipped by axes spines.
    fig.add_artist(Line2D([hero_w_frac, hero_w_frac], [0, 1],
                          color=_MUTED, linewidth=1, alpha=0.3))
    for i in range(1, n_slots):
        y = 1.0 - i * slot_h
        fig.add_artist(Line2D([hero_w_frac, 1.0], [y, y],
                              color=_MUTED, linewidth=1, alpha=0.3))

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
    return buf.getvalue()
