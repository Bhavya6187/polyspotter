"""Persistence + dedup for the accountability-layer tables.

Thin layer over Postgres so result_pipeline.py / publish_result.py can record
settled calls and ask "did we already settle this flag tweet?" without
duplicating SQL. Owns the result_tweets table plus its growth-measurement
satellites: follower_snapshots (daily follower trend) and weekly_scoreboards
(Sunday scoreboard tweet dedup + record). Every public function goes through
`_run` so tests can monkeypatch a single seam.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "")
QUERY_TIMEOUT_SECONDS = 10
_AUDIENCE_TZ = ZoneInfo("America/New_York")

# The single outcome string that counts as a win. Shared so producers
# (publish_result.py) and this win-mapping agree on the literal — a typo
# would otherwise silently classify a win as a loss.
WIN_OUTCOME = "cashed"


def _run(query: str, params: tuple, fetch: bool = False):
    """Execute one statement. Returns list[dict] when fetch, else None."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        cur.close()
        return [dict(r) for r in rows] if fetch else None
    finally:
        conn.close()


def result_exists(original_tweet_id: str) -> bool:
    """True if we've already recorded a result for this flag tweet."""
    rows = _run(
        "SELECT 1 FROM result_tweets WHERE original_tweet_id = %s LIMIT 1",
        (str(original_tweet_id),), fetch=True,
    )
    return bool(rows)


def record_result(*, original_tweet_id: str, result_tweet_id: str | None,
                  alert_ids: list[int], condition_ids: list[str],
                  n_won: int, n_lost: int, net_pl_usd: float,
                  total_invested_usd: float, outcome: str,
                  event_label: str | None) -> None:
    """Insert (or no-op on duplicate) a settled-result row."""
    _run(
        """
        INSERT INTO result_tweets
            (original_tweet_id, result_tweet_id, alert_ids, condition_ids,
             n_won, n_lost, net_pl_usd, total_invested_usd, outcome,
             event_label, posted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (original_tweet_id) DO NOTHING
        """,
        (str(original_tweet_id),
         str(result_tweet_id) if result_tweet_id else None,
         [int(i) for i in alert_ids],
         [str(c) for c in condition_ids],
         int(n_won), int(n_lost), float(net_pl_usd),
         float(total_invested_usd), str(outcome), event_label),
    )


def todays_posted_outcomes(now: datetime) -> list[bool]:
    """is_win flags for results posted on the same ET calendar day as `now`.

    'cashed' -> True (win); anything else -> False. Used to keep the running
    win share near RESULT_WIN_BIAS and to count today's posts against the cap.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(_AUDIENCE_TZ).date()
    # Bind the lookback window to the passed-in `now`, not the DB clock, so the
    # SQL prefilter and the Python ET-day filter agree on which day is "today"
    # even when a caller passes a non-present `now` (backfill/replay).
    window_start = now - timedelta(days=2)
    rows = _run(
        "SELECT posted_at, outcome FROM result_tweets "
        "WHERE posted_at IS NOT NULL AND posted_at >= %s",
        (window_start,), fetch=True,
    ) or []
    out: list[bool] = []
    for r in rows:
        pa = r.get("posted_at")
        if pa is None:
            continue
        if pa.tzinfo is None:
            pa = pa.replace(tzinfo=timezone.utc)
        if pa.astimezone(_AUDIENCE_TZ).date() == today:
            out.append((r.get("outcome") or "") == WIN_OUTCOME)
    return out


# --- Follower snapshots (free-tier growth measurement) ----------------------

def follower_snapshot_exists(snapshot_date: date) -> bool:
    """True if we've already snapshotted follower count for this ET date."""
    rows = _run(
        "SELECT 1 FROM follower_snapshots WHERE snapshot_date = %s LIMIT 1",
        (snapshot_date,), fetch=True,
    )
    return bool(rows)


def record_follower_snapshot(*, snapshot_date: date, followers_count: int,
                             tweet_count: int) -> None:
    """Insert (or no-op on duplicate) one daily follower-count snapshot."""
    _run(
        """
        INSERT INTO follower_snapshots
            (snapshot_date, followers_count, tweet_count)
        VALUES (%s, %s, %s)
        ON CONFLICT (snapshot_date) DO NOTHING
        """,
        (snapshot_date, int(followers_count), int(tweet_count)),
    )


def recent_record(days: int = 30) -> tuple[int, int]:
    """(n_cashed, n_burned) over publicly posted results in the last `days`.

    Counts result_tweets rows (one per settled flag tweet), not trade-level
    n_won/n_lost. 'wash' rows are excluded from both sides.
    """
    rows = _run(
        """
        SELECT COUNT(*) FILTER (WHERE outcome = %s)        AS n_cashed,
               COUNT(*) FILTER (WHERE outcome = 'burned')  AS n_burned
        FROM result_tweets
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - (%s * INTERVAL '1 day')
        """,
        (WIN_OUTCOME, int(days)), fetch=True,
    ) or [{}]
    row = rows[0]
    return int(row.get("n_cashed") or 0), int(row.get("n_burned") or 0)


# --- Weekly scoreboard (Component B of the accountability layer) -------------

def weekly_scoreboard_exists(iso_week: str) -> bool:
    """True if this ISO week's scoreboard tweet was already posted."""
    rows = _run(
        "SELECT 1 FROM weekly_scoreboards WHERE iso_week = %s LIMIT 1",
        (str(iso_week),), fetch=True,
    )
    return bool(rows)


def record_weekly_scoreboard(*, iso_week: str, tweet_id: str | None,
                             n_cashed: int, n_burned: int,
                             net_pl_usd: float) -> None:
    """Insert (or no-op on duplicate) one weekly scoreboard row."""
    _run(
        """
        INSERT INTO weekly_scoreboards
            (iso_week, tweet_id, n_cashed, n_burned, net_pl_usd)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (iso_week) DO NOTHING
        """,
        (str(iso_week), str(tweet_id) if tweet_id else None,
         int(n_cashed), int(n_burned), float(net_pl_usd)),
    )


def weekly_aggregate(days: int = 7) -> dict:
    """{n_cashed, n_burned, net_pl_usd} over results posted in the last
    `days`. Row-level outcomes; 'wash' rows count toward neither side but
    their net P&L (≈0 by definition) is included in the sum."""
    rows = _run(
        """
        SELECT COUNT(*) FILTER (WHERE outcome = %s)        AS n_cashed,
               COUNT(*) FILTER (WHERE outcome = 'burned')  AS n_burned,
               COALESCE(SUM(net_pl_usd), 0)                AS net_pl_usd
        FROM result_tweets
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - (%s * INTERVAL '1 day')
        """,
        (WIN_OUTCOME, int(days)), fetch=True,
    ) or [{}]
    row = rows[0]
    return {"n_cashed": int(row.get("n_cashed") or 0),
            "n_burned": int(row.get("n_burned") or 0),
            "net_pl_usd": float(row.get("net_pl_usd") or 0.0)}
