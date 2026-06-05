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
import sqlite3
import sys
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
from matplotlib.patches import Rectangle


# ----------------------- House style -----------------------

CHART_TYPES = (
    "price_sparkline",
    "volume_bar",
    "wallet_record_card",
    "fresh_wallet_card",
    "cluster_card",
    "result_scorecard",
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
    """Serialize a Figure to PNG bytes."""
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=DPI)
    return buf.getvalue()


# ----------------------- wallet_record_card -----------------------

class WalletRecordCardData(TypedDict):
    market_title: str
    record_str: str          # e.g. "29-4"
    win_pct: float           # 0..1
    bet_count: int
    bet_size_usd: float
    outcome_side: str        # "Yes" / "Arsenal" / etc.


def _format_usd(amount: float) -> str:
    """Round dollars for readability: 78131 -> '$78k', 2789285 -> '$2.8M'."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:.0f}"


def _draw_wallet_record_card(ax, data: WalletRecordCardData) -> None:
    """Draw the wallet record card into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Top: market title in muted grey
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero number: prefer record string ("29-4") if win_pct >= 0.7, else show pct.
    hero = data["record_str"] if data["win_pct"] >= 0.7 else f"{data['win_pct']*100:.0f}%"
    ax.text(0.5, 0.62, hero, color=ACCENT, fontsize=110, ha="center", va="center",
            fontweight="bold")

    # Subtitle: count of prior bets.
    subtitle = f"across {data['bet_count']} prior Polymarket bets"
    ax.text(0.5, 0.40, subtitle, color=FG, fontsize=16, ha="center", va="center")

    # Record bar: green for wins, red for losses, sized by win_pct
    bar_y, bar_h = 0.22, 0.06
    ax.add_patch(Rectangle((0.1, bar_y), 0.8 * data["win_pct"], bar_h,
                           color=ACCENT, transform=ax.transAxes))
    ax.add_patch(Rectangle((0.1 + 0.8 * data["win_pct"], bar_y),
                           0.8 * (1 - data["win_pct"]), bar_h,
                           color=LOSS, transform=ax.transAxes))

    # Personal subtitle: bet size + outcome side. Drop "on" when side missing.
    side = (data.get("outcome_side") or "").strip()
    bet_str = _format_usd(data["bet_size_usd"])
    footer = f"{bet_str} on {side}" if side else f"{bet_str} bet"
    ax.text(0.5, 0.10, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")


def render_wallet_record_card(data: WalletRecordCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_wallet_record_card(ax, data)
    return _figure_to_png_bytes(fig)


# ----------------------- result_scorecard -----------------------

class ResultScorecardData(TypedDict):
    verdict: str             # "CASHED" | "BURNED" | "WASH" (classify_outcome
                             # emits only these three; "MIXED" is accepted
                             # defensively — rendered neutrally by the else
                             # branch below — but not currently produced)
    net_pl_usd: float        # signed
    record_str: str          # trade W-L, e.g. "3-1"
    event_label: str         # "Padres-Phillies Over 7.5 runs"
    outcome_side: str        # the side the cluster was on
    flagged_days_ago: int


def _draw_result_scorecard(ax, data: ResultScorecardData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    verdict = (data.get("verdict") or "WASH").upper()
    net = float(data.get("net_pl_usd") or 0.0)
    if verdict == "CASHED":
        color, mark = ACCENT, "✓"   # green check
    elif verdict == "BURNED":
        color, mark = LOSS, "✗"     # red cross
    else:
        color, mark = MUTED, "–"    # neutral en-dash

    sign = "+" if net > 0 else ("-" if net < 0 else "")
    net_str = f"{sign}{_format_usd(abs(net))}" if verdict != "WASH" else "BROKE EVEN"

    ax.text(0.5, 0.74, f"{mark}  {verdict}", color=color, fontsize=58,
            ha="center", va="center", fontweight="bold")
    ax.text(0.5, 0.50, net_str, color=color, fontsize=72,
            ha="center", va="center", fontweight="bold")
    ax.text(0.5, 0.31, data.get("event_label") or "", color=FG, fontsize=26,
            ha="center", va="center", wrap=True)
    side = data.get("outcome_side") or ""
    record = data.get("record_str") or ""
    sub = f"Flagged side: {side}   ·   Trades: {record}" if side else f"Trades: {record}"
    ax.text(0.5, 0.20, sub, color=MUTED, fontsize=20, ha="center", va="center",
            wrap=True)
    days = int(data.get("flagged_days_ago") or 0)
    when = "today" if days <= 0 else (f"{days} day ago" if days == 1
                                      else f"{days} days ago")
    ax.text(0.5, 0.08, f"PolySpotter flagged this {when}", color=MUTED,
            fontsize=18, ha="center", va="center")


def render_result_scorecard(data: ResultScorecardData) -> bytes:
    fig, ax = _new_figure()
    _draw_result_scorecard(ax, data)
    return _figure_to_png_bytes(fig)


# ----------------------- wallet_record_card fetcher -----------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
QUERY_TIMEOUT_SECONDS = 10
WALLET_RECORD_MIN_BETS = 10  # below this, the record isn't a story


def _fetch_wallet_profiles(wallets: list[str]) -> dict[str, dict]:
    """Batch-fetch wallet_profiles. Returns {wallet: profile} only for wallets
    that exist in the table AND have >= WALLET_RECORD_MIN_BETS resolved bets."""
    if not wallets:
        return {}
    placeholders = ",".join(["%s"] * len(wallets))
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT wallet, wins, losses, win_rate, first_seen_at "
            f"FROM wallet_profiles WHERE wallet IN ({placeholders})",
            wallets,
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for wallet, wins, losses, win_rate, first_seen_at in rows:
        wins = wins or 0
        losses = losses or 0
        total_bets = wins + losses
        if total_bets < WALLET_RECORD_MIN_BETS:
            continue
        out[wallet] = {
            "wins": wins,
            "losses": losses,
            "win_rate": float(win_rate or (wins / total_bets if total_bets else 0)),
            "first_seen_at": first_seen_at,
        }
    return out


def fetch_wallet_record_card_data(
    alert: dict,
    *,
    params: dict | None = None,
) -> WalletRecordCardData | None:
    """Build WalletRecordCardData for either a single-wallet or cluster alert.

    Single-wallet (alert['wallet'] set): use that wallet's wallet_profiles row,
    and the alert's total_usd as the bet size in the footer.

    Cluster (alert['wallet'] empty): scan alert['trades'] — the cluster has no
    primary wallet, but the picker may have led with a sharp wallet *inside*
    the cluster. Pick the wallet with the highest win_rate among those meeting
    WALLET_RECORD_MIN_BETS, and show its individual contribution in the footer.

    Returns None when the wallet is unknown / not in the cluster, or has fewer
    than WALLET_RECORD_MIN_BETS resolved bets.

    alert dict fields used:
        wallet          — Polymarket proxy wallet (single-wallet alerts only)
        trades          — list of trade dicts (cluster alerts; required there)
        market_title    — market question string
        total_usd       — bet size for single-wallet alerts
        llm_copy_action — JSON string (or dict) with outcome/side fields
    """
    wallet = alert.get("wallet")
    if wallet:
        profiles = _fetch_wallet_profiles([wallet])
        profile = profiles.get(wallet)
        if profile is None:
            return None
        bet_size = float(alert.get("total_usd", 0))
    else:
        wallet_sizes = _wallets_in_alert(alert)
        if not wallet_sizes:
            return None
        size_by_wallet = dict(wallet_sizes)
        profiles = _fetch_wallet_profiles(list(size_by_wallet.keys()))
        if not profiles:
            return None
        wallet = max(profiles, key=lambda w: profiles[w]["win_rate"])
        profile = profiles[wallet]
        bet_size = size_by_wallet.get(wallet, 0.0)

    wins = profile["wins"]
    losses = profile["losses"]
    total_bets = wins + losses

    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except (json.JSONDecodeError, ValueError):
            copy = {}
    p = params or {}
    outcome_side = (p.get("outcome") or p.get("side")
                    or copy.get("outcome") or copy.get("side") or "")

    return {
        "market_title": alert.get("market_title", ""),
        "record_str": f"{wins}-{losses}",
        "win_pct": profile["win_rate"],
        "bet_count": int(total_bets),
        "bet_size_usd": float(bet_size),
        "outcome_side": outcome_side,
    }


# ----------------------- fresh_wallet_card -----------------------

class FreshWalletCardData(TypedDict):
    market_title: str
    wallet_age_days: int
    bet_size_usd: float
    outcome_side: str


# Mirror of new_wallet_large_bet's freshness threshold (WALLET_AGE_DAYS=30)
# with a small buffer so an alert generated near the cutoff still renders.
FRESH_WALLET_MAX_DAYS = 60
GAMMA_PUBLIC_PROFILE_URL = "https://gamma-api.polymarket.com/public-profile"
POLYMARKET_DATA_API = "https://data-api.polymarket.com"


def _draw_fresh_wallet_card(ax, data: FreshWalletCardData) -> None:
    """Draw the fresh wallet card into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Top: market title in muted grey
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero number: wallet age in days, big green
    days = data["wallet_age_days"]
    ax.text(0.5, 0.62, f"{days}", color=ACCENT, fontsize=140, ha="center", va="center",
            fontweight="bold")

    # Subtitle: "DAY OLD ACCOUNT" / "DAYS OLD ACCOUNT"
    label = "DAY OLD ACCOUNT" if days == 1 else "DAYS OLD ACCOUNT"
    ax.text(0.5, 0.38, label, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")
    ax.text(0.5, 0.30, "on Polymarket", color=MUTED, fontsize=16,
            ha="center", va="center")

    # Footer: bet size + outcome side (drop "on" when side is missing)
    side = (data.get("outcome_side") or "").strip()
    bet_str = _format_usd(data["bet_size_usd"])
    footer = f"{bet_str} on {side}" if side else f"{bet_str} bet"
    ax.text(0.5, 0.12, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")


def render_fresh_wallet_card(data: FreshWalletCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_fresh_wallet_card(ax, data)
    return _figure_to_png_bytes(fig)


def _fetch_wallet_first_trade_at(wallet: str) -> datetime | None:
    """Earliest trade timestamp for a wallet from the Polymarket Data API.

    Used as a fallback for wallet age when Gamma has no public profile —
    a wallet that traded but never went through profile setup has no
    `/public-profile` row, but the Data API still has its trades. The
    detection layer treats those wallets as "very new"; this gives the
    chart a real number to render.

    Data API `/trades` returns desc by timestamp and ignores sort params,
    so we page until we hit a partial/empty page and take the last item.
    Capped at MAX_PAGES because a wallet active enough to need more isn't
    plausibly fresh anyway."""
    if not wallet:
        return None
    PAGE = 500
    MAX_PAGES = 5
    earliest_ts: int | None = None
    offset = 0
    try:
        for _ in range(MAX_PAGES):
            r = requests.get(
                f"{POLYMARKET_DATA_API}/trades",
                params={"user": wallet, "limit": PAGE, "offset": offset},
                timeout=QUERY_TIMEOUT_SECONDS * 2,
            )
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            last_ts = int(chunk[-1].get("timestamp") or 0)
            if last_ts > 0 and (earliest_ts is None or last_ts < earliest_ts):
                earliest_ts = last_ts
            if len(chunk) < PAGE:
                break
            offset += PAGE
    except (requests.RequestException, ValueError) as exc:
        print(
            f"[storybot.charts] _fetch_wallet_first_trade_at failed for {wallet}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if earliest_ts is None:
        return None
    return datetime.fromtimestamp(earliest_ts, tz=timezone.utc)


def _fetch_wallet_created_at(wallet: str) -> datetime | None:
    """Live Gamma /public-profile fetch for a wallet's `createdAt`. Falls
    back to the earliest trade timestamp from the Data API when Gamma has
    no profile row (the user never set up a public profile) or returns no
    usable createdAt. Returns None only on network failure or a wallet
    with neither profile nor trades. Mirrors the freshness logic in
    detection_strategies/new_wallet_large_bet.py, which also treats a 404
    as "very new wallet"."""
    if not wallet:
        return None
    try:
        r = requests.get(
            GAMMA_PUBLIC_PROFILE_URL,
            params={"address": wallet},
            timeout=QUERY_TIMEOUT_SECONDS * 2,
        )
        if r.status_code == 404:
            return _fetch_wallet_first_trade_at(wallet)
        r.raise_for_status()
        profile = r.json()
    except (requests.RequestException, ValueError) as exc:
        print(
            f"[storybot.charts] _fetch_wallet_created_at failed for {wallet}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    created_str = profile.get("createdAt") if isinstance(profile, dict) else None
    if not created_str:
        return _fetch_wallet_first_trade_at(wallet)
    try:
        return datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return _fetch_wallet_first_trade_at(wallet)


def youngest_fresh_wallet(wallets: list[str]) -> tuple[str, int] | None:
    """Pick the wallet with the smallest age (in days) within
    FRESH_WALLET_MAX_DAYS, by Gamma `createdAt`. Returns (wallet, age_days)
    or None when no wallet qualifies. Network failures degrade silently."""
    now = datetime.now(timezone.utc)
    best: tuple[str, int] | None = None
    for w in wallets:
        try:
            ca = _fetch_wallet_created_at(w)
        except Exception:
            continue
        if ca is None:
            continue
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        age_days = (now - ca).days
        if age_days < 0 or age_days > FRESH_WALLET_MAX_DAYS:
            continue
        if best is None or age_days < best[1]:
            best = (w, age_days)
    return best


def fetch_fresh_wallet_card_data(
    alert: dict, *, params: dict | None = None,
) -> FreshWalletCardData | None:
    """Build FreshWalletCardData for either a single-wallet or cluster alert.

    Single-wallet (alert['wallet'] set): use that wallet's age, with the
    alert's total_usd as the bet size in the footer.

    Cluster (alert['wallet'] empty): scan alert['trades'], pick the youngest
    wallet within FRESH_WALLET_MAX_DAYS, and show that wallet's individual
    contribution to the cluster (mirrors the wallet_record_card cluster path).

    Returns None when no wallet qualifies (missing profile, too old, no trades).

    alert dict fields used:
        wallet          — Polymarket proxy wallet (single-wallet alerts only)
        trades          — list of trade dicts (cluster alerts; required there)
        market_title    — market question string
        total_usd       — bet size for single-wallet alerts
        llm_copy_action — JSON string (or dict) with outcome/side fields
    """
    wallet = alert.get("wallet")
    if wallet:
        created_at = _fetch_wallet_created_at(wallet)
        if created_at is None:
            return None
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days < 0 or age_days > FRESH_WALLET_MAX_DAYS:
            return None
        bet_size = float(alert.get("total_usd") or 0)
    else:
        wallet_sizes = _wallets_in_alert(alert)
        if not wallet_sizes:
            return None
        best = youngest_fresh_wallet([w for w, _ in wallet_sizes])
        if best is None:
            return None
        wallet, age_days = best
        bet_size = dict(wallet_sizes).get(wallet, 0.0)

    if bet_size <= 0:
        return None
    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except (json.JSONDecodeError, ValueError):
            copy = {}
    p = params or {}
    outcome_side = (p.get("outcome") or p.get("side")
                    or copy.get("outcome") or copy.get("side") or "")
    return {
        "market_title": alert.get("market_title", ""),
        "wallet_age_days": int(age_days),
        "bet_size_usd": bet_size,
        "outcome_side": outcome_side,
    }


# ----------------------- volume_bar -----------------------

class VolumeBarData(TypedDict):
    market_title: str
    today_volume_usd: float
    baseline_avg_usd: float
    multiplier: float


def _draw_volume_bar(ax, data: VolumeBarData) -> None:
    """Draw the volume bar chart into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    mult = data["multiplier"]
    mult_label = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    ax.text(0.5, 0.72, mult_label, color=ACCENT, fontsize=120, ha="center",
            va="center", fontweight="bold")
    ax.text(0.5, 0.55, "today's volume vs. 7-day average", color=FG, fontsize=20,
            ha="center", va="center")

    today = max(data["today_volume_usd"], 1.0)
    baseline = max(data["baseline_avg_usd"], 1.0)
    today_w = 0.62
    baseline_w = max(0.04, today_w * (baseline / today))

    ax.add_patch(Rectangle((0.1, 0.32), baseline_w, 0.04, color=MUTED,
                           transform=ax.transAxes))
    ax.text(0.1 + baseline_w + 0.02, 0.34,
            f"7-day daily avg: {_format_usd(baseline)}",
            color=MUTED, fontsize=14, ha="left", va="center")

    ax.add_patch(Rectangle((0.1, 0.20), today_w, 0.06, color=ACCENT,
                           transform=ax.transAxes))
    ax.text(0.1 + today_w + 0.02, 0.23,
            f"today: {_format_usd(today)}",
            color=FG, fontsize=16, ha="left", va="center", fontweight="bold")


def render_volume_bar(data: VolumeBarData) -> bytes:
    fig, ax = _new_figure()
    _draw_volume_bar(ax, data)
    return _figure_to_png_bytes(fig)


# ----------------------- volume_bar fetcher -----------------------

GAMMA_API = "https://gamma-api.polymarket.com"
VOLUME_BAR_MIN_TODAY_USD = 1_000
VOLUME_BAR_MIN_MULTIPLIER = 5.0


def _fetch_gamma_volume24hr(condition_id: str) -> float:
    """Live Gamma fetch for `volume24hr`. Returns 0.0 on any failure."""
    if not condition_id:
        return 0.0
    try:
        r = requests.get(
            f"{GAMMA_API}/markets",
            params=[("condition_ids", condition_id)],
            timeout=QUERY_TIMEOUT_SECONDS * 2,
        )
        r.raise_for_status()
        markets = r.json()
        if not markets:
            return 0.0
        return float(markets[0].get("volume24hr") or 0)
    except Exception as exc:
        print(
            f"[storybot.charts] _fetch_gamma_volume24hr failed for {condition_id}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 0.0


def _fetch_baseline_avg_volume(condition_id: str) -> float | None:
    """Read average daily volume baseline from local SQLite market_volume_snapshots.

    Returns None if the DB or table is missing, or if there are no snapshots
    for this market. Cron hosts without polybot.db must not crash."""
    if not condition_id:
        return None
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
        row = conn.execute(
            "SELECT AVG(volume_24h), COUNT(*) FROM market_volume_snapshots "
            "WHERE condition_id = ?",
            (condition_id,),
        ).fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        print(
            f"[storybot.charts] _fetch_baseline_avg_volume: SQLite unavailable "
            f"({type(e).__name__}: {e}); returning None",
            file=sys.stderr,
        )
        return None
    finally:
        if conn is not None:
            conn.close()
    if not row or row[1] == 0 or row[0] is None:
        return None
    return float(row[0])


def fetch_volume_bar_data(
    alert: dict, *, params: dict | None = None,
) -> VolumeBarData | None:
    # `params` is unused — volume_bar shows market-wide volume and has no
    # outcome/side. Accepted for dispatch-signature uniformity.
    del params
    cid = alert.get("condition_id")
    if not cid:
        return None
    today = _fetch_gamma_volume24hr(cid)
    if today < VOLUME_BAR_MIN_TODAY_USD:
        return None
    baseline = _fetch_baseline_avg_volume(cid)
    if baseline is None or baseline <= 0:
        return None
    mult = today / baseline
    if mult < VOLUME_BAR_MIN_MULTIPLIER:
        return None
    return {
        "market_title": alert.get("market_title", ""),
        "today_volume_usd": today,
        "baseline_avg_usd": baseline,
        "multiplier": mult,
    }


# ----------------------- cluster_card -----------------------

class ClusterCardData(TypedDict):
    market_title: str
    outcome_side: str
    wallet_sizes: list[tuple[str, float]]   # (pseudonym, $)
    total_usd: float
    shared_funder: str | None


# Pseudonym helper.
#
# This is a byte-for-byte port of frontend/src/lib/pseudonym.js so the
# Twitter cards show the same wallet name a reader would see on the
# corresponding polyspotter.com page. The JS reference:
#
#   export function walletPseudonym(address, tier) {
#     if (!address) return "Unknown";
#     const prefix = tier?.prefix || "Wallet";
#     const short = address.startsWith("0x")
#       ? address.slice(2, 7) : address.slice(0, 5);
#     return `${prefix}_0x${short}`;
#   }
#
# Tier prefixes (from frontend/src/lib/tiers.js): "Whale", "Sharp",
# "Trader", "Wallet". The bot may not have tier info handy, so the
# default ("Wallet") is the safe choice — it matches what the JS
# returns when no tier is computed.
def wallet_pseudonym(wallet: str | None, tier: dict | None = None) -> str:
    """Stable pseudonym for a wallet address. Mirrors frontend/src/lib/pseudonym.js."""
    if not wallet:
        return "Unknown"
    prefix = (tier or {}).get("prefix") or "Wallet"
    short = wallet[2:7] if wallet.startswith("0x") else wallet[:5]
    return f"{prefix}_0x{short}"


def _draw_cluster_card(ax, data: ClusterCardData) -> None:
    """Draw the cluster card into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.text(0.5, 0.93, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    wallets = data["wallet_sizes"][:8]
    if not wallets:
        return
    max_size = max(w[1] for w in wallets) or 1.0
    bar_top = 0.78
    bar_h = 0.06
    spacing = 0.02
    for i, (name, size_usd) in enumerate(wallets):
        y = bar_top - i * (bar_h + spacing)
        w = 0.55 * (size_usd / max_size)
        ax.add_patch(Rectangle((0.32, y), w, bar_h, color=ACCENT,
                               transform=ax.transAxes))
        ax.text(0.30, y + bar_h / 2, name, color=FG, fontsize=14,
                ha="right", va="center")
        ax.text(0.32 + w + 0.01, y + bar_h / 2, _format_usd(size_usd),
                color=FG, fontsize=14, ha="left", va="center")

    side = (data.get("outcome_side") or "").strip()
    total_fmt = _format_usd(data["total_usd"])
    total_str = f"{total_fmt} on {side}" if side else f"{total_fmt} total"
    ax.text(0.5, 0.16, total_str, color=ACCENT, fontsize=28, ha="center",
            va="center", fontweight="bold")
    if data["shared_funder"]:
        funder = data["shared_funder"]
        funder_disp = funder[:6] + "…" + funder[-4:] if len(funder) > 12 else funder
        ax.text(0.5, 0.08, f"Shared funder: {funder_disp}", color=MUTED,
                fontsize=14, ha="center", va="center")


def render_cluster_card(data: ClusterCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_cluster_card(ax, data)
    return _figure_to_png_bytes(fig)


# ----------------------- cluster_card fetcher -----------------------

CLUSTER_CARD_MIN_WALLETS = 2

# wallet_funders lives in the local SQLite (polybot.db), not in Postgres
# — see db.py and storybot/storybot.py:580. The bot is expected to run
# from the repo root, where polybot.db sits. The path is overridable
# via the POLYBOT_DB_PATH env var (helpful in tests).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLYBOT_DB_PATH = os.environ.get(
    "POLYBOT_DB_PATH", os.path.join(_REPO_ROOT, "polybot.db")
)


def _wallets_in_alert(alert: dict) -> list[tuple[str, float]]:
    """Return [(wallet_address, $size), ...] from the alert's trades JSON, summed per wallet."""
    trades = alert.get("trades")
    if isinstance(trades, str):
        try:
            trades = json.loads(trades)
        except json.JSONDecodeError:
            trades = []
    if not isinstance(trades, list):
        return []
    sums: dict[str, float] = {}
    for t in trades:
        if not isinstance(t, dict):
            continue
        w = t.get("proxyWallet") or t.get("wallet")
        if not w:
            continue
        try:
            size = float(t.get("usdcSize") or t.get("size") or 0)
        except (TypeError, ValueError):
            size = 0.0
        sums[w] = sums.get(w, 0.0) + size
    return sorted(sums.items(), key=lambda kv: kv[1], reverse=True)


def _shared_funder_for_wallets(wallets: list[str]) -> str | None:
    """Look up the most common shared funder across the given wallets in wallet_funders.

    Reads the local SQLite cache (polybot.db). Stored wallets/funders are
    lowercased (see db.py:save_funder), so we lowercase inputs to match.
    Returns the funder address only when at least 2 of the input wallets
    share it (otherwise there's no real "cluster" story).
    """
    if len(wallets) < 2:
        return None
    lower_wallets = [w.lower() for w in wallets]
    placeholders = ",".join("?" * len(lower_wallets))
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
        cur = conn.execute(
            f"""
            SELECT funder, COUNT(*) AS n
            FROM wallet_funders
            WHERE wallet IN ({placeholders}) AND funder IS NOT NULL
            GROUP BY funder
            ORDER BY n DESC
            LIMIT 1
            """,
            lower_wallets,
        )
        row = cur.fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        # Missing db file or missing wallet_funders table: treat as
        # "no shared funder known" rather than crashing the tweet pipeline.
        print(
            f"[storybot.charts] _shared_funder_for_wallets: SQLite unavailable "
            f"({type(e).__name__}: {e}); returning None",
            file=sys.stderr,
        )
        return None
    finally:
        if conn is not None:
            conn.close()
    if not row:
        return None
    funder, n = row
    return funder if n >= 2 else None


def _funder_for_wallet(wallet: str) -> str | None:
    """Look up a single wallet's funder in wallet_funders. Returns None when the
    wallet is unknown, has no recorded funder, or the SQLite cache is missing."""
    if not wallet:
        return None
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
        cur = conn.execute(
            "SELECT funder FROM wallet_funders "
            "WHERE wallet = ? AND funder IS NOT NULL",
            (wallet.lower(),),
        )
        row = cur.fetchone()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        print(
            f"[storybot.charts] _funder_for_wallet: SQLite unavailable "
            f"({type(e).__name__}: {e}); returning None",
            file=sys.stderr,
        )
        return None
    finally:
        if conn is not None:
            conn.close()
    return row[0] if row else None


def _wallets_sharing_funder(funder: str) -> list[str]:
    """All wallets co-funded by `funder` (lowercased addresses).

    Empty list when the funder is unknown or the SQLite cache is missing.
    """
    if not funder:
        return []
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
        cur = conn.execute(
            "SELECT wallet FROM wallet_funders WHERE funder = ?",
            (funder,),
        )
        rows = cur.fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        print(
            f"[storybot.charts] _wallets_sharing_funder: SQLite unavailable "
            f"({type(e).__name__}: {e}); returning []",
            file=sys.stderr,
        )
        return []
    finally:
        if conn is not None:
            conn.close()
    return [r[0] for r in rows if r[0]]


def _fetch_cluster_bets_on_market(condition_id: str,
                                  wallets: list[str]) -> list[tuple[str, float]]:
    """Sum each wallet's stake on `condition_id` from Postgres alert_trades.

    Returns [(wallet, total_usd), ...] sorted by $ descending. Empty list when
    Postgres is unreachable, wallets is empty, or no rows match.
    """
    if not condition_id or not wallets:
        return []
    placeholders = ",".join(["%s"] * len(wallets))
    lower_wallets = [w.lower() for w in wallets]
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    except psycopg2.Error as e:
        print(
            f"[storybot.charts] _fetch_cluster_bets_on_market: postgres "
            f"unavailable ({type(e).__name__}: {e}); returning []",
            file=sys.stderr,
        )
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT LOWER(wallet) AS w, SUM(usd_value) AS total
            FROM alert_trades
            WHERE condition_id = %s AND LOWER(wallet) IN ({placeholders})
            GROUP BY LOWER(wallet)
            """,
            [condition_id] + lower_wallets,
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    sized = [(w, float(t)) for w, t in rows if t is not None and float(t) > 0]
    sized.sort(key=lambda kv: kv[1], reverse=True)
    return sized


def fetch_cluster_card_data(
    alert: dict, *, params: dict | None = None,
) -> ClusterCardData | None:
    """Build ClusterCardData from an alert dict.

    Two paths:
    1) Multi-wallet alert: pull wallets directly from alert['trades'] and
       look for a funder shared across them.
    2) Single-wallet alert tagged with a cluster signal: the cluster's other
       members live on sibling alerts, not in this alert's trades JSON. Look
       up this wallet's funder, fan out to all wallets sharing it, then sum
       each one's stake on this market from alert_trades. Without this path
       the chart picker would pick cluster_card (it keys off signal-derived
       cluster_size) and the fetcher would refuse to render it.

    alert dict fields used:
        wallet          — top-level wallet address (single-wallet alerts)
        condition_id    — required for the sibling-fanout path
        trades          — list of trade dicts (or JSON string)
        market_title    — market question string
        total_usd       — total $ across all trades in the cluster
        llm_copy_action — JSON string (or dict) with outcome/side fields

    Returns None when fewer than CLUSTER_CARD_MIN_WALLETS wallets can be
    assembled or no shared funder is found.
    """
    wallet_sizes_raw = _wallets_in_alert(alert)
    total_override: float | None = None
    if len(wallet_sizes_raw) >= CLUSTER_CARD_MIN_WALLETS:
        funder = _shared_funder_for_wallets([w for w, _ in wallet_sizes_raw])
        if not funder:
            return None  # no shared funder = no real "cluster" story
    else:
        primary = (alert.get("wallet")
                   or (wallet_sizes_raw[0][0] if wallet_sizes_raw else None))
        cid = alert.get("condition_id")
        if not primary or not cid:
            return None
        funder = _funder_for_wallet(primary)
        if not funder:
            return None
        siblings = _wallets_sharing_funder(funder)
        if len(siblings) < CLUSTER_CARD_MIN_WALLETS:
            return None
        wallet_sizes_raw = _fetch_cluster_bets_on_market(cid, siblings)
        if len(wallet_sizes_raw) < CLUSTER_CARD_MIN_WALLETS:
            return None
        total_override = sum(s for _, s in wallet_sizes_raw)

    wallet_sizes = [(wallet_pseudonym(w), s) for w, s in wallet_sizes_raw]

    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except (json.JSONDecodeError, ValueError):
            copy = {}
    p = params or {}
    outcome_side = (p.get("outcome") or p.get("side")
                    or copy.get("outcome") or copy.get("side") or "")

    total_usd = (total_override
                 if total_override is not None
                 else float(alert.get("total_usd", 0)))
    return {
        "market_title": alert.get("market_title", ""),
        "outcome_side": outcome_side,
        "wallet_sizes": wallet_sizes,
        "total_usd": total_usd,
        "shared_funder": funder,
    }


# ----------------------- price_sparkline -----------------------

class PriceSparklineData(TypedDict):
    market_title: str
    outcome_side: str
    times: Sequence[float]            # unix timestamps, ascending
    prices: Sequence[float]           # 0..1, same length as times
    trade_times: Sequence[float]
    trade_prices: Sequence[float]
    trade_sizes_usd: Sequence[float]


def _draw_price_sparkline(ax, data: PriceSparklineData) -> None:
    """Draw the price sparkline into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    times = list(data["times"])
    prices = list(data["prices"])
    if len(times) < 2 or len(times) != len(prices):
        # Defensive — fetcher should have rejected this case.
        return

    # Match the figure background so the sub-axes doesn't paint white
    # over the figure when this draws into a chart_grid sub-region.
    ax.set_facecolor(BG)

    # Title (drop the dash when side is missing). Use ax.text in axes coords
    # so it survives being drawn into a margin-less sub-axes inside
    # chart_grid.compose_chart (ax.set_title renders outside the data area
    # and gets clipped when the axes is placed edge-to-edge).
    side = (data.get("outcome_side") or "").strip()
    title = f"{data['market_title']} — {side}" if side else data["market_title"]
    ax.text(0.5, 0.96, title, color=MUTED, fontsize=18,
            ha="center", va="top", transform=ax.transAxes, wrap=True)

    ax.plot(times, prices, color=ACCENT, linewidth=3)
    if data["trade_times"]:
        sizes = list(data["trade_sizes_usd"]) or [10_000] * len(data["trade_times"])
        scaled = [min(60 + s / 800, 240) for s in sizes]
        ax.scatter(list(data["trade_times"]), list(data["trade_prices"]),
                   s=scaled, color=FG, edgecolor=ACCENT, linewidth=2, zorder=5)

    pmin, pmax = min(prices), max(prices)
    pad = max((pmax - pmin) * 0.15, 0.01)
    ax.set_ylim(max(0, pmin - pad), min(1, pmax + pad))

    # Hide ticks; draw price labels in axes coords so they survive
    # placement inside a margin-less sub-axes.
    ax.set_yticks([])
    ax.set_xticks([])
    ax.text(0.02, 0.10, f"{int(prices[0]*100)}c", color=FG, fontsize=14,
            ha="left", va="center", transform=ax.transAxes, fontweight="bold")
    ax.text(0.98, 0.10, f"{int(prices[-1]*100)}c", color=FG, fontsize=14,
            ha="right", va="center", transform=ax.transAxes, fontweight="bold")
    ax.text(0.02, 0.04, "24h ago", color=MUTED, fontsize=12,
            ha="left", va="bottom", transform=ax.transAxes)
    ax.text(0.98, 0.04, "now", color=MUTED, fontsize=12,
            ha="right", va="bottom", transform=ax.transAxes)


def render_price_sparkline(data: PriceSparklineData) -> bytes:
    fig, ax = _new_figure()
    _draw_price_sparkline(ax, data)
    return _figure_to_png_bytes(fig)


# ----------------------- price_sparkline fetcher -----------------------

CLOB_API = "https://clob.polymarket.com"
SPARKLINE_MIN_POINTS = 2
SPARKLINE_MIN_MOVE = 0.01  # 1 cent


def _fetch_clob_prices_history(token_id: str, hours: int = 24) -> list[tuple[float, float]]:
    """Return [(unix_ts, price), ...] for the last `hours` hours from CLOB."""
    end_ts = int(time.time())
    start_ts = end_ts - hours * 3600
    params = {"market": token_id, "startTs": start_ts, "endTs": end_ts, "fidelity": 60}
    r = requests.get(f"{CLOB_API}/prices-history", params=params, timeout=15)
    r.raise_for_status()
    body = r.json()
    points = body.get("history") if isinstance(body, dict) else body
    if not isinstance(points, list):
        return []
    out: list[tuple[float, float]] = []
    for p in points:
        try:
            out.append((float(p["t"]), float(p["p"])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda kv: kv[0])
    return out


def _yes_token_id(alert: dict, params: dict | None = None) -> str | None:
    """The CLOB price for a market is keyed by the outcome token. Resolve it
    from (in order): cover_chart_spec params, the alert's enriched top-level
    `token_id`, the alert's `llm_copy_action.token_id`, or `alert['tokens']`
    matched against the chosen outcome side."""
    p = params or {}
    if p.get("token_id"):
        return p["token_id"]
    direct = alert.get("token_id")
    if direct:
        return direct
    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except json.JSONDecodeError:
            copy = {}
    if copy.get("token_id"):
        return copy["token_id"]
    tokens = alert.get("tokens")
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except json.JSONDecodeError:
            tokens = None
    if isinstance(tokens, list) and tokens:
        # Prefer the token matching the outcome side; otherwise first.
        side = (p.get("outcome") or p.get("side")
                or copy.get("outcome") or copy.get("side") or "").lower()
        for t in tokens:
            if isinstance(t, dict) and (t.get("outcome") or "").lower() == side:
                return t.get("token_id") or t.get("id")
        first = tokens[0]
        if isinstance(first, dict):
            return first.get("token_id") or first.get("id")
    return None


def fetch_price_sparkline_data(
    alert: dict, *, params: dict | None = None,
) -> PriceSparklineData | None:
    token_id = _yes_token_id(alert, params)
    if not token_id:
        return None
    try:
        history = _fetch_clob_prices_history(token_id, hours=24)
    except requests.RequestException:
        return None
    if len(history) < SPARKLINE_MIN_POINTS:
        return None
    prices = [p for _, p in history]
    if max(prices) - min(prices) < SPARKLINE_MIN_MOVE:
        return None  # nothing visually interesting

    times = [t for t, _ in history]

    trades = alert.get("trades")
    if isinstance(trades, str):
        try:
            trades = json.loads(trades)
        except json.JSONDecodeError:
            trades = []
    if not isinstance(trades, list):
        trades = []

    window_start = times[0]
    trade_times: list[float] = []
    trade_prices: list[float] = []
    trade_sizes: list[float] = []
    for t in trades:
        ts = t.get("timestamp") or t.get("ts") or 0
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        if ts_f < window_start:
            continue
        try:
            tp = float(t.get("price", 0))
            tsize = float(t.get("usdcSize") or t.get("size") or 0)
        except (TypeError, ValueError):
            continue
        trade_times.append(ts_f)
        trade_prices.append(tp)
        trade_sizes.append(tsize)

    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except json.JSONDecodeError:
            copy = {}
    p = params or {}
    return {
        "market_title": alert.get("market_title", ""),
        "outcome_side": (p.get("outcome") or p.get("side")
                         or copy.get("outcome") or copy.get("side") or ""),
        "times": times,
        "prices": prices,
        "trade_times": trade_times,
        "trade_prices": trade_prices,
        "trade_sizes_usd": trade_sizes,
    }


# ----------------------- Dispatcher -----------------------

_CHART_REGISTRY: dict[str, tuple] = {
    "wallet_record_card": (fetch_wallet_record_card_data, render_wallet_record_card),
    "fresh_wallet_card":  (fetch_fresh_wallet_card_data,  render_fresh_wallet_card),
    "volume_bar":         (fetch_volume_bar_data,         render_volume_bar),
    "cluster_card":       (fetch_cluster_card_data,       render_cluster_card),
    "price_sparkline":    (fetch_price_sparkline_data,    render_price_sparkline),
}


def _try_render(chart_type: str, alert: dict,
                params: dict | None = None) -> bytes | None:
    """Try the chart for `chart_type`. Returns bytes or None. Never raises.

    `params` carries chart-specific overrides (`outcome`, `token_id`, ...)
    that the LLM included in cover_chart_spec — fetchers that opt in prefer
    these over what they can derive from the alert dict.
    """
    pair = _CHART_REGISTRY.get(chart_type)
    if not pair:
        return None
    fetcher, renderer = pair
    try:
        data = fetcher(alert, params=params)
    except Exception:
        return None
    if data is None:
        return None
    try:
        return renderer(data)
    except Exception:
        return None


def render_chart_for_alert(chart_type: str, alert: dict,
                           *, params: dict | None = None) -> bytes | None:
    """Try the requested chart. If it fails, fall back to wallet_record_card
    (except for the wallet-shaped charts, which are mutually exclusive with
    a record card — a fresh wallet has no record, and vice versa). Returns
    PNG bytes or None. Never raises.

    `params` mirrors articlebot's cover_chart_spec.params. It is forwarded to
    the fallback as well, so an `outcome` the LLM specified for the primary
    chart still informs the wallet_record_card footer when we degrade.
    """
    if chart_type in ("none", "", None):
        return None
    primary = _try_render(chart_type, alert, params)
    if primary is not None:
        return primary
    if chart_type in ("wallet_record_card", "fresh_wallet_card"):
        return None
    return _try_render("wallet_record_card", alert, params)
