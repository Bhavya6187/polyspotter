"""
Signal adapter: Alert DB row + joined trades + joined live price → SignalView.

This module is the single source of truth for the design's Signal shape.
When the Alert table changes or when the UI's Signal shape changes, the
mapping is updated HERE and nowhere else.

Shape spec: docs/superpowers/specs/2026-04-17-polyspotter-redesign-design.md §4.1
"""
from __future__ import annotations

import json
import hashlib
from typing import Any

from models import SignalView, SignalMarket, SignalWallet
from topics import topic_for_tags
from pseudonym import alias_for_wallet

_WALLET_PALETTE = ["#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"]


def bucket_rating(score: float | None) -> int:
    """Map composite_score → 1..5 per spec §4.3."""
    s = float(score or 0)
    if s >= 25: return 5
    if s >= 18: return 4
    if s >= 12: return 3
    if s >= 7:  return 2
    return 1


def tier_for_wallet(win_rate: float | None, pnl: float | None) -> str:
    """Classify wallet reputation: legend / sharp / prov (provisional)."""
    w = float(win_rate or 0)
    p = float(pnl or 0)
    if w >= 0.88 and p >= 300_000:
        return "legend"
    if w >= 0.72:
        return "sharp"
    return "prov"


def color_for_wallet(addr: str) -> str:
    """Deterministic color from a wallet address. Lowercased for consistency
    with alias_for_wallet, so checksummed and non-checksummed addresses map
    to the same color."""
    if not addr:
        return _WALLET_PALETTE[0]
    h = hashlib.md5(addr.lower().encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % len(_WALLET_PALETTE)
    return _WALLET_PALETTE[idx]


def return_pct(side: str | None, entry: float | None) -> int:
    """Implied return on the side taken, given entry price.

    YES at E: if resolves YES, share pays $1 → return (1-E)/E.
    NO  at E: if resolves NO,  share pays $1 → return (1-E)/E.
    Same formula — we're quoting entry price of the side taken, not yesPrice.
    """
    if side not in ("YES", "NO"):
        return 0
    if entry is None or entry <= 0 or entry >= 1:
        return 0
    return round((1 - entry) / entry * 100)


def _parse_json_field(raw: Any, default: Any):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def signal_from_row(row: dict, trades: list[dict] | None, live: dict | None) -> SignalView:
    """Build a SignalView from an alerts row + its joined trades + live market data.

    `trades`: list of alert_trades rows (earliest-first recommended).
    `live`:   dict with yes_price, price_change_24h, volume_24h, candles (any may be absent).
    """
    trades = trades or []
    live = live or {}

    tags = _parse_json_field(row.get("tags"), [])
    bullets = _parse_json_field(row.get("llm_bullets"), [])
    # Pad to 3 so the UI can always render three lines.
    while len(bullets) < 3:
        bullets.append("")

    topic, icon = topic_for_tags(tags)

    # Pick the first trade (earliest or largest — use first as canonical).
    t0 = trades[0] if trades else None
    side = None
    entry_price = None
    if t0:
        outcome = (t0.get("outcome") or "").upper()
        if outcome in ("YES", "NO"):
            side = outcome
        entry_price = t0.get("price")

    why = (
        row.get("llm_summary")
        or row.get("cluster_headline")
        or row.get("llm_headline")
        or ""
    )

    addr = row.get("wallet") or ""
    alias = alias_for_wallet(addr) if addr else "ANON"

    market = SignalMarket(
        condition_id=row.get("condition_id"),
        title=row.get("market_title"),
        topic=topic,
        icon=icon,
        end_date=row.get("end_date"),
        yes_price=live.get("yes_price"),
        price_change_24h=float(live.get("price_change_24h") or 0),
        volume_24h=float(live.get("volume_24h") or 0),
        candles=list(live.get("candles") or []),
    )

    wallet = SignalWallet(
        addr=addr,
        alias=alias,
        tier=tier_for_wallet(row.get("win_rate"), row.get("total_pnl")),
        win_rate=float(row.get("win_rate") or 0),
        pnl=float(row.get("total_pnl") or 0),
        bets=int(row.get("trade_count") or 0),
        color=color_for_wallet(addr),
    )

    score = float(row.get("composite_score") or 0)

    # price_now: for YES side, use yes_price; for NO side, use 1 - yes_price.
    # When side is None or yes_price missing, fall back to yes_price.
    yes_price = live.get("yes_price")
    if side == "NO" and yes_price is not None:
        price_now = round(1 - yes_price, 4)
    else:
        price_now = yes_price

    return SignalView(
        id=str(row.get("id")),
        created_at=row.get("created_at"),
        market=market,
        wallet=wallet,
        side=side,
        entry_price=entry_price,
        stake_usd=float(row.get("total_usd") or 0),
        score=score,
        rating=bucket_rating(score),
        why=why,
        signals=[],  # filled by the endpoint from alert_signals rows
        bullets=bullets,
        price_at_alert=entry_price,
        price_now=price_now,
        return_pct=return_pct(side, entry_price),
    )
