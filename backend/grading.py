"""Pure grading + scoreboard aggregation logic — no I/O, no DB, no network.

A "call" is the highest-conviction alert on a resolved market. We grade it
$100-flat, hold-to-resolution: a win returns (1-entry)/entry, a loss -1.0.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

RESOLVED_THRESHOLD = 0.98  # one outcome price >= this => market decided


# Recurring / short-duration crypto price markets (BTC up-or-down, etc.) are
# return-negative coin-flips where copying adds no edge. Excluded from the
# public scoreboard at query time (display-only; rows stay in graded_calls).
JUNK_TAGS = {
    "Crypto", "Crypto Prices", "Recurring", "Bitcoin", "Ethereum",
    "Up or Down", "5M", "Daily", "Weekly", "Hide From New",
}


# "Sharpest in" hook: rank recognizable categories by avg copy return.
META_TAGS = {"Sports", "Games"}   # too broad to read as a "category"
CATEGORY_MIN_CALLS = 20           # meaningful-sample floor
TOP_CATEGORIES = 3


def _row_tags(row) -> set:
    """Parse a graded row's joined alerts.tags (JSON text) into a set of tag
    strings. Tolerates a missing key / None / non-string / malformed JSON by
    returning an empty set (so such rows are never treated as junk)."""
    raw = row.get("tags")
    if isinstance(raw, (list, tuple)):
        return set(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return set()
        return set(parsed) if isinstance(parsed, list) else set()
    return set()


def exclude_junk(rows):
    """Drop rows whose tags intersect JUNK_TAGS (recurring crypto coin-flips)."""
    return [r for r in rows if not (_row_tags(r) & JUNK_TAGS)]


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


def top_categories(rows, window_days: int = 30):
    """Top categories by avg copy return over the windowed rows.

    Aggregates per tag (excluding META_TAGS and JUNK_TAGS), requires at least
    CATEGORY_MIN_CALLS calls, ranks by avg return desc, and returns up to
    TOP_CATEGORIES entries as {name, calls, hit_rate, return_pct}. Pass rows
    that are already junk-excluded; the 30-day window is applied here."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    skip = META_TAGS | JUNK_TAGS
    agg = {}  # tag -> [wins, total, sum_return]
    for r in rows:
        if r["resolved_at"] < cutoff:
            continue
        for tag in _row_tags(r):
            if tag in skip:
                continue
            a = agg.setdefault(tag, [0, 0, 0.0])
            a[0] += 1 if r["won"] else 0
            a[1] += 1
            a[2] += r["return_pct"]
    cats = [
        {
            "name": tag,
            "calls": total,
            "hit_rate": wins / total,
            "return_pct": sr / total,
        }
        for tag, (wins, total, sr) in agg.items()
        if total >= CATEGORY_MIN_CALLS
    ]
    cats.sort(key=lambda c: c["return_pct"], reverse=True)
    return cats[:TOP_CATEGORIES]
