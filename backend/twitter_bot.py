"""
Hourly Twitter bot for PolySpotter.

Runs as a standalone script (Railway cron, once per hour at :00):
    python backend/twitter_bot.py

Flow: fetch last-hour alerts → dedup → send top 20 to GPT-5.4 → either post
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


# The scanner's db module lives at the repo root; add it to sys.path so we can
# import polybot.db for SQLite-backed agent tools.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

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
    """Drop candidates whose alert_id has already been tweeted."""
    if not candidates:
        return []

    cur = db_conn.cursor(cursor_factory=RealDictCursor)
    try:
        ids = [int(a["id"]) for a in candidates]
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            (ids,),
        )
        hard = {row["alert_id"] for row in cur.fetchall()}
    finally:
        cur.close()

    return [a for a in candidates if int(a["id"]) not in hard]


# --- LLM composition ---------------------------------------------------------

def call_llm(
    top_alerts: list[dict],
    *,
    llm_client,
    db_conn_pg=None,
    db_conn_sqlite=None,
    http=None,
    run_id: str | None = None,
    on_stage1_complete=None,
):
    """Orchestrate stage 1 → stage 2 and return (ShortlistDecision, decision_dict).

    Stage 1: select_shortlist picks 2-4 alerts (or skips). On invalid output or
    LLM exception, falls back to a deterministic top-3-by-score shortlist.

    Stage 2: compose_tweet researches the shortlist and writes the tweet.
    Length-retry is applied to the stage-2 output.

    Returns:
        (shortlist_decision, decision_dict). On stage-1 skip, the decision dict
        is {"decision": "skip", "reason": shortlist_decision.reason} and stage 2
        is not invoked.
    """
    from twitter_bot_agent import (
        compose_tweet, select_shortlist,
        ShortlistValidationError, ToolDeps,
    )

    log_event("stage1_start", run_id=run_id, input_count=len(top_alerts))

    # --- Stage 1 ---
    fallback = False
    try:
        shortlist_decision = select_shortlist(top_alerts, llm_client=llm_client)
    except ShortlistValidationError as exc:
        log_event("stage1_invalid", run_id=run_id, validation_error=str(exc)[:500])
        shortlist_decision = _build_fallback_shortlist(top_alerts)
        log_event("stage1_fallback", run_id=run_id, error=str(exc)[:500])
        fallback = True
    except Exception as exc:
        shortlist_decision = _build_fallback_shortlist(top_alerts)
        log_event("stage1_fallback", run_id=run_id, error=f"{type(exc).__name__}: {exc}"[:500])
        fallback = True

    log_event(
        "stage1_result",
        run_id=run_id,
        decision=shortlist_decision.decision,
        mode=shortlist_decision.mode,
        shortlist_ids=(
            [item.alert_id for item in shortlist_decision.shortlist]
            if shortlist_decision.shortlist else None
        ),
        reason=shortlist_decision.reason,
        fallback=fallback,
    )

    if on_stage1_complete is not None:
        on_stage1_complete(shortlist_decision)

    if shortlist_decision.decision == "skip":
        return shortlist_decision, {
            "decision": "skip",
            "reason": shortlist_decision.reason,
        }

    # --- Stage 2 ---
    deps = ToolDeps(
        http=http if http is not None else requests,
        api_url=POLYSPOTTER_API_URL,
        db_conn_pg=db_conn_pg,
        db_conn_sqlite=db_conn_sqlite,
    )

    def _on_tool_call(name: str, args: dict, envelope: dict) -> None:
        if TWITTER_BOT_DRY_RUN:
            proj = args.get("projection")
            other = {k: v for k, v in args.items() if k != "projection"}
            err = envelope.get("error")
            status = f"ERROR: {err}" if err else "ok"
            line = f"  tool  {name}  {other}"
            if proj:
                line += f"\n        proj: {proj}"
            line += f"\n        → {status}"
            print(line, flush=True)
            return
        log_event(
            "tool_call",
            run_id=run_id,
            name=name,
            args=args,
            error=envelope.get("error"),
            truncated=envelope.get("truncated", False),
        )

    decision = compose_tweet(
        top_alerts,
        llm_client=llm_client,
        deps=deps,
        shortlist_decision=shortlist_decision,
        on_tool_call=_on_tool_call,
    )

    tweet = decision.get("tweet") or ""
    if decision.get("decision") == "post" and len(tweet) > TWEET_MAX_CHARS:
        decision = _shorten_tweet(decision, top_alerts, shortlist_decision, llm_client=llm_client)

    return shortlist_decision, decision


def _stage1_run_end_fields(shortlist_decision) -> dict:
    """Build the stage1_mode + stage1_fallback fields for run_end log events.

    On no_candidates (shortlist_decision is None), both fields are absent/defaults.
    On stage-1 skip, stage1_mode is None (the decision has no mode).
    Otherwise, stage1_mode is the committed mode and stage1_fallback reflects
    whether this came from _build_fallback_shortlist.
    """
    if shortlist_decision is None:
        return {"stage1_mode": None, "stage1_fallback": False}
    return {
        "stage1_mode": shortlist_decision.mode,
        "stage1_fallback": shortlist_decision.fallback,
    }


def _build_fallback_shortlist(top_alerts: list[dict]):
    """Top-3 by composite_score, mode=single, no angles. Used on stage-1 failure."""
    from twitter_bot_agent import ShortlistDecision, ShortlistItem
    sorted_alerts = sorted(
        top_alerts, key=lambda a: a.get("composite_score", 0), reverse=True,
    )
    picks = sorted_alerts[:3]
    items = [ShortlistItem(alert_id=int(a["id"]), angle="") for a in picks]
    return ShortlistDecision(
        decision="shortlist",
        reason="stage-1 fallback: top by composite_score",
        mode="single",
        shortlist=items,
        fallback=True,
    )


def _shorten_tweet(decision: dict, top_alerts: list[dict], shortlist_decision, *, llm_client) -> dict:
    """One-shot non-agentic call to shorten an over-length tweet."""
    from twitter_bot_agent import SYSTEM_PROMPT, build_user_message
    original = decision.get("tweet") or ""
    shortlisted_ids = {item.alert_id for item in shortlist_decision.shortlist}
    filtered = [a for a in top_alerts if int(a["id"]) in shortlisted_ids]
    selection = {
        "mode": shortlist_decision.mode,
        "angles": {str(item.alert_id): item.angle for item in shortlist_decision.shortlist},
    }
    retry_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(filtered, selection=selection)},
        {"role": "assistant", "content": json.dumps(decision)},
        {"role": "user", "content": (
            f"Your tweet was {len(original)} characters, must be ≤{TWEET_MAX_CHARS}. "
            f"Shorten it, keep the hook and CTA. Return the same JSON format — "
            f"no tool calls, just the final JSON."
        )},
    ]
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=retry_messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=500,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


# --- Validation --------------------------------------------------------------

def validate_decision(
    decision: dict,
    shortlisted_ids: set[int],
    mode: str,
) -> tuple[bool, str]:
    """Validate the LLM's stage-2 decision dict. Returns (ok, error_message).

    Args:
        decision: the dict returned by compose_tweet.
        shortlisted_ids: the set of alert IDs stage 1 shortlisted (the only
            valid alert IDs the tweet may reference).
        mode: "single" or "composite", from the ShortlistDecision.

    Rules:
      - decision must be 'post' or 'skip'.
      - if 'skip', nothing else is checked (mode-agnostic).
      - if 'post':
          - alert_ids must be a non-empty list of ints, all ∈ shortlisted_ids.
          - tweet must be a non-empty string with length <= TWEET_MAX_CHARS.
          - mode='single':    len(alert_ids) == 1 AND is_composite is False.
          - mode='composite': set(alert_ids) == shortlisted_ids AND is_composite is True.
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

    unknown = [i for i in int_ids if i not in shortlisted_ids]
    if unknown:
        return False, f"alert_ids contains ids not in shortlist: {unknown}"

    is_composite = bool(decision.get("is_composite"))

    if mode == "single":
        if len(int_ids) != 1:
            return False, f"single-mode tweet must reference exactly one alert_id, got {len(int_ids)}"
        if is_composite:
            return False, "single-mode tweet must have is_composite=false"
    elif mode == "composite":
        if set(int_ids) != shortlisted_ids:
            return False, (
                f"composite-mode tweet must reference all shortlisted ids "
                f"{sorted(shortlisted_ids)}, got {sorted(int_ids)}"
            )
        if not is_composite:
            return False, "composite-mode tweet must have is_composite=true"
    else:
        return False, f"unknown mode: {mode!r}"

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
        top_alerts = sorted(after_dedup, key=lambda a: a.get("composite_score", 0), reverse=True)[:20]
        if not top_alerts:
            log_event("no_candidates", run_id=run_id)
            log_event("run_end", run_id=run_id, posted=False, reason="no_candidates",
                      **_stage1_run_end_fields(None))
            return 0

        if TWITTER_BOT_DRY_RUN:
            print(f"\n--- Top {len(top_alerts)} candidate alerts ---", flush=True)
            for i, a in enumerate(top_alerts, 1):
                wallet = a.get("wallet")
                if wallet and wallet.startswith("0x") and len(wallet) > 12:
                    wallet_display = f"{wallet[:6]}…{wallet[-4:]}"
                elif wallet:
                    wallet_display = wallet
                else:
                    wallet_display = "(cluster)"
                win = a.get("win_rate")
                win_display = f"{win * 100:.0f}%" if win is not None else "  -"
                market = (a.get("market_title") or "")[:60]
                print(
                    f"  {i}. #{int(a['id']):<6}  "
                    f"score={a.get('composite_score', 0):>5.2f}  "
                    f"${a.get('total_usd', 0):>9,.0f}  "
                    f"wr={win_display:<4}  {wallet_display:<14}  {market}",
                    flush=True,
                )
                if a.get("llm_headline"):
                    print(f"       → {a['llm_headline']}", flush=True)
            print("", flush=True)

        # 4. LLM (two-stage agentic composer).
        from db import get_db as _get_sqlite_db
        try:
            db_conn_sqlite = _get_sqlite_db()
        except Exception as e:
            log_event("sqlite_open_error", run_id=run_id, error=str(e))
            db_conn_sqlite = None

        def _on_stage1(sd):
            if not TWITTER_BOT_DRY_RUN:
                return
            if sd.decision == "skip":
                print(f"\n--- Stage 1 skip: {sd.reason} ---", flush=True)
                return
            if sd.fallback:
                print(
                    f"\n--- Stage 1 fallback: {sd.reason} — using top-{len(sd.shortlist)} by score ---",
                    flush=True,
                )
            else:
                print(
                    f"\n--- Stage 1 selection: {sd.mode} ({len(sd.shortlist)} alerts) ---",
                    flush=True,
                )
                print(f"  → reason: {sd.reason}", flush=True)
            for item in sd.shortlist:
                print(f"  #{item.alert_id}  {item.angle}", flush=True)
            print("", flush=True)

        try:
            shortlist_decision, decision = call_llm(
                top_alerts,
                llm_client=llm_client,
                db_conn_pg=db_conn,
                db_conn_sqlite=db_conn_sqlite,
                http=http,
                run_id=run_id,
                on_stage1_complete=_on_stage1,
            )
        except Exception as e:
            log_event("llm_error", run_id=run_id, stage=2, error=str(e))
            return 1

        if decision.get("decision") == "skip":
            stage = 1 if shortlist_decision.decision == "skip" else 2
            log_event("llm_skip", run_id=run_id, stage=stage, reason=decision.get("reason"))
            log_event(
                "run_end", run_id=run_id, posted=False, reason="llm_skip",
                **_stage1_run_end_fields(shortlist_decision),
            )
            return 0

        # 5. Validate.
        shortlisted_ids = {item.alert_id for item in shortlist_decision.shortlist}
        ok, err = validate_decision(decision, shortlisted_ids, shortlist_decision.mode)
        if not ok:
            log_event("validation_error", run_id=run_id, error=err, decision=decision)
            return 1

        # 6. Post.
        picked_ids = [int(i) for i in decision["alert_ids"]]
        picked_alerts = [a for a in top_alerts if int(a["id"]) in picked_ids]
        tweet_text = decision["tweet"]
        try:
            tweet_id = post_tweet(tweet_text, twitter_client=twitter_client, dry_run=TWITTER_BOT_DRY_RUN)
        except Exception as e:
            log_event("post_error", run_id=run_id, error=str(e))
            return 1

        log_event("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=picked_ids,
                  is_composite=bool(decision.get("is_composite")))

        print(f"\n--- Final tweet ({len(tweet_text)} chars) ---\n{tweet_text}\n", flush=True)

        # 7. Record (skip in dry run).
        if TWITTER_BOT_DRY_RUN:
            log_event("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
                      **_stage1_run_end_fields(shortlist_decision))
            return 0

        try:
            record_tweet(alerts=picked_alerts, tweet_id=tweet_id, tweet_text=tweet_text, db_conn=db_conn)
        except Exception as e:
            log_event("record_error", run_id=run_id, error=str(e))
            # Intentionally still success: the tweet is already live.
            log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
                      **_stage1_run_end_fields(shortlist_decision))
            return 0

        log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
                  **_stage1_run_end_fields(shortlist_decision))
        return 0
    finally:
        if owns_conn:
            try:
                db_conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
