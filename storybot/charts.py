"""
Chart rendering for storybot/twitter_simple.py.

Four chart types are supported. Each has a typed-dict input, a fetcher that
pulls the data from Postgres / CLOB / Polymarket Data API, and a renderer
that returns PNG bytes. A dispatcher picks the right pair by chart_type.

Visual house style is dark (#0E1117), 1200x675 (16:9 — fits Twitter's
1.91:1 in-feed preview without crop), no gridlines, no chartjunk.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import TypedDict, Sequence

import matplotlib
matplotlib.use("Agg")  # headless, no display required
import matplotlib.pyplot as plt
import psycopg2
import requests
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


# ----------------------- wallet_record_card -----------------------

class WalletRecordCardData(TypedDict):
    market_title: str
    record_str: str          # e.g. "29-4"
    win_pct: float           # 0..1
    bet_count: int
    wallet_age_days: int | None
    bet_size_usd: float
    outcome_side: str        # "Yes" / "Arsenal" / etc.


def _format_usd(amount: float) -> str:
    """Round dollars for readability: 78131 -> '$78k', 2789285 -> '$2.8M'."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:.0f}"


def render_wallet_record_card(data: WalletRecordCardData) -> bytes:
    fig, ax = _new_figure()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    # Top: market title in muted grey
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero number: prefer record string ("29-4") if win_pct >= 0.7, else show pct.
    hero = data["record_str"] if data["win_pct"] >= 0.7 else f"{data['win_pct']*100:.0f}%"
    ax.text(0.5, 0.62, hero, color=ACCENT, fontsize=110, ha="center", va="center",
            fontweight="bold")

    # Subtitle: count of prior bets
    age_str = (
        f", {data['wallet_age_days']}-day-old account" if data["wallet_age_days"] is not None
        else ""
    )
    subtitle = f"across {data['bet_count']} prior Polymarket bets{age_str}"
    ax.text(0.5, 0.40, subtitle, color=FG, fontsize=20, ha="center", va="center")

    # Record bar: green for wins, red for losses, sized by win_pct
    bar_y, bar_h = 0.22, 0.06
    ax.add_patch(plt.Rectangle((0.1, bar_y), 0.8 * data["win_pct"], bar_h,
                               color=ACCENT, transform=ax.transAxes))
    ax.add_patch(plt.Rectangle((0.1 + 0.8 * data["win_pct"], bar_y),
                               0.8 * (1 - data["win_pct"]), bar_h,
                               color=LOSS, transform=ax.transAxes))

    # Footer: bet size + outcome side
    footer = f"{_format_usd(data['bet_size_usd'])} on {data['outcome_side']}"
    ax.text(0.5, 0.10, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")

    return _figure_to_png_bytes(fig)


# ----------------------- wallet_record_card fetcher -----------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
QUERY_TIMEOUT_SECONDS = 10
WALLET_RECORD_MIN_BETS = 10  # below this, the record isn't a story


def fetch_wallet_record_card_data(alert: dict) -> WalletRecordCardData | None:
    """Build WalletRecordCardData from an alert dict and Postgres wallet_profiles.

    Queries `wallet_profiles` in Railway Postgres (the authoritative win/loss
    store pushed by polybot). Returns None when the wallet is unknown or has
    fewer than WALLET_RECORD_MIN_BETS resolved bets.

    alert dict fields used:
        wallet          — Polymarket proxy wallet address
        market_title    — market question string
        total_usd       — size of the bet in USD
        llm_copy_action — JSON string (or dict) with outcome/side fields
    """
    wallet = alert.get("wallet")
    if not wallet:
        return None

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wins, losses, win_rate, first_seen_at
            FROM wallet_profiles
            WHERE wallet = %s
            """,
            (wallet,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return None
    wins, losses, win_rate, first_seen_at = row
    wins = wins or 0
    losses = losses or 0
    total_bets = wins + losses
    if total_bets < WALLET_RECORD_MIN_BETS:
        return None

    # Derive wallet age from first_seen_at if available
    wallet_age_days: int | None = None
    if first_seen_at is not None:
        try:
            if isinstance(first_seen_at, str):
                first_seen_at = datetime.fromisoformat(first_seen_at)
            if first_seen_at.tzinfo is None:
                first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
            wallet_age_days = (datetime.now(timezone.utc) - first_seen_at).days
        except (ValueError, TypeError, AttributeError):
            wallet_age_days = None

    # Parse llm_copy_action (may arrive as JSON string or dict)
    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except (json.JSONDecodeError, ValueError):
            copy = {}
    outcome_side = copy.get("outcome") or copy.get("side") or ""

    return {
        "market_title": alert.get("market_title", ""),
        "record_str": f"{wins}-{losses}",
        "win_pct": float(win_rate or (wins / total_bets if total_bets else 0)),
        "bet_count": int(total_bets),
        "wallet_age_days": wallet_age_days,
        "bet_size_usd": float(alert.get("total_usd", 0)),
        "outcome_side": outcome_side,
    }


# ----------------------- volume_bar -----------------------

class VolumeBarData(TypedDict):
    market_title: str
    today_volume_usd: float
    baseline_avg_usd: float
    multiplier: float


def render_volume_bar(data: VolumeBarData) -> bytes:
    fig, ax = _new_figure()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    # Title
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero multiplier
    mult = data["multiplier"]
    mult_label = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    ax.text(0.5, 0.72, mult_label, color=ACCENT, fontsize=120, ha="center", va="center",
            fontweight="bold")
    ax.text(0.5, 0.55, "today's volume vs. 7-day average", color=FG, fontsize=20,
            ha="center", va="center")

    # Two horizontal bars — baseline tiny, today full-width
    # Map widths to a log-friendly visual: baseline always >= 4% of bar area for visibility.
    today = max(data["today_volume_usd"], 1.0)
    baseline = max(data["baseline_avg_usd"], 1.0)
    today_w = 0.8
    baseline_w = max(0.04, today_w * (baseline / today))

    ax.add_patch(plt.Rectangle((0.1, 0.32), baseline_w, 0.04, color=MUTED,
                               transform=ax.transAxes))
    ax.text(0.1 + baseline_w + 0.02, 0.34,
            f"7-day daily avg: {_format_usd(baseline)}",
            color=MUTED, fontsize=14, ha="left", va="center")

    ax.add_patch(plt.Rectangle((0.1, 0.20), today_w, 0.06, color=ACCENT,
                               transform=ax.transAxes))
    ax.text(0.1 + today_w + 0.02, 0.23,
            f"today: {_format_usd(today)}",
            color=FG, fontsize=16, ha="left", va="center", fontweight="bold")

    return _figure_to_png_bytes(fig)


# ----------------------- volume_bar fetcher -----------------------

POLYMARKET_DATA_API = "https://data-api.polymarket.com"
VOLUME_BAR_MIN_TODAY_USD = 1_000
VOLUME_BAR_MIN_MULTIPLIER = 5.0


def _fetch_market_volume_window(condition_id: str, start_ts: int, end_ts: int) -> float:
    """Sum trade $ on a market between two unix timestamps. Paginated."""
    total = 0.0
    cursor = ""
    page_size = 500
    while True:
        params = {
            "market": condition_id,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": page_size,
        }
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{POLYMARKET_DATA_API}/trades", params=params, timeout=15)
        r.raise_for_status()
        body = r.json()
        rows = body if isinstance(body, list) else body.get("data", [])
        for row in rows:
            size = row.get("usdcSize") or row.get("size") or 0
            try:
                total += float(size)
            except (TypeError, ValueError):
                continue
        next_cursor = body.get("nextCursor", "") if isinstance(body, dict) else ""
        if not next_cursor or len(rows) < page_size:
            break
        cursor = next_cursor
    return total


def fetch_volume_bar_data(alert: dict) -> VolumeBarData | None:
    cid = alert.get("condition_id")
    if not cid:
        return None

    now = int(time.time())
    today_start = now - 86_400
    week_start = now - 86_400 * 8
    week_end = now - 86_400

    today = _fetch_market_volume_window(cid, today_start, now)
    if today < VOLUME_BAR_MIN_TODAY_USD:
        return None
    baseline_total = _fetch_market_volume_window(cid, week_start, week_end)
    baseline_avg = baseline_total / 7.0
    if baseline_avg <= 0:
        return None
    mult = today / baseline_avg
    if mult < VOLUME_BAR_MIN_MULTIPLIER:
        return None

    return {
        "market_title": alert.get("market_title", ""),
        "today_volume_usd": today,
        "baseline_avg_usd": baseline_avg,
        "multiplier": mult,
    }
