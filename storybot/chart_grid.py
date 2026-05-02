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
from matplotlib.patches import Rectangle


@dataclass(frozen=True)
class TileSpec:
    """Describes one stat tile to be drawn into the right column."""
    kind: str          # "clock" | "cluster_total" | ...
    big: str           # "11 MIN" / "$220K" / "12×" — large display value
    label: str         # "to tip" / "cluster flow" / "usual volume"
    accent: bool       # True → ACCENT (green); False → FG (white)


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
    """Same as charts._format_usd but caps the K-suffix to 0 decimals."""
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
