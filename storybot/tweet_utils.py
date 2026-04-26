"""
Twitter-specific helpers for storybot and twitter_simple.

Holds the X/Twitter surface: OAuth credentials, tweet-length math,
URL regexes, banned-phrase list, v1.1 + v2 client builders, and the
`tweeted_alerts` Postgres recording.

Cross-bot non-Twitter machinery (config, DB access, seed-alert
pipeline, picker compaction, LLM usage accumulator) lives in
`bot_utils`.
"""

from __future__ import annotations

import os
import re

import psycopg2
import tweepy
from psycopg2.extras import RealDictCursor

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS


# --- Config ------------------------------------------------------------------

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_KEY_SECRET = os.environ.get("X_CONSUMER_KEY_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

TWEET_MAX_CHARS = 280
TWEET_URL_CHARS = 23   # Twitter t.co wraps every URL to this length, regardless of source length


# --- Tweet text helpers ------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+")
_POLYSPOTTER_URL_RE = re.compile(r"https://polyspotter\.com/(?:market|wallet|alert|tag)/")
_BANNED_TWEET_PHRASES = ("in bio", "full breakdown", "link below", "link in bio")


def _tweet_length(t: str) -> int:
    """Twitter-counted length: every URL counts as TWEET_URL_CHARS regardless of actual length."""
    urls = _URL_RE.findall(t)
    return len(t) - sum(len(u) for u in urls) + TWEET_URL_CHARS * len(urls)


# --- Twitter clients ---------------------------------------------------------

def _x_credentials() -> tuple[str, str, str, str]:
    """The four X/Twitter OAuth1 user creds — single source of truth for both v1 and v2 clients."""
    return X_CONSUMER_KEY, X_CONSUMER_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET


def _build_twitter_client() -> tweepy.Client:
    consumer_key, consumer_secret, access_token, access_token_secret = _x_credentials()
    return tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


def _build_twitter_api_v1() -> tweepy.API:
    """v1.1 client for media upload. The v2 Client used by `_build_twitter_client`
    cannot upload media; v1.1 still owns that endpoint as of this writing."""
    auth = tweepy.OAuth1UserHandler(*_x_credentials())
    return tweepy.API(auth)


# --- Recording ---------------------------------------------------------------

def record_tweet(alert_ids: list[int], tweet_id: str, tweet_text: str) -> None:
    """Insert one tweeted_alerts row per alert. Re-uses the table the existing
    twitter_bot writes to, so both bots share dedup state."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, wallet, condition_id FROM alerts WHERE id = ANY(%s)",
            ([int(i) for i in alert_ids],),
        )
        meta = {r["id"]: (r["wallet"] or "", r["condition_id"] or "") for r in cur.fetchall()}
        rows = [
            (int(i), meta.get(int(i), ("", ""))[0], meta.get(int(i), ("", ""))[1], tweet_id, tweet_text)
            for i in alert_ids
        ]
        cur.executemany(
            """
            INSERT INTO tweeted_alerts (alert_id, wallet, condition_id, tweet_id, tweet_text)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (alert_id) DO NOTHING
            """,
            rows,
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
