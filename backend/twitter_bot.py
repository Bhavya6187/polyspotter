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


# --- LLM composition ---------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the social media voice for PolySpotter, a service that surfaces "
    "notable Polymarket bets from sharp wallets, whales, and coordinated flow.\n\n"

    "You'll be given up to 5 alerts from the last hour. Your job: write ONE "
    "tweet that's as engaging as possible — drawing on one OR multiple alerts "
    "— or skip the hour if nothing is compelling.\n\n"

    "## Single vs composite\n"
    "- If one alert clearly stands out, write a tight hook-driven tweet focused on it.\n"
    "- If 2+ alerts tell a bigger story together (same market, same wallet across "
    "markets, a theme like '3 whales all loaded up on Iran markets today'), "
    "compose a synthesis tweet.\n"
    "- Never force synthesis. If alerts are unrelated, just pick the best one.\n\n"

    "## Tweet rules\n"
    "- Max 260 characters (safety margin under X's 280 limit).\n"
    "- Hook-driven opening: lead with the most striking fact (dollar amount, "
    "win rate, timing).\n"
    "- Use specific numbers, not vague descriptors.\n"
    "- End with a CTA that drives clicks to bio, e.g., "
    "'→ link in bio', 'full details in bio 👀', 'who is this wallet? bio link'.\n"
    "- 1–2 relevant hashtags max. Prefer topic-specific over generic #Polymarket.\n"
    "- 0–2 emojis, only if they add something. No emoji spam.\n"
    "- No URLs. No @mentions of real users.\n"
    "- Never fabricate numbers or facts not in the alert data.\n"
    "- Write like a sharp trading desk analyst, not a corporate account.\n\n"

    "## Skip criteria\n"
    "If all 5 alerts are routine/low-signal, return decision=skip with a short reason.\n\n"

    "## Output format (strict JSON)\n"
    '{\n'
    '  "decision": "post" | "skip",\n'
    '  "reason": "short string",\n'
    '  "alert_ids": [<int>, ...] | null,\n'
    '  "tweet": "<string ≤260 chars | null>",\n'
    '  "is_composite": true | false\n'
    '}\n'
    "alert_ids must be integers taken from the alerts you were shown. "
    "If is_composite=false, alert_ids must contain exactly one id."
)


def _build_user_message(top5: list[dict]) -> str:
    """Build the JSON payload describing the 5 candidate alerts."""
    payload = []
    for a in top5:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "market_title": a.get("market_title"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "wallet_total_pnl": a.get("total_pnl"),
            "total_usd": a.get("total_usd"),
            "tags": a.get("tags") or [],
        })
    return json.dumps({"alerts": payload}, default=str)


def call_llm(top5: list[dict], *, llm_client) -> dict:
    """Send the top 5 alerts to GPT and parse its decision.

    Retries once if the returned tweet exceeds TWEET_MAX_CHARS, asking the model
    to shorten. Returns the raw decision dict (caller is responsible for any
    validation beyond length — e.g. alert_id membership).
    """
    user_msg = _build_user_message(top5)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    decision = _llm_decide(messages, llm_client=llm_client)

    # Length retry (only if decision is 'post' and tweet is over limit).
    tweet = decision.get("tweet") or ""
    if decision.get("decision") == "post" and len(tweet) > TWEET_MAX_CHARS:
        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(decision)},
            {"role": "user", "content": (
                f"Your tweet was {len(tweet)} characters, must be ≤{TWEET_MAX_CHARS}. "
                f"Shorten it, keep the hook and CTA. Return the same JSON format."
            )},
        ]
        decision = _llm_decide(retry_messages, llm_client=llm_client)

    return decision


def _llm_decide(messages: list[dict], *, llm_client) -> dict:
    """Call the model once and parse JSON out of the response."""
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=500,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


# --- Validation --------------------------------------------------------------

def validate_decision(decision: dict, top5_ids: set[int]) -> tuple[bool, str]:
    """Validate the LLM's decision dict. Returns (ok, error_message).

    Rules:
      - decision must be 'post' or 'skip'.
      - if 'skip', nothing else is checked.
      - if 'post':
          - alert_ids must be a non-empty list of ints all present in top5_ids.
          - tweet must be a non-empty string with length <= TWEET_MAX_CHARS.
          - if is_composite is False, alert_ids must have length 1.
    """
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision value: {d!r}"

    alert_ids = decision.get("alert_ids") or []
    if not isinstance(alert_ids, list) or not alert_ids:
        return False, "alert_ids must be a non-empty list when decision=post"

    try:
        int_ids = [int(i) for i in alert_ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {alert_ids!r}"

    unknown = [i for i in int_ids if i not in top5_ids]
    if unknown:
        return False, f"alert_ids contains ids not in input: {unknown}"

    is_composite = bool(decision.get("is_composite"))
    if not is_composite and len(int_ids) != 1:
        return False, "non-composite tweet must reference exactly one alert_id"

    tweet = decision.get("tweet") or ""
    if not isinstance(tweet, str) or not tweet.strip():
        return False, "tweet must be a non-empty string"
    if len(tweet) > TWEET_MAX_CHARS:
        return False, f"tweet length {len(tweet)} exceeds max {TWEET_MAX_CHARS}"

    return True, ""


# --- Twitter client ----------------------------------------------------------

def _build_twitter_client() -> tweepy.Client:
    """Build a real Tweepy v2 client from env credentials (OAuth 1.0a user auth)."""
    return tweepy.Client(
        consumer_key=X_CONSUMER_KEY,
        consumer_secret=X_CONSUMER_KEY_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )


def post_tweet(text: str, *, twitter_client, dry_run: bool) -> str:
    """Post a tweet (or log it in dry-run mode) and return the tweet id.

    In dry-run mode, does not call the client and returns a synthetic id
    starting with 'dryrun-'. The caller uses the dry_run flag to decide
    whether to record the tweet in the DB (dry runs must not poison dedup).
    """
    if dry_run:
        log_event("dry_run_tweet", tweet=text)
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    response = twitter_client.create_tweet(text=text)
    data = getattr(response, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {response!r}")
    return tweet_id


# --- Record ------------------------------------------------------------------

def record_tweet(
    *,
    alerts: list[dict],
    tweet_id: str,
    tweet_text: str,
    db_conn,
) -> None:
    """Insert one tweeted_alerts row per alert, all sharing tweet_id/tweet_text.

    Uses ON CONFLICT DO NOTHING so re-runs (after a DB failure mid-write, for
    example) don't crash. That said, the caller swallows errors from this
    function anyway per the 'record_error' policy.
    """
    rows = [
        (int(a["id"]), a.get("wallet") or "", a.get("condition_id") or "", tweet_id, tweet_text)
        for a in alerts
    ]
    cur = db_conn.cursor()
    try:
        if len(rows) == 1:
            cur.execute(
                """
                INSERT INTO tweeted_alerts (alert_id, wallet, condition_id, tweet_id, tweet_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                rows[0],
            )
        else:
            cur.executemany(
                """
                INSERT INTO tweeted_alerts (alert_id, wallet, condition_id, tweet_id, tweet_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                rows,
            )
    finally:
        cur.close()
    db_conn.commit()


# --- Entrypoint --------------------------------------------------------------

def main(
    *,
    http=None,
    llm_client=None,
    twitter_client=None,
    db_conn=None,
) -> int:
    """Run one pass of the Twitter bot. Returns an exit code (0 = success, 1 = error).

    All dependencies can be injected for testing. When any are None, the real
    versions are constructed from environment config.
    """
    run_id = uuid.uuid4().hex[:8]
    log_event("run_start", run_id=run_id,
              api_url=POLYSPOTTER_API_URL,
              min_score=TWITTER_BOT_MIN_SCORE,
              dry_run=TWITTER_BOT_DRY_RUN)

    # Lazy-construct real deps if not injected.
    if http is None:
        http = requests
    owns_conn = False
    if db_conn is None:
        db_conn = psycopg2.connect(DATABASE_URL)
        owns_conn = True
    if llm_client is None:
        llm_client = OpenAI(
            base_url=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
        )
    if twitter_client is None:
        twitter_client = _build_twitter_client()

    try:
        # 1. Fetch.
        try:
            candidates = fetch_recent_alerts(POLYSPOTTER_API_URL, TWITTER_BOT_MIN_SCORE, http=http)
        except Exception as e:
            log_event("fetch_error", run_id=run_id, error=str(e))
            return 1

        log_event("candidates_fetched", run_id=run_id, count=len(candidates))

        # 2. Dedup.
        after_dedup = filter_dedup(candidates, db_conn)
        log_event("after_dedup", run_id=run_id, count=len(after_dedup))

        # 3. Top 5 by composite_score.
        top5 = sorted(after_dedup, key=lambda a: a.get("composite_score", 0), reverse=True)[:5]
        if not top5:
            log_event("no_candidates", run_id=run_id)
            log_event("run_end", run_id=run_id, posted=False, reason="no_candidates")
            return 0

        # 4. LLM.
        try:
            decision = call_llm(top5, llm_client=llm_client)
        except Exception as e:
            log_event("llm_error", run_id=run_id, error=str(e))
            return 1

        if decision.get("decision") == "skip":
            log_event("llm_skip", run_id=run_id, reason=decision.get("reason"))
            log_event("run_end", run_id=run_id, posted=False, reason="llm_skip")
            return 0

        # 5. Validate.
        top5_ids = {int(a["id"]) for a in top5}
        ok, err = validate_decision(decision, top5_ids)
        if not ok:
            log_event("validation_error", run_id=run_id, error=err, decision=decision)
            return 1

        # 6. Post.
        picked_ids = [int(i) for i in decision["alert_ids"]]
        picked_alerts = [a for a in top5 if int(a["id"]) in picked_ids]
        tweet_text = decision["tweet"]
        try:
            tweet_id = post_tweet(tweet_text, twitter_client=twitter_client, dry_run=TWITTER_BOT_DRY_RUN)
        except Exception as e:
            log_event("post_error", run_id=run_id, error=str(e))
            return 1

        log_event("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=picked_ids,
                  is_composite=bool(decision.get("is_composite")))

        # 7. Record (skip in dry run).
        if TWITTER_BOT_DRY_RUN:
            log_event("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id)
            return 0

        try:
            record_tweet(alerts=picked_alerts, tweet_id=tweet_id, tweet_text=tweet_text, db_conn=db_conn)
        except Exception as e:
            log_event("record_error", run_id=run_id, error=str(e))
            # Intentionally still success: the tweet is already live.
            log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False)
            return 0

        log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True)
        return 0
    finally:
        if owns_conn:
            try:
                db_conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
