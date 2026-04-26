"""
4-stage Twitter bot: event picker → deterministic data fetch → chart picker → writer.

Run via cron:
    python storybot/twitter_pipeline.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone


def _parse_iso(value) -> datetime | None:
    """Parse a Postgres-shaped timestamp into an aware datetime, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _extract_sharp_wallet(chosen_alerts: list[dict]) -> dict | None:
    """Try llm_copy_action first; fall back to wallet_pnl SQLite lookup if a
    win_rate_tracking signal exists but no record string is in the payload."""
    for a in chosen_alerts:
        copy = a.get("llm_copy_action") or {}
        if isinstance(copy, str):
            try:
                copy = json.loads(copy)
            except json.JSONDecodeError:
                copy = {}
        record = copy.get("wallet_record") or copy.get("record")
        win_pct = copy.get("win_pct") or copy.get("win_rate")
        if record and a.get("wallet"):
            return {
                "wallet": a["wallet"],
                "record": str(record),
                "win_pct": float(win_pct) if win_pct is not None else None,
            }

    # Fallback: any alert has a win_rate_tracking signal? Ask wallet_pnl.
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any((s.get("strategy") == "win_rate_tracking") for s in signals):
            continue
        wallet = a.get("wallet")
        if not wallet:
            continue
        try:
            from bot_utils import query_sqlite
            rows = query_sqlite(
                f"SELECT wins, losses, win_rate FROM wallet_pnl "
                f"WHERE wallet = '{wallet}' LIMIT 1"
            )
        except Exception:
            rows = []
        if rows:
            r = rows[0]
            wins, losses = r.get("wins"), r.get("losses")
            wr = r.get("win_rate")
            if wins is not None and losses is not None:
                return {
                    "wallet": wallet,
                    "record": f"{wins}-{losses}",
                    "win_pct": float(wr) if wr is not None else None,
                }
    return None


def _cluster_size(chosen_alerts: list[dict]) -> int | None:
    """Largest cluster_size implied by wallet_clustering or concentrated_one_sided signals."""
    sizes = []
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") in ("wallet_clustering", "concentrated_one_sided"):
                # severity is roughly the cluster size for these strategies.
                sev = s.get("severity")
                if isinstance(sev, (int, float)) and sev > 0:
                    sizes.append(int(sev))
    return max(sizes) if sizes else None


def _has_volume_spike(chosen_alerts: list[dict]) -> bool:
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") == "pre_event_volume_spike":
                return True
    return False


def _minutes_to_resolution(chosen_alerts: list[dict]) -> int | None:
    """Smallest positive (resolution_time - now) in minutes, across chosen alerts."""
    now = datetime.now(timezone.utc)
    best = None
    for a in chosen_alerts:
        when = _parse_iso(a.get("game_start_time")) or _parse_iso(a.get("event_end_estimate"))
        if when is None:
            continue
        delta_min = int((when - now).total_seconds() // 60)
        if delta_min < 0:
            continue
        if best is None or delta_min < best:
            best = delta_min
    return best


def _dominant_outcome(trades: list[dict]) -> str | None:
    """Outcome with the largest USD share of the trades."""
    if not trades:
        return None
    totals: Counter = Counter()
    for t in trades:
        oc = t.get("outcome")
        if oc:
            totals[oc] += float(t.get("usdcSize") or 0.0)
    if not totals:
        return None
    return totals.most_common(1)[0][0]


def _biggest_price_move(trades: list[dict]) -> dict | None:
    """First→last price on the dominant outcome. None if <2 trades on that outcome."""
    outcome = _dominant_outcome(trades)
    if outcome is None:
        return None
    sub = [t for t in trades if t.get("outcome") == outcome and t.get("price") is not None]
    sub.sort(key=lambda t: float(t.get("timestamp") or 0.0))
    if len(sub) < 2:
        return None
    return {"from": float(sub[0]["price"]), "to": float(sub[-1]["price"])}


def _peak_hour_volume_usd(trades: list[dict]) -> float | None:
    """Max USD across rolling 60-minute windows. None if 0 trades."""
    if not trades:
        return None
    sorted_t = sorted(trades, key=lambda t: float(t.get("timestamp") or 0.0))
    best = 0.0
    left = 0
    running = 0.0
    for right in range(len(sorted_t)):
        running += float(sorted_t[right].get("usdcSize") or 0.0)
        while (float(sorted_t[right].get("timestamp") or 0.0)
               - float(sorted_t[left].get("timestamp") or 0.0)) > 3600:
            running -= float(sorted_t[left].get("usdcSize") or 0.0)
            left += 1
        if running > best:
            best = running
    return best if best > 0 else None


def _time_span_minutes(trades: list[dict]) -> int:
    if not trades:
        return 0
    times = [float(t.get("timestamp") or 0.0) for t in trades if t.get("timestamp")]
    if not times:
        return 0
    return int((max(times) - min(times)) // 60)


def _distinct_wallets(trades: list[dict]) -> int:
    return len({t.get("wallet") for t in trades if t.get("wallet")})


def build_facts_bundle(chosen_alerts: list[dict], trades: list[dict]) -> dict:
    """Derive a small dict of facts for downstream LLM stages to quote precisely.

    All fields gracefully degrade to null/0 when underlying data is missing.
    """
    total_usd = sum(float(t.get("usdcSize") or 0.0) for t in trades)
    return {
        "distinct_wallets": _distinct_wallets(trades),
        "total_usd": total_usd,
        "trade_count": len(trades),
        "time_span_minutes": _time_span_minutes(trades),
        "biggest_price_move": _biggest_price_move(trades),
        "peak_hour_volume_usd": _peak_hour_volume_usd(trades),
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts),
        "cluster_size": _cluster_size(chosen_alerts),
        "has_volume_spike": _has_volume_spike(chosen_alerts),
        "minutes_to_resolution": _minutes_to_resolution(chosen_alerts),
    }


if __name__ == "__main__":
    import sys
    print("twitter_pipeline.py: main() not implemented yet", file=sys.stderr)
    sys.exit(1)
