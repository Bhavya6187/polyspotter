"""Grading worker — one pass, then exit (wrap in a shell sleep loop, like
seo_worker.py). Finds featured markets that have resolved but aren't yet
graded, picks the highest-conviction alert as "the call", determines the
winning outcome from Gamma, and upserts a row into graded_calls.

    while true; do python backend/grade_worker.py; sleep 1800; done

Autocommit connection: no transaction is held open across a Gamma HTTP call.
"""

from __future__ import annotations

import json
import sys
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from database import get_conn  # noqa: E402
from grading import winning_outcome, is_won, copy_return, pick_call  # noqa: E402

GAMMA_API = "https://gamma-api.polymarket.com"
SCORE_THRESHOLD = 2.0   # high-conviction floor for the public track record (NOT the homepage's min-score, which is 0)
BATCH_LIMIT = 50        # markets to consider per pass


def fetch_market(condition_id: str):
    """Return {outcomes: list[str], prices: list[float]} for a market, or None.

    Retries with closed=true because Gamma hides closed markets by default."""
    for params in ({"condition_ids": condition_id},
                   {"condition_ids": condition_id, "closed": "true"}):
        try:
            resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
        except Exception:
            continue
        if not markets:
            continue
        m = markets[0]
        raw_out = m.get("outcomes", "[]")
        raw_prc = m.get("outcomePrices", "[]")
        outcomes = json.loads(raw_out) if isinstance(raw_out, str) else raw_out
        try:
            prices = [float(p) for p in (json.loads(raw_prc) if isinstance(raw_prc, str) else raw_prc)]
        except (ValueError, TypeError):
            prices = []
        return {"outcomes": outcomes or [], "prices": prices}
    return None


def grade_once(conn, fetch=fetch_market) -> int:
    """Grade up to BATCH_LIMIT ungraded featured markets. Returns count graded."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT a.condition_id
            FROM alerts a
            WHERE a.condition_id IS NOT NULL
              AND a.composite_score >= %s
              AND a.llm_copy_action IS NOT NULL
              AND a.llm_copy_action <> '{}'
              AND COALESCE(a.event_end_estimate, a.end_date) <= NOW()
              AND NOT EXISTS (
                  SELECT 1 FROM graded_calls g WHERE g.condition_id = a.condition_id
              )
            ORDER BY a.condition_id
            LIMIT %s
        """, (SCORE_THRESHOLD, BATCH_LIMIT))
        candidate_cids = [r["condition_id"] for r in cur.fetchall()]

    graded = 0
    for cid in candidate_cids:
        try:
            if _grade_market(conn, cid, fetch):
                graded += 1
        except Exception as e:
            print(f"[grade_worker] error grading {cid}: {e}", flush=True)
            continue
    return graded


def _grade_market(conn, cid, fetch) -> bool:
    """Grade a single market. Returns True if a row was graded (inserted),
    False if the market was skipped (no alerts, fetch None, unresolved,
    bad/missing copy_action, bad entry)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, composite_score, event_slug, market_title, llm_copy_action, event_end_estimate
            FROM alerts
            WHERE condition_id = %s AND composite_score >= %s
              AND llm_copy_action IS NOT NULL AND llm_copy_action <> '{}'
        """, (cid, SCORE_THRESHOLD))
        alerts = cur.fetchall()
    if not alerts:
        return False

    market = fetch(cid)
    if not market:
        return False
    resolved = winning_outcome(market["outcomes"], market["prices"])
    if resolved is None:
        return False  # not cleanly decided — leave ungraded, retry next pass

    call = pick_call(alerts)
    try:
        action = json.loads(call["llm_copy_action"])
    except (json.JSONDecodeError, TypeError):
        return False
    outcome = action.get("outcome")
    entry = action.get("entry_price")
    if not outcome or entry is None:
        return False
    try:
        entry = float(entry)
    except (ValueError, TypeError):
        return False
    if not (0 < entry < 1):
        return False

    if not any(is_won(outcome, o) for o in market["outcomes"]):
        print(f"[grade_worker] {cid}: copy outcome {outcome!r} not among "
              f"market outcomes {market['outcomes']}; skipping", flush=True)
        return False

    won = is_won(outcome, resolved)
    ret = copy_return(entry, won)

    resolved_at = call.get("event_end_estimate") or datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO graded_calls
                (condition_id, alert_id, event_slug, market_title, outcome,
                 entry_price, resolved_outcome, won, return_pct, composite_score, resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (condition_id) DO NOTHING
        """, (
            cid, call["id"], call.get("event_slug"), call.get("market_title"),
            outcome, float(entry), resolved, won, ret, call["composite_score"], resolved_at,
        ))
    print(f"[grade_worker] {call.get('market_title')}: "
          f"{'WON' if won else 'LOST'} {ret:+.0%}", flush=True)
    return True


def main() -> int:
    print("[grade_worker] start", flush=True)
    conn = get_conn()
    conn.autocommit = True
    try:
        with closing(conn):
            n = grade_once(conn)
    except Exception as e:
        print(f"[grade_worker] FAILED: {e}", flush=True)
        return 0
    print(f"[grade_worker] done: graded={n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
