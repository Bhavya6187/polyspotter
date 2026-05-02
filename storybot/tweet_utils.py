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

import json
import os
import re

import psycopg2
import requests
import tweepy
from psycopg2.extras import RealDictCursor

import chart_grid
import charts
from bot_utils import DATABASE_URL, GAMMA_BASE_URL, QUERY_TIMEOUT_SECONDS, log


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
_BANNED_TWEET_PHRASES = ("in bio", "full breakdown", "link below", "more at", "link in bio")


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


# --- URL helpers -------------------------------------------------------------

_POLYSPOTTER_URL_STRIP_RE = re.compile(
    r"\s*https://polyspotter\.com/(?:market|wallet|alert|tag)/\S+"
)


def strip_polyspotter_url(tweet: str) -> str:
    """Remove polyspotter.com deep links (and any leading whitespace) before posting."""
    return _POLYSPOTTER_URL_STRIP_RE.sub("", tweet).rstrip()


# --- Dedup ------------------------------------------------------------------

def already_tweeted_ids(alert_ids: list[int]) -> set[int]:
    """Return the subset of alert_ids that already have a row in tweeted_alerts."""
    if not alert_ids:
        return set()
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            ([int(i) for i in alert_ids],),
        )
        rows = cur.fetchall()
        cur.close()
        return {int(r[0]) for r in rows}
    finally:
        conn.close()


def filter_posted_alerts(seed_alerts: list[dict]) -> list[dict]:
    """Drop seed alerts that have already been tweeted (by any bot)."""
    ids = [int(a["id"]) for a in seed_alerts if a.get("id") is not None]
    posted = already_tweeted_ids(ids)
    return [a for a in seed_alerts if int(a.get("id") or 0) not in posted]


# --- Chart prep -------------------------------------------------------------

def fetch_alert_trades(alert_id: int) -> list[dict]:
    """Fetch all trades for one alert from Postgres alert_trades, shaped like the Polymarket Data API."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wallet, outcome, side, usd_value, size, price,
                   EXTRACT(EPOCH FROM trade_timestamp) AS ts,
                   transaction_hash
            FROM alert_trades WHERE alert_id = %s
            """,
            (alert_id,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    out = []
    for w, oc, sd, usd, sz, pr, ts, txh in rows:
        out.append({
            "wallet": w,
            "outcome": oc,
            "side": sd,
            "usdcSize": float(usd) if usd is not None else 0.0,
            "size": float(sz) if sz is not None else 0.0,
            "price": float(pr) if pr is not None else 0.0,
            "timestamp": float(ts) if ts is not None else 0.0,
            "transaction_hash": txh,
        })
    return out


def fetch_market_tokens(condition_id: str) -> dict[str, str]:
    """Live Gamma fetch: return {outcome_name: token_id}. Empty dict on failure."""
    if not condition_id:
        return {}
    try:
        r = requests.get(
            f"{GAMMA_BASE_URL}/markets",
            params=[("condition_ids", condition_id)],
            timeout=QUERY_TIMEOUT_SECONDS * 2,
        )
        r.raise_for_status()
        markets = r.json()
        if not markets:
            return {}
        m = markets[0]
        outcomes = m.get("outcomes")
        token_ids = m.get("clobTokenIds")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if not (isinstance(outcomes, list) and isinstance(token_ids, list)):
            return {}
        return {o: t for o, t in zip(outcomes, token_ids) if o and t}
    except Exception as exc:
        log("market_tokens_fetch_error",
            condition_id=condition_id,
            error=f"{type(exc).__name__}: {exc}")
        return {}


def enrich_alert_for_charts(alert: dict) -> None:
    """Populate alert['trades'] and alert['token_id'] in-place. Failures are silent."""
    alert_id = alert.get("id")
    if alert_id is None:
        return
    try:
        alert["trades"] = fetch_alert_trades(int(alert_id))
    except Exception as exc:
        log("alert_trades_fetch_error",
            alert_id=alert_id, error=f"{type(exc).__name__}: {exc}")
        alert["trades"] = []

    cid = alert.get("condition_id")
    if not cid:
        return
    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except json.JSONDecodeError:
            copy = {}
    side = copy.get("outcome") or copy.get("side")
    if not side:
        return
    tokens = fetch_market_tokens(cid)
    if side in tokens:
        alert["token_id"] = tokens[side]


def prepare_chart(chart_type: str, alert: dict) -> bytes | None:
    """Render a chart for one alert. Returns PNG bytes or None. Never raises.

    Caller is responsible for resolving which alert + chart_type to render.
    """
    if not alert:
        return None
    enrich_alert_for_charts(alert)
    try:
        return charts.render_chart_for_alert(chart_type, alert)
    except Exception as exc:
        log("chart_render_error",
            error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=alert.get("id"))
        return None


def prepare_chart_grid(chart_type: str, alert: dict,
                       *,
                       facts_bundle: dict) -> bytes | None:
    """Render a hero+tiles grid for one alert. Returns PNG bytes or None.
    Never raises.

    Used by twitter_pipeline. articlebot continues to call prepare_chart
    (single-chart) until/unless we choose to migrate it later.
    """
    if not alert:
        return None
    enrich_alert_for_charts(alert)
    try:
        return chart_grid.compose_chart(
            hero_type=chart_type,
            alert=alert,
            facts_bundle=facts_bundle,
        )
    except Exception as exc:
        log("chart_grid_render_error",
            error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=alert.get("id"))
        return None


# --- Posting ----------------------------------------------------------------

def post_tweet(
    text: str,
    *,
    twitter_client,
    twitter_api_v1=None,
    media_png: bytes | None = None,
    dry_run: bool,
) -> str:
    """Post a single tweet, optionally with one PNG attached. Returns the tweet id."""
    import uuid
    if dry_run:
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    media_ids = None
    if media_png is not None and twitter_api_v1 is not None:
        from io import BytesIO
        media = twitter_api_v1.media_upload(filename="chart.png", file=BytesIO(media_png))
        media_id = getattr(media, "media_id", None) or getattr(media, "media_id_string", None)
        if media_id:
            media_ids = [media_id]

    if media_ids:
        resp = twitter_client.create_tweet(text=text, media_ids=media_ids)
    else:
        resp = twitter_client.create_tweet(text=text)
    data = getattr(resp, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {resp!r}")
    return tweet_id
