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

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from database import get_conn  # noqa: E402
from grading import winning_outcome, is_won, copy_return, pick_call  # noqa: E402

GAMMA_API = "https://gamma-api.polymarket.com"
SCORE_THRESHOLD = 2.0   # "featured" floor — matches the homepage list
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
              AND NOT EXISTS (
                  SELECT 1 FROM graded_calls g WHERE g.condition_id = a.condition_id
              )
            ORDER BY a.condition_id
            LIMIT %s
        """, (SCORE_THRESHOLD, BATCH_LIMIT))
        candidate_cids = [r["condition_id"] for r in cur.fetchall()]

    graded = 0
    for cid in candidate_cids:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, composite_score, event_slug, market_title, llm_copy_action
                FROM alerts
                WHERE condition_id = %s AND composite_score >= %s
                  AND llm_copy_action IS NOT NULL AND llm_copy_action <> '{}'
            """, (cid, SCORE_THRESHOLD))
            alerts = cur.fetchall()
        if not alerts:
            continue

        market = fetch(cid)
        if not market:
            continue
        resolved = winning_outcome(market["outcomes"], market["prices"])
        if resolved is None:
            continue  # not cleanly decided — leave ungraded, retry next pass

        call = pick_call(alerts)
        try:
            action = json.loads(call["llm_copy_action"])
        except (json.JSONDecodeError, TypeError):
            continue
        outcome = action.get("outcome")
        entry = action.get("entry_price")
        if not outcome or entry in (None, 0):
            continue

        won = is_won(outcome, resolved)
        ret = copy_return(float(entry), won)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO graded_calls
                    (condition_id, alert_id, event_slug, market_title, outcome,
                     entry_price, resolved_outcome, won, return_pct, composite_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (condition_id) DO NOTHING
            """, (
                cid, call["id"], call.get("event_slug"), call.get("market_title"),
                outcome, float(entry), resolved, won, ret, call["composite_score"],
            ))
        graded += 1
        print(f"[grade_worker] {call.get('market_title')}: "
              f"{'WON' if won else 'LOST'} {ret:+.0%}", flush=True)
    return graded


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
