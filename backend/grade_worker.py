"""Grading worker — one pass, then exit (wrap in a shell sleep loop, like
seo_worker.py). Finds featured markets that have resolved but aren't yet
graded, picks the highest-conviction alert as "the call", determines the
winning outcome from Gamma, and upserts a row into graded_calls.

    while true; do python backend/grade_worker.py; sleep 1800; done

Autocommit connection: no transaction is held open across a Gamma HTTP call.

Queue discipline (2026-09): every pass that cannot grade a market records an
attempt in grade_attempts. A market is retried at most once per
ATTEMPT_BACKOFF_HOURS and abandoned after MAX_GRADE_ATTEMPTS, and candidates
are taken newest-ended first. Before this, candidates were taken in
condition_id order with no memory, so 50/50 voids, misspelled LLM outcomes and
team-name outcomes on Yes/No markets sat at the front of the queue forever
(39k markets waiting, 11 graded in 3 days) and the public scoreboard froze.
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

from database import get_conn, _migrate_add_grade_attempts  # noqa: E402
from grading import winning_outcome, is_won, copy_return, pick_call  # noqa: E402

GAMMA_API = "https://gamma-api.polymarket.com"
SCORE_THRESHOLD = 2.0   # high-conviction floor for the public track record (NOT the homepage's min-score, which is 0)
BATCH_LIMIT = 50        # markets to consider per pass
MAX_GRADE_ATTEMPTS = 5  # give up on a market after this many failed passes
ATTEMPT_BACKOFF_HOURS = 24  # minimum gap between passes on the same market


def fetch_market(condition_id: str):
    """Return {outcomes: list[str], prices: list[float], closed: bool} for a
    market, or None.

    Retries with closed=true because Gamma hides closed markets by default.
    `closed` is what tells an in-progress game (one side trading at 0.985)
    apart from a settled one."""
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
        return {"outcomes": outcomes or [], "prices": prices, "closed": bool(m.get("closed"))}
    return None


def ensure_schema(conn) -> None:
    """Create grade_attempts if the backend's init_db hasn't run yet (this
    worker runs from the local working tree, independently of a deploy)."""
    with conn.cursor() as cur:
        _migrate_add_grade_attempts(cur)


def _record_attempt(conn, cid: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO grade_attempts (condition_id, attempts, last_attempt_at, last_reason)
            VALUES (%s, 1, NOW(), %s)
            ON CONFLICT (condition_id) DO UPDATE SET
                attempts = grade_attempts.attempts + 1,
                last_attempt_at = NOW(),
                last_reason = EXCLUDED.last_reason
        """, (cid, reason))


def grade_once(conn, fetch=fetch_market) -> int:
    """Grade up to BATCH_LIMIT ungraded featured markets. Returns count graded."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.condition_id,
                   MAX(COALESCE(a.event_end_estimate, a.end_date)) AS ended_at
            FROM alerts a
            LEFT JOIN grade_attempts ga ON ga.condition_id = a.condition_id
            WHERE a.condition_id IS NOT NULL
              AND a.composite_score >= %s
              AND a.llm_copy_action IS NOT NULL
              AND a.llm_copy_action <> '{}'
              AND COALESCE(a.event_end_estimate, a.end_date) <= NOW()
              AND NOT EXISTS (
                  SELECT 1 FROM graded_calls g WHERE g.condition_id = a.condition_id
              )
              AND (
                  ga.condition_id IS NULL
                  OR (ga.attempts < %s
                      AND ga.last_attempt_at < NOW() - make_interval(hours => %s))
              )
            GROUP BY a.condition_id
            ORDER BY ended_at DESC
            LIMIT %s
        """, (SCORE_THRESHOLD, MAX_GRADE_ATTEMPTS, ATTEMPT_BACKOFF_HOURS, BATCH_LIMIT))
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
    False if the market was skipped (no alerts, fetch None, not closed,
    unresolved, bad/missing copy_action, bad entry). Every skip that depends
    on external state records an attempt so the queue can back off."""
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
        _record_attempt(conn, cid, "gamma_fetch_failed")
        return False
    if not market.get("closed"):
        # One side can trade at 0.98+ while the game is still on; grading
        # then is permanent (ON CONFLICT DO NOTHING) even if it flips.
        _record_attempt(conn, cid, "not_closed_yet")
        return False
    resolved = winning_outcome(market["outcomes"], market["prices"])
    if resolved is None:
        _record_attempt(conn, cid, "unresolved_or_void")
        return False  # 50/50 void or ambiguous — retry later, give up eventually

    call = pick_call(alerts)
    try:
        action = json.loads(call["llm_copy_action"])
    except (json.JSONDecodeError, TypeError):
        _record_attempt(conn, cid, "bad_copy_action")
        return False
    outcome = action.get("outcome")
    entry = action.get("entry_price")
    if not outcome or entry is None:
        _record_attempt(conn, cid, "bad_copy_action")
        return False
    try:
        entry = float(entry)
    except (ValueError, TypeError):
        _record_attempt(conn, cid, "bad_copy_action")
        return False
    if not (0 < entry < 1):
        _record_attempt(conn, cid, "bad_copy_action")
        return False

    if not any(is_won(outcome, o) for o in market["outcomes"]):
        print(f"[grade_worker] {cid}: copy outcome {outcome!r} not among "
              f"market outcomes {market['outcomes']}; skipping", flush=True)
        _record_attempt(conn, cid, "outcome_not_in_market")
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
            ensure_schema(conn)
            n = grade_once(conn)
    except Exception as e:
        print(f"[grade_worker] FAILED: {e}", flush=True)
        return 0
    print(f"[grade_worker] done: graded={n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
