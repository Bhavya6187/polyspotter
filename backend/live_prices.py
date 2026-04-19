"""
Batch live-price loader. Pulls latest yes_price + recent candles + derived
24h change for a set of condition_ids in one DB round-trip against the
price_candles table.

Used by /api/signals and /api/markets/movers to avoid N+1 fetches.

Note: the schema has no gamma_cache table — live price data comes from the
price_candles time-series table (populated by the scanner). Volume_24h
is not available from price_candles alone and is returned as 0; callers
that need real 24h volume should query Gamma directly per market.
"""
from __future__ import annotations

_DAY_SECONDS = 86400
_CANDLES_PER_MARKET = 32


def _fetch_batch(condition_ids: list[str]) -> dict[str, dict]:
    """Query price_candles for the requested condition_ids.

    Returns: {condition_id: {yes_price, price_change_24h, volume_24h, candles[]}}
    """
    if not condition_ids:
        return {}

    # Lazy import so test collection doesn't require DATABASE_URL.
    from database import get_conn

    conn = get_conn()
    try:
        cur = conn.cursor()
        # Pull the last N*2 points per condition_id; we'll trim to N in Python
        # and pick the YES outcome (if present) or the first outcome otherwise.
        cur.execute(
            """
            SELECT condition_id, outcome, t, p
            FROM price_candles
            WHERE condition_id = ANY(%s)
            ORDER BY condition_id, t DESC
            """,
            (condition_ids,),
        )
        rows = cur.fetchall()
    except Exception:
        return {}
    finally:
        conn.close()

    # Group by condition_id, then by outcome.
    by_cid: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for r in rows:
        cid = r["condition_id"]
        outcome = (r["outcome"] or "").upper() or "YES"
        t = float(r["t"])
        p = float(r["p"])
        by_cid.setdefault(cid, {}).setdefault(outcome, []).append((t, p))

    out: dict[str, dict] = {}
    for cid in condition_ids:
        outcomes = by_cid.get(cid, {})
        # Prefer YES; fall back to first outcome we have.
        series = outcomes.get("YES") or next(iter(outcomes.values()), [])
        if not series:
            continue
        # series is newest-first from the SQL ORDER BY; reverse for display.
        series_asc = list(reversed(series[:_CANDLES_PER_MARKET]))
        candles = [p for _t, p in series_asc]
        latest_t, latest_p = series_asc[-1]
        # 24h change: find the oldest candle within the last ~24h, else use
        # the oldest we have.
        cutoff = latest_t - _DAY_SECONDS
        past_p = next((p for t, p in series_asc if t >= cutoff), series_asc[0][1])
        price_change_24h = round(latest_p - past_p, 4)

        out[cid] = {
            "yes_price": latest_p,
            "price_change_24h": price_change_24h,
            "volume_24h": 0.0,
            "candles": candles,
        }
    return out


def batch_live_for_condition_ids(condition_ids: list[str]) -> dict[str, dict]:
    """Public API. Returns a dict keyed by condition_id; missing ids are absent
    (caller should treat as empty dict)."""
    fetched = _fetch_batch(condition_ids)
    return {cid: fetched.get(cid, {}) for cid in condition_ids}
