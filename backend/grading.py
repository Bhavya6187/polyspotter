"""Pure grading + scoreboard aggregation logic — no I/O, no DB, no network.

A "call" is the highest-conviction alert on a resolved market. We grade it
$100-flat, hold-to-resolution: a win returns (1-entry)/entry, a loss -1.0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

RESOLVED_THRESHOLD = 0.98  # one outcome price >= this => market decided


def winning_outcome(outcomes, prices, threshold: float = RESOLVED_THRESHOLD):
    """Return the decided outcome name, or None if not (cleanly) resolved.

    Decided = the outcomes/prices line up and exactly one price >= threshold.
    50-50, still-trading, and ambiguous (multiple winners) markets return None
    (left ungraded)."""
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    above = [i for i, p in enumerate(prices) if p >= threshold]
    if len(above) != 1:
        return None
    return outcomes[above[0]]


def is_won(copy_outcome: str, resolved_outcome: str) -> bool:
    """Case-insensitive match between the call's outcome and the winner."""
    return (copy_outcome or "").strip().lower() == (resolved_outcome or "").strip().lower()


def copy_return(entry_price: float, won: bool) -> float:
    """$100-flat copy return. Win -> (1-entry)/entry, loss -> -1.0."""
    if not won:
        return -1.0
    return (1.0 - entry_price) / entry_price


def pick_call(alerts):
    """The single call for a market = the alert with the highest composite_score."""
    return max(alerts, key=lambda a: a["composite_score"])


def _stats(rows):
    wins = sum(1 for r in rows if r["won"])
    losses = sum(1 for r in rows if not r["won"])
    total = wins + losses
    hit_rate = wins / total if total else 0.0
    copy_return_pct = (sum(r["return_pct"] for r in rows) / total) if total else 0.0
    return {
        "wins": wins,
        "losses": losses,
        "hit_rate": hit_rate,
        "copy_return_pct": copy_return_pct,
    }


def summarize(rows, window_days: int = 30):
    """Aggregate graded rows into {window, all_time}. Equal-weight mean return."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    window_rows = [r for r in rows if r["resolved_at"] >= cutoff]
    return {
        "window_days": window_days,
        "window": _stats(window_rows),
        "all_time": _stats(rows),
    }
