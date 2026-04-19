"""
Hourly Twitter bot for PolySpotter.

Runs as a standalone script (Railway cron, once per hour at :00):
    python backend/twitter_bot.py

Flow: fetch last-hour alerts → dedup → send top 5 to GPT-5.4 → either post
a tweet via the X API or skip → record to tweeted_alerts.

Design spec: docs/superpowers/specs/2026-04-19-twitter-bot-design.md
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import psycopg2
import requests
import tweepy
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor


load_dotenv()

# --- Config (from env) --------------------------------------------------------

POLYSPOTTER_API_URL = os.environ.get("POLYSPOTTER_API_URL", "https://api.polyspotter.com")
TWITTER_BOT_MIN_SCORE = float(os.environ.get("TWITTER_BOT_MIN_SCORE", "5.0"))
TWITTER_BOT_DRY_RUN = os.environ.get("TWITTER_BOT_DRY_RUN", "false").lower() == "true"

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_KEY_SECRET = os.environ.get("X_CONSUMER_KEY_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://gpt-5-mati-labs.cognitiveservices.azure.com/openai/v1/"
MODEL = "gpt-5.4"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Time window for candidate alerts (slack beyond exactly 60 minutes to tolerate
# cron drift).
LOOKBACK_MINUTES = 65

# Soft-dedup window: don't tweet same (wallet, condition_id) within this many hours.
SOFT_DEDUP_HOURS = 24

# Hard length cap for tweets (under X's 280 limit, leaves safety margin).
TWEET_MAX_CHARS = 260


# --- Logging ------------------------------------------------------------------

def log_event(event: str, **fields: Any) -> None:
    """Emit a single-line JSON log event to stdout."""
    payload = {"event": event, **fields}
    # Ensure values are JSON-safe.
    print(json.dumps(payload, default=str), flush=True)


# --- Fetch alerts from PolySpotter API ---------------------------------------

def fetch_recent_alerts(api_url: str, min_score: float, *, http=requests) -> list[dict]:
    """Fetch alerts from the hosted API and filter to the last LOOKBACK_MINUTES.

    The API returns alerts sorted by created_at DESC, so we fetch up to 100 and
    client-side filter by `created_at`. Returns a list of AlertOut-shaped dicts.
    """
    resp = http.get(
        f"{api_url}/api/alerts",
        params={"per_page": 100, "min_score": min_score},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    alerts = body.get("alerts", [])

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    recent = []
    for a in alerts:
        ts = a.get("created_at")
        if not ts:
            continue
        # Accept datetime or ISO string; FastAPI returns ISO.
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            parsed = ts
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed >= cutoff:
            recent.append(a)
    return recent


# --- Deduplication -----------------------------------------------------------

def filter_dedup(candidates: list[dict], db_conn) -> list[dict]:
    """Drop candidates that have already been tweeted, or whose
    (wallet, condition_id) pair was tweeted within SOFT_DEDUP_HOURS.

    Runs two queries:
      1. Hard dedup: exact alert_id match.
      2. Soft dedup: (wallet, condition_id) match within the window.
    """
    if not candidates:
        return []

    cur = db_conn.cursor(cursor_factory=RealDictCursor)
    try:
        # 1. Hard dedup: alert_id already tweeted?
        ids = [int(a["id"]) for a in candidates]
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            (ids,),
        )
        hard = {row["alert_id"] for row in cur.fetchall()}

        # 2. Soft dedup: (wallet, condition_id) tweeted recently?
        cutoff = datetime.now(timezone.utc) - timedelta(hours=SOFT_DEDUP_HOURS)
        cur.execute(
            """
            SELECT wallet, condition_id
            FROM tweeted_alerts
            WHERE tweeted_at >= %s
              AND wallet = ANY(%s)
              AND condition_id = ANY(%s)
            """,
            (cutoff, [a.get("wallet") for a in candidates if a.get("wallet")],
             [a.get("condition_id") for a in candidates if a.get("condition_id")]),
        )
        soft = {(row["wallet"], row["condition_id"]) for row in cur.fetchall()}
    finally:
        cur.close()

    kept = []
    for a in candidates:
        if int(a["id"]) in hard:
            continue
        pair = (a.get("wallet"), a.get("condition_id"))
        if pair in soft:
            continue
        kept.append(a)
    return kept


if __name__ == "__main__":
    sys.exit(0)  # placeholder; real main() added in Task 10
