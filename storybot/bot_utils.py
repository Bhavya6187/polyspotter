"""
Shared utilities for storybot and twitter_simple.

Holds the cross-bot non-Twitter surface: env config, logging, read-only
DB access, the Gamma-filtered seed-alert pipeline, picker compaction,
and the LLM usage accumulator.

Twitter-specific machinery (OAuth creds, tweet-length math, client
builders, `tweeted_alerts` recording) lives in `tweet_utils`. Bot-
specific machinery (storybot's research agent loop, twitter_simple's
chart selection, distinct system prompts and validators) lives in the
respective bot modules.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()


# --- Config ------------------------------------------------------------------

POLYBOT_DB_PATH = os.path.join(_REPO_ROOT, "polybot.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
MODEL = os.environ.get("AZURE_OPENAI_MODEL", "")

QUERY_TIMEOUT_SECONDS = 5
MAX_ROWS = 200

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

SEED_CANDIDATE_LIMIT = 50   # pulled from Postgres, then Gamma-filtered
MAX_SEED_ALERTS = 20        # what the model ultimately sees
SETTLED_PRICE_THRESHOLD = 0.98


# --- Logging -----------------------------------------------------------------

def log(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


# --- Read-only DB access -----------------------------------------------------

_BANNED_SQL_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "replace", "attach", "detach", "pragma", "copy",
    "grant", "revoke", "vacuum",
)

_POSTGRES_ONLY_TABLES = (
    "alerts", "alert_trades", "alert_signals", "wallet_profiles",
    "wallet_theses", "tweeted_alerts",
)

_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _check_sqlite_not_postgres(sql: str) -> None:
    lower = _SQL_COMMENT_RE.sub(" ", sql).lower()
    for tbl in _POSTGRES_ONLY_TABLES:
        if re.search(r"\b" + re.escape(tbl) + r"\b", lower):
            raise ValueError(
                f"table '{tbl}' is in Postgres, not SQLite — use query_postgres"
            )


def _guard_read_only(sql: str) -> None:
    """Block anything that isn't a plain SELECT / WITH CTE. Defence in depth —
    the connection is also opened read-only."""
    code = _SQL_COMMENT_RE.sub(" ", sql)
    stripped = code.strip().lower().lstrip("(")
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValueError("only SELECT / WITH queries are allowed")
    tokens = set(
        stripped.replace("(", " ").replace(")", " ").replace(",", " ")
        .replace(";", " ").split()
    )
    bad = sorted(tokens & set(_BANNED_SQL_KEYWORDS))
    if bad:
        raise ValueError(f"banned keyword(s): {bad}")
    if ";" in code.strip().rstrip(";"):
        raise ValueError("multiple statements not allowed")


def query_sqlite(sql: str, params: tuple = ()) -> list[dict]:
    """Read-only SELECT against polybot.db. Returns up to MAX_ROWS rows as dicts."""
    _guard_read_only(sql)
    _check_sqlite_not_postgres(sql)
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = cur.fetchmany(MAX_ROWS)
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_postgres(sql: str) -> list[dict]:
    """Read-only SELECT against Railway Postgres. Returns up to MAX_ROWS rows as dicts."""
    _guard_read_only(sql)
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SET statement_timeout = {QUERY_TIMEOUT_SECONDS * 1000}")
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(sql)
        rows = cur.fetchmany(MAX_ROWS)
        cur.close()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Seed alerts -------------------------------------------------------------

SEED_ALERTS_SQL = f"""
    SELECT a.id, a.alert_type, a.composite_score, a.market_title, a.condition_id,
           a.event_slug, a.wallet, a.total_usd, a.trade_count, a.tags,
           a.market_description, a.end_date, a.game_start_time, a.event_end_estimate,
           a.cluster_headline, a.llm_headline, a.llm_summary, a.llm_bullets,
           a.llm_copy_action, a.seo_summary, a.created_at,
           COALESCE(s.signals, '[]'::jsonb) AS signals
    FROM alerts a
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            jsonb_build_object(
                'strategy', strategy,
                'severity', severity,
                'headline', headline
            ) ORDER BY severity DESC
        ) AS signals
        FROM alert_signals WHERE alert_id = a.id
    ) s ON true
    WHERE a.created_at >= NOW() - INTERVAL '3 hours'
      AND (
          -- Sports markets: pre-kickoff only (drop in-progress games)
          (a.game_start_time IS NOT NULL AND a.game_start_time > NOW())
          -- Non-game markets: resolution deadline still in the future
          OR (a.game_start_time IS NULL
              AND COALESCE(a.event_end_estimate, a.end_date) > NOW())
      )
    ORDER BY a.composite_score DESC
    LIMIT {SEED_CANDIDATE_LIMIT}
"""


def _gamma_status_for_markets(condition_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch {closed, uma_status, max_price} per condition_id from Gamma.

    Two passes: open markets first, then retry the misses with closed=true
    (Gamma hides closed markets by default — without the retry, settled
    games would silently leak through as "unknown"). Degrades gracefully
    on network failure: returns partial results and the caller falls back
    to whatever the SQL filter already caught.
    """
    if not condition_ids:
        return {}
    remaining = list(dict.fromkeys(condition_ids))  # dedup, preserve order
    out: dict[str, dict] = {}

    for extra_params in ({}, {"closed": "true"}):
        if not remaining:
            break
        params: list[tuple[str, str]] = [("condition_ids", cid) for cid in remaining]
        for k, v in extra_params.items():
            params.append((k, v))
        try:
            resp = requests.get(
                f"{GAMMA_BASE_URL}/markets", params=params,
                timeout=QUERY_TIMEOUT_SECONDS * 2,
            )
            resp.raise_for_status()
            markets = resp.json()
        except Exception as exc:
            log("gamma_status_error",
                error=f"{type(exc).__name__}: {exc}",
                pending=len(remaining))
            break

        for m in markets:
            cid = m.get("conditionId")
            if not cid:
                continue
            raw = m.get("outcomePrices") or "[]"
            try:
                prices = json.loads(raw) if isinstance(raw, str) else raw
                max_price = max(float(p) for p in prices) if prices else 0.0
            except (ValueError, TypeError, json.JSONDecodeError):
                max_price = 0.0
            out[cid] = {
                "closed": bool(m.get("closed")),
                "uma_status": (m.get("umaResolutionStatus") or "").strip(),
                "max_price": max_price,
            }
        remaining = [cid for cid in remaining if cid not in out]

    return out


def _is_settled(status: dict | None) -> bool:
    """True if a Gamma market is effectively decided (mirrors backend logic)."""
    if not status:
        return False
    if status.get("closed"):
        return True
    if status.get("uma_status"):
        return True
    return (status.get("max_price") or 0.0) >= SETTLED_PRICE_THRESHOLD


def fetch_seed_alerts() -> list[dict]:
    """Top alerts from the last ~3 hours that are still actionable.

    Pipeline:
      1. Pull up to {SEED_CANDIDATE_LIMIT} candidates from Postgres, filtered by SQL
         to drop obviously-over events (non-sports past resolution deadline;
         sports past kickoff).
      2. Batch-query Gamma /markets for real-time settlement status.
      3. Drop anything Gamma reports as closed, in UMA resolution, or priced
         >= {SETTLED_PRICE_THRESHOLD} (effectively decided by the market).
      4. Return the top {MAX_SEED_ALERTS} survivors by composite_score.
    """
    candidates = query_postgres(SEED_ALERTS_SQL)
    if not candidates:
        return []
    cids = [c["condition_id"] for c in candidates if c.get("condition_id")]
    status_by_cid = _gamma_status_for_markets(cids)

    kept: list[dict] = []
    n_settled = 0
    for row in candidates:
        cid = row.get("condition_id")
        if cid and _is_settled(status_by_cid.get(cid)):
            n_settled += 1
            continue
        kept.append(row)
        if len(kept) >= MAX_SEED_ALERTS:
            break

    log("seed_filter",
        sql_candidates=len(candidates),
        gamma_statuses=len(status_by_cid),
        gamma_settled=n_settled,
        kept=len(kept))
    return kept


# --- Picker compaction -------------------------------------------------------

_PICKER_FIELDS = (
    "id", "alert_type", "composite_score", "market_title", "event_slug",
    "wallet", "total_usd", "trade_count", "tags",
    "llm_headline", "cluster_headline",
    "game_start_time", "event_end_estimate",
)


def _compact_alert_for_picker(alert: dict) -> dict:
    """Trim a full alert row down to the fields the picker needs to judge it."""
    out = {k: alert.get(k) for k in _PICKER_FIELDS if alert.get(k) is not None}
    signals = alert.get("signals") or []
    if signals:
        out["signals"] = [
            {"strategy": s.get("strategy"), "severity": s.get("severity"),
             "headline": s.get("headline")}
            for s in signals if isinstance(s, dict)
        ]
    return out


# --- LLM usage accumulator ---------------------------------------------------

def _accumulate_usage(usage: dict, response) -> None:
    """Add the usage numbers from one chat.completions response to a running total.

    Safe if `response.usage` is None. `cached_prompt_tokens` is sourced from
    `prompt_tokens_details.cached_tokens` when the endpoint reports it (Azure
    OpenAI does — it's how we measure prompt-cache hit rate)."""
    u = getattr(response, "usage", None)
    if u is None:
        return
    usage["requests"] = usage.get("requests", 0) + 1
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + (u.prompt_tokens or 0)
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + (u.completion_tokens or 0)
    usage["total_tokens"] = usage.get("total_tokens", 0) + (u.total_tokens or 0)
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
        usage["cached_prompt_tokens"] = usage.get("cached_prompt_tokens", 0) + cached
    completion_details = getattr(u, "completion_tokens_details", None)
    if completion_details is not None:
        reasoning = getattr(completion_details, "reasoning_tokens", 0) or 0
        usage["reasoning_tokens"] = usage.get("reasoning_tokens", 0) + reasoning
