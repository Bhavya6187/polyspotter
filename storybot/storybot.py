"""
Hourly "story" bot for PolySpotter.

Fetches the last 3 hours of alerts from Railway Postgres, researches them using
four tools (SQLite / Postgres / Gamma API / CLOB API), and writes an engaging
3-5 tweet thread — not an alert recap but a short, specific story about what
a sharp bettor is doing and why it matters.

Four agent tools:
    - query_sqlite(sql)             — read-only SELECT against polybot.db
    - query_postgres(sql)           — read-only SELECT against Railway Postgres
    - call_gamma(path, params)      — GET against gamma-api.polymarket.com
    - call_clob(path, params)       — GET against clob.polymarket.com (price history + book)

Run via cron (once per hour):
    python storybot/storybot.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from typing import Any

import psycopg2
import requests
import tweepy
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()


# --- Config ------------------------------------------------------------------

POLYBOT_DB_PATH = os.path.join(_REPO_ROOT, "polybot.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_KEY_SECRET = os.environ.get("X_CONSUMER_KEY_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://gpt-5-mati-labs.cognitiveservices.azure.com/openai/v1/"
MODEL = "gpt-5.4"

STORYBOT_DRY_RUN = os.environ.get("STORYBOT_DRY_RUN", "false").lower() == "true"

TWEET_MAX_CHARS = 280
QUERY_TIMEOUT_SECONDS = 5
MAX_ROWS = 200
RESPONSE_CAP_BYTES = 12288   # 12 KB per tool response
MAX_TOOL_CALLS = 22
MAX_ITERATIONS = 20

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
GAMMA_PATH_ALLOWLIST = ("/markets", "/events", "/trades")

CLOB_BASE_URL = "https://clob.polymarket.com"
CLOB_PATH_ALLOWLIST = ("/prices-history", "/book")


# --- Logging -----------------------------------------------------------------

def log(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


# --- The three tools ---------------------------------------------------------

_BANNED_SQL_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "replace", "attach", "detach", "pragma", "copy",
    "grant", "revoke", "vacuum",
)

_POSTGRES_ONLY_TABLES = (
    "alerts", "alert_trades", "alert_signals", "wallet_profiles",
    "wallet_theses", "tweeted_alerts",
)


def _check_sqlite_not_postgres(sql: str) -> None:
    lower = sql.lower()
    for tbl in _POSTGRES_ONLY_TABLES:
        if re.search(r"\b" + re.escape(tbl) + r"\b", lower):
            raise ValueError(
                f"table '{tbl}' is in Postgres, not SQLite — use query_postgres"
            )


def _guard_read_only(sql: str) -> None:
    """Block anything that isn't a plain SELECT / WITH CTE. Defence in depth —
    the connection is also opened read-only."""
    stripped = sql.strip().lower().lstrip("(")
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValueError("only SELECT / WITH queries are allowed")
    tokens = set(
        stripped.replace("(", " ").replace(")", " ").replace(",", " ")
        .replace(";", " ").split()
    )
    bad = sorted(tokens & set(_BANNED_SQL_KEYWORDS))
    if bad:
        raise ValueError(f"banned keyword(s): {bad}")
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("multiple statements not allowed")


def query_sqlite(sql: str) -> list[dict]:
    """Read-only SELECT against polybot.db. Returns up to MAX_ROWS rows as dicts."""
    _guard_read_only(sql)
    _check_sqlite_not_postgres(sql)
    uri = f"file:{POLYBOT_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
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


SEED_CANDIDATE_LIMIT = 50   # pulled from Postgres, then Gamma-filtered
MAX_SEED_ALERTS = 20        # what the model ultimately sees
GAME_LIVE_BUFFER_HOURS = 3  # matches backend /top3 — covers soccer/NBA/esports BO3
SETTLED_PRICE_THRESHOLD = 0.98

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
          -- Sports markets: pre-kickoff OR within {GAME_LIVE_BUFFER_HOURS}h of kickoff
          (a.game_start_time IS NOT NULL
           AND a.game_start_time + INTERVAL '{GAME_LIVE_BUFFER_HOURS} hours' > NOW())
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
         sports past kickoff+{GAME_LIVE_BUFFER_HOURS}h).
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


_MARKET_FIELDS_KEEP = (
    "id", "conditionId", "slug", "question",
    "outcomes", "outcomePrices",
    "volume", "volumeNum", "volume24hr", "volume1wk",
    "liquidity", "liquidityNum",
    "startDate", "endDate", "endDateIso", "gameStartTime",
    "bestBid", "bestAsk", "lastTradePrice", "spread",
    "oneHourPriceChange", "oneDayPriceChange",
    "oneWeekPriceChange", "oneMonthPriceChange",
    "clobTokenIds",
    "active", "closed", "archived", "negRisk",
    "groupItemTitle", "line", "sportsMarketType",
)

_EVENT_FIELDS_KEEP = (
    "id", "slug", "title", "ticker",
    "startDate", "endDate", "eventDate", "startTime",
    "volume", "volume24hr", "liquidity",
    "active", "closed", "archived", "negRisk",
)


def _slim_market(m: dict) -> dict:
    out = {k: m[k] for k in _MARKET_FIELDS_KEEP if k in m}
    evts = m.get("events")
    if isinstance(evts, list):
        out["events"] = [
            {k: e.get(k) for k in ("id", "slug", "title", "endDate") if k in e}
            for e in evts if isinstance(e, dict)
        ]
    return out


def _slim_event(e: dict) -> dict:
    out = {k: e[k] for k in _EVENT_FIELDS_KEEP if k in e}
    tags = e.get("tags")
    if isinstance(tags, list):
        out["tags"] = [
            {k: t.get(k) for k in ("id", "label", "slug") if k in t}
            for t in tags if isinstance(t, dict)
        ]
    markets = e.get("markets")
    if isinstance(markets, list):
        out["markets"] = [_slim_market(m) for m in markets if isinstance(m, dict)]
    return out


def _slim_gamma_response(path: str, data: Any) -> Any:
    """Strip verbose fields (descriptions, series, clobRewards, eventMetadata
    prose, etc.) from Gamma /markets and /events responses. Keeps the
    tradeable fields the storybot actually uses."""
    if "/tags" in path or path.startswith("/trades"):
        return data
    if path.startswith("/markets"):
        if isinstance(data, list):
            return [_slim_market(m) if isinstance(m, dict) else m for m in data]
        if isinstance(data, dict):
            return _slim_market(data)
    if path.startswith("/events"):
        if isinstance(data, list):
            return [_slim_event(e) if isinstance(e, dict) else e for e in data]
        if isinstance(data, dict):
            return _slim_event(data)
    return data


def _slim_clob_book(data: Any) -> Any:
    """Cap /book responses to top 20 levels per side (by best price)."""
    if not isinstance(data, dict):
        return data
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    out = dict(data)
    out["bids"] = sorted(bids, key=lambda b: float(b.get("price", 0)), reverse=True)[:20]
    out["asks"] = sorted(asks, key=lambda a: float(a.get("price", 0)))[:20]
    if len(bids) > 20 or len(asks) > 20:
        out["original_depth"] = {"bids": len(bids), "asks": len(asks)}
    return out


def _summarize_prices_history(data: Any) -> Any:
    """Prepend a `summary` dict (first/last/min/max price + delta + n_points)
    to /prices-history responses so the model doesn't have to scan the series
    to make a price-move claim."""
    if not isinstance(data, dict):
        return data
    history = data.get("history") or []
    if not history:
        return data
    prices = [pt["p"] for pt in history if isinstance(pt, dict) and "p" in pt]
    if not prices:
        return data
    first_p = history[0].get("p")
    last_p = history[-1].get("p")
    return {
        "summary": {
            "first_t": history[0].get("t"),
            "first_p": first_p,
            "last_t": history[-1].get("t"),
            "last_p": last_p,
            "min_p": min(prices),
            "max_p": max(prices),
            "abs_change": round((last_p or 0) - (first_p or 0), 6),
            "n_points": len(history),
        },
        "history": history,
    }


def call_gamma(path: str, params: dict | None = None) -> Any:
    """Generic GET to gamma-api.polymarket.com. Allowlist: /markets, /events, /trades."""
    if not path.startswith("/") or ".." in path or "//" in path:
        raise ValueError("path not allowed")
    if not any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in GAMMA_PATH_ALLOWLIST):
        raise ValueError(f"path must start with one of {GAMMA_PATH_ALLOWLIST}")
    resp = requests.get(f"{GAMMA_BASE_URL}{path}", params=params or None,
                        timeout=QUERY_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return _slim_gamma_response(path, resp.json())


def call_clob(path: str, params: dict | None = None) -> Any:
    """Generic GET to clob.polymarket.com. Allowlist: /prices-history, /book."""
    if not path.startswith("/") or ".." in path or "//" in path:
        raise ValueError("path not allowed")
    if not any(path == p or path.startswith(p + "?") for p in CLOB_PATH_ALLOWLIST):
        raise ValueError(f"path must be one of {CLOB_PATH_ALLOWLIST}")
    resp = requests.get(f"{CLOB_BASE_URL}{path}", params=params or None,
                        timeout=QUERY_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    if path.startswith("/book"):
        return _slim_clob_book(data)
    if path.startswith("/prices-history"):
        return _summarize_prices_history(data)
    return data


# --- Tool envelope + dispatch -----------------------------------------------

def _envelope(data: Any = None, *, error: str | None = None) -> dict:
    """Build a tool-response envelope. Truncates to RESPONSE_CAP_BYTES when JSON-serialized."""
    if error is not None:
        return {"error": error}
    serialized = json.dumps(data, default=str)
    truncated = False
    if len(serialized) > RESPONSE_CAP_BYTES:
        truncated = True
        if isinstance(data, list):
            trimmed = list(data)
            while trimmed and len(json.dumps(trimmed, default=str)) > RESPONSE_CAP_BYTES:
                trimmed.pop()
            data = trimmed
        else:
            data = serialized[: RESPONSE_CAP_BYTES - 1] + "…"
    out = {"data": data}
    if truncated:
        out["truncated"] = True
    return out


_TOOLS = {
    "query_sqlite": lambda args: query_sqlite(args["sql"]),
    "query_postgres": lambda args: query_postgres(args["sql"]),
    "call_gamma": lambda args: call_gamma(args["path"], args.get("params")),
    "call_clob": lambda args: call_clob(args["path"], args.get("params")),
}


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "query_sqlite",
        "description": (
            "Run a read-only SELECT / WITH query against the scanner's local "
            "SQLite database (polybot.db). Returns up to 200 rows. "
            "Statements other than SELECT/WITH are rejected."
        ),
        "parameters": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT or WITH statement."},
            },
        },
    }},
    {"type": "function", "function": {
        "name": "query_postgres",
        "description": (
            "Run a read-only SELECT / WITH query against the Railway Postgres "
            "database (shared with the PolySpotter backend). Returns up to 200 "
            "rows. Statements other than SELECT/WITH are rejected."
        ),
        "parameters": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT or WITH statement."},
            },
        },
    }},
    {"type": "function", "function": {
        "name": "call_gamma",
        "description": (
            "GET against https://gamma-api.polymarket.com. "
            "Allowed path prefixes: /markets, /events, /trades. "
            "Use `params` for query-string filters."
        ),
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Path starting with /markets, /events, or /trades."},
                "params": {"type": "object", "description": "Query string parameters."},
            },
        },
    }},
    {"type": "function", "function": {
        "name": "call_clob",
        "description": (
            "GET against https://clob.polymarket.com. "
            "Allowed paths: /prices-history (historical candles) and /book (order book). "
            "/prices-history takes `market` (a CLOB token_id, NOT a conditionId — "
            "get token_ids from Gamma `/markets?condition_ids=...` → `clobTokenIds`), "
            "plus `interval` (e.g. '1h', '6h', '1d', '1w', 'max') and "
            "`fidelity` (granularity in minutes; e.g. 1 = minute candles). "
            "Returns {\"history\": [{\"t\": <unix_seconds>, \"p\": <price>}, ...]} — "
            "the canonical source of truth for price moves. Prefer this over the "
            "`price_candles` tables, which may be stale or partial."
        ),
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Either /prices-history or /book."},
                "params": {"type": "object", "description": "Query string parameters."},
            },
        },
    }},
]


def dispatch(name: str, args: dict) -> dict:
    fn = _TOOLS.get(name)
    if fn is None:
        return _envelope(error=f"unknown tool: {name}")
    try:
        return _envelope(fn(args))
    except Exception as exc:
        return _envelope(error=f"{type(exc).__name__}: {exc}")


# --- System prompt -----------------------------------------------------------

SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service that surfaces
notable bets on Polymarket (whales, sharp wallets, coordinated flow, informed
edge). Every hour, a cron triggers you to look at what sharp money just did
and, when something genuinely merits attention, write an engaging 3-5 tweet
thread that tells the whole story.

## Your job, in order
1. The kickoff user message contains the alert(s) picked by a preceding
   triage pass. When there are multiple, they all share the same event —
   treat them as a single story and look for signal overlap across them
   (wallet_clustering + concentrated_one_sided = coordinated squad;
   timing + win_rate = sharp at the buzzer; composite + cluster alert on
   the same game = multiple angles on one story). Their full fields are
   embedded: `llm_headline`, `llm_summary`, `llm_bullets`,
   `llm_copy_action`, `cluster_headline`, the `signals` array (which
   detection strategies fired, with severity + headline),
   `market_description` (resolution criteria), `tags`, and `seo_summary`.
   No need to re-query for any of that. (`seo_faqs` is NOT embedded —
   query it if you need Q&A-style context.) Already-settled markets
   (closed / UMA-resolving / priced >= {SETTLED_PRICE_THRESHOLD}) have
   been filtered out via Gamma. Sports markets may be pre-kickoff or
   in-progress (within {GAME_LIVE_BUFFER_HOURS}h of start) — if the
   chosen event is an in-progress game, `game_start_time <= NOW()` and
   the thread angle should reflect that ("wallet loaded $X pre-tip and
   is now…").
2. RESEARCH. A great thread cites specific, surprising facts the raw
   alerts don't already contain. You'll need several — one per tweet.
   Research all three layers:

   The alerts/market themselves:
     - market_volume_snapshots / orderbook_snapshots → 24h volume + book depth
     - CLOB /prices-history    → canonical price time-series (PREFER this over
                                 price_candles for any price-move claim)
     - alert_trades            → individual trades backing the alert(s)

   The wallet(s) (usually the richest source of surprise):
     - wallet_profiles / wallet_pnl  → track record, edge, streaks, avg buy price
     - wallet_funders                → part of a shared-funder cluster?
     - wallet_event_history          → broader thesis across markets?
     - Gamma /trades?user=<wallet>   → their recent activity across Polymarket

   The tag / event context:
     - Gamma /events?slug=<event>    → sibling markets, event metadata
     - alerts filtered by tag        → other recent alerts in this vertical
                                       (sports / politics / crypto) — is this
                                       part of a broader pattern or an outlier?
     - wallet_theses                 → cross-market thesis groupings on this event
3. Write the thread.

## What each detection strategy means
The `signals` array on each seed alert (and rows in `alert_signals`) uses
these strategy names. Severity is 0-10; higher = stronger.

- **win_rate_tracking** (1.0-6.0): Wallet has >=75% win rate on 10+
  resolved bets AND beats implied odds by 15%+ (edge-adjusted). These are
  sharp bettors — a proven track record, not luck.
- **new_wallet_large_bet** (1.0-7.0): Wallets <30 days old placing large
  ($3k+) bets. Severity scales with wallet youth; escalated if the
  wallet is also already profitable. Signals informed conviction from a
  fresh account.
- **timing_relative_resolution** (1.0-8.0): Bets placed within 60 min of
  market resolution (short-duration markets like 5-min BTC binaries are
  excluded). "SERIAL TIMER" wallets that repeatedly bet near resolution
  across long-duration markets get heavily escalated — possible
  real-time information edge.
- **low_activity_large_bet** (0.5-4.0): Large bets on thinly-traded
  markets (<$5k 24h vol) or where a single bet is >=50% of 24h volume.
  Someone confident is moving real money into a market others ignore.
- **pre_event_volume_spike** (1.0-4.0): Scan-window volume >=10x the
  normalized average AND >=$10k absolute. A sudden flood into a
  normally quiet market — informed positioning.
- **wallet_clustering** (5.0-8.0): >=2 wallets funded by the same
  Etherscan address (traced via funding history). Severity scales
  logarithmically with cluster size. One actor deploying capital across
  multiple wallets.
- **concentrated_one_sided** (3.5-8.0): >=3 distinct wallets all betting
  the same direction on the same outcome within the scan window,
  totaling >=$5k. Jumps +1.5 if wallets in the cluster share a funder.
  Coordinated directional flow.
- **price_impact** (1.0-5.0): Significant price shift — within-window
  >=15pp, historical breakout >=25pp, or rapid velocity (>=10pp in 5
  min). Thin orderbooks boost severity. Someone is moving the market
  with conviction.
- **correlated_cross_market** (1.5-4.0): Wallet betting across multiple
  markets in the same event (same `event_slug`). Mixed directions =
  hedged thesis (3.0); consistent = directional thesis (1.5). Serial
  cross-market traders (>=3 events) escalate to 4.0.

The `signals` array is attached to every chosen alert, sorted by severity
DESC. Do NOT re-query `alert_signals` for alerts already in the kickoff
— they're already there. The top signal (or the strongest signal across
the group when you got multiple alerts) is usually the heart of the
story — lead the opening tweet with what IT says, not the raw
composite_score.

## The four tools
- query_sqlite(sql)    → scanner's local polybot.db (wallet P&L, funders, event history, etc.)
- query_postgres(sql)  → Railway Postgres (alerts, alert_trades, alert_signals, wallet_profiles, tweeted_alerts, wallet_theses, price_candles)
- call_gamma(path)     → https://gamma-api.polymarket.com  (allowed: /markets, /events, /trades)
- call_clob(path)      → https://clob.polymarket.com  (allowed: /prices-history, /book)

Queries MUST be SELECT / WITH only. Postgres and SQLite use slightly different
SQL dialects (Postgres: `NOW() - INTERVAL '1 hour'`, jsonb ops, ILIKE; SQLite:
no jsonb, LIKE is case-insensitive by default, `datetime('now','-1 hour')`).
Each tool returns up to 200 rows; responses are capped at ~12 KB. Prefer
narrow SELECT lists and LIMITs over SELECT *.

## Column types you WILL get wrong if you're not careful
Some timestamp-shaped columns are unix-epoch **doubles**, not
TIMESTAMPTZ / TEXT. `NOW() - INTERVAL ...` will error against them. Handle
them like this:
  - Postgres `price_candles.t`                   → double (unix seconds).
    Filter with `t >= EXTRACT(EPOCH FROM NOW()) - 7200` for 'last 2 hours'.
  - SQLite `price_candles.t`                     → double (unix seconds).
    Filter with `t >= strftime('%s','now') - 7200`.
  - SQLite `wallet_event_history.trade_timestamp` → double (unix seconds, same pattern).
  - SQLite `wallet_pnl.api_timestamp`             → bigint (unix seconds).
  - SQLite `tracked_bets.trade_timestamp`         → double (unix seconds).

TIMESTAMPTZ / ISO-8601 text columns (use `NOW() - INTERVAL` / `datetime(...)` freely):
  - Postgres `alerts.scanned_at`, `alerts.created_at`, `alert_trades.trade_timestamp`,
    `tweeted_alerts.tweeted_at`, `price_candles.created_at`.
  - SQLite `*.recorded_at`, `*.snapshot_at`, `*.discovered_at` (all ISO-8601 text).

## Railway Postgres schema (key tables)
- alerts — one row per composite/cluster alert
    id, alert_type ('composite'|'cluster'), composite_score,
    market: market_title, condition_id, event_slug, market_url,
            market_image, market_description, tags (TEXT JSON-array, e.g. '["Sports","NBA"]'),
    wallet (NULL for cluster alerts),
    aggregates: total_usd, trade_count, cluster_headline,
    timing:  end_date, game_start_time, event_end_estimate
             (event_end_estimate = game_start_time if set else end_date;
              use this to rank "resolving soon"),
    llm: llm_headline, llm_summary,
         llm_bullets (TEXT JSON-array of strings),
         llm_copy_action (TEXT JSON-object: {{outcome, side, entry_price, max_price}}),
    seo: seo_title, seo_description, seo_summary,
         seo_faqs (TEXT JSON-array of {{question, answer}}), seo_generated_at,
    timestamps: scanned_at, created_at,
    dedup_key (UNIQUE)
- alert_trades — individual trades attached to an alert (FK alerts.id, cascades)
    id, alert_id, transaction_hash, wallet, condition_id, outcome,
    side ('BUY'|'SELL'), usd_value, size, price, trade_timestamp
    UNIQUE(alert_id, transaction_hash)
- alert_signals — detection signals that fired for an alert (FK alerts.id)
    id, alert_id, strategy (e.g. 'new_wallet_large_bet'), severity, headline
- wallet_profiles — per-wallet cached stats (PK=wallet)
    total_positions, closed_positions, wins, losses,
    total_pnl, total_invested, avg_win_price, win_rate,
    times_flagged, current_streak, first_seen_at, updated_at
- wallet_theses — cross-market thesis groupings (UNIQUE wallet+event_slug)
    id, wallet, event_slug, thesis_headline,
    markets (JSONB array), total_usd, composite_score, created_at, updated_at
- tweeted_alerts — dedup log for the Twitter bot (PK=alert_id)
    alert_id, wallet, condition_id, tweet_id, tweet_text, tweeted_at
    (composite tweets share tweet_id/tweet_text across multiple rows)
- price_candles — sparkline data, mirrored from SQLite
    id, condition_id, token_id, outcome, t (unix secs, DOUBLE), p, created_at
    UNIQUE(token_id, t)

JSON-in-TEXT columns: alerts.tags, alerts.llm_bullets, alerts.llm_copy_action,
alerts.seo_faqs. Parse with `(col)::jsonb` in Postgres to use `->`, `->>`,
`jsonb_array_elements`, etc. wallet_theses.markets is already JSONB.

## polybot.db (SQLite) schema (key tables)
Wallet P&L and track record (written by win_rate_tracking):
- wallet_pnl — one row per closed position (UNIQUE wallet+condition_id+asset+position_type)
    wallet, condition_id, asset, outcome, avg_price, total_bought,
    realized_pnl, cur_price, event_slug, end_date (TEXT),
    position_type, recorded_at, api_timestamp (BIGINT unix secs)
- tracked_bets — raw tracked trades for win/loss attribution
    (UNIQUE wallet+condition_id+outcome+side+trade_timestamp)
    wallet, condition_id, outcome, side, usd_value,
    trade_timestamp (REAL unix secs), recorded_at,
    resolved (0/1), won (0/1/NULL)

Wallet clustering & flags:
- wallet_funders — shared-funder cluster detection (PK=wallet)
    wallet, funder, discovered_at
- wallet_event_history — cross-run event history per wallet
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, event_slug, condition_id, outcome, side, usd_value,
    trade_timestamp (REAL unix secs), recorded_at, price, market_title
- flagged_wallets — per-wallet rollup of large-bet flags (PK=wallet)
    wallet, times_flagged, total_usd_flagged,
    first_flagged_at, last_flagged_at
- flagged_trade_events — per-trade dedup behind flagged_wallets
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, condition_id, trade_timestamp (REAL), usd_value, recorded_at
- timing_flags — bets placed close to resolution
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, condition_id, minutes_to_resolution, usd_value,
    trade_timestamp (REAL), recorded_at, market_duration_hours

Market price/volume/orderbook state:
- market_volume_snapshots — 24h volume samples
    condition_id, volume_24h, snapshot_at
- price_history — per-trade price observations for price_impact
    (UNIQUE condition_id+outcome+trade_timestamp)
    condition_id, outcome, price, trade_timestamp (REAL), recorded_at
- price_candles — CLOB historical price time-series for sparklines
    (UNIQUE token_id+t)
    condition_id, token_id, outcome,
    t (REAL unix secs), p, recorded_at
- orderbook_snapshots — CLOB order book depth samples
    condition_id, token_id, outcome, best_bid, best_ask, spread,
    bid_depth, ask_depth, mid_price, snapshot_at

## Gamma API (https://gamma-api.polymarket.com)
Useful paths (all GET; allowlist = /markets, /events, /trades):
  /markets?condition_ids=...             market(s) by conditionId (comma-sep for many)
  /markets?slug=...                      market by slug
  /markets?tag_id=...&active=true        filter by tag + state (active/closed/archived)
  /markets?volume_num_min=...&order=...  filter/sort by volume, liquidity, end_date
  /markets/{{id}}                          single market by numeric id
  /markets/slug/{{slug}}                   single market by slug
  /markets/{{id}}/tags                     tags on a market
  /events?slug=...                       event(s) by slug (nested markets[])
  /events?tag_id=...&closed=false        filter events by tag + state
  /events/{{id}}                           single event by id
  /events/slug/{{slug}}                    single event by slug
  /events/{{id}}/tags                      tags on an event
  /trades?market=...&limit=...           recent trades on a market (by conditionId)
  /trades?user=...&limit=...             recent trades by a wallet

Common query params:
  limit, offset                 pagination (default limit ~100, cap 500)
  active, closed, archived      boolean state filters
  order, ascending              sort field + direction (e.g. order=volume)
  end_date_min, end_date_max    ISO-8601 bounds on resolution time
  volume_num_min, liquidity_num_min  numeric floors

Notable response fields:
  market: conditionId, slug, question, endDate, outcomes, outcomePrices,
          volume, volumeNum, volume24hr, liquidity, active, closed, negRisk,
          clobTokenIds, bestBid, bestAsk, lastTradePrice, events[{{id,slug}}]
  event:  id, slug, title, endDate, negRisk, volume, liquidity,
          markets[] (nested, same shape as above), tags[{{id,label,slug}}]
  tag:    id, label, slug   (e.g. id="1" = Sports, "3" = Politics, "4" = Crypto)

## CLOB API (https://clob.polymarket.com)
The canonical source for price history and order book state. Prefer this over
`price_candles` / `orderbook_snapshots` for any claim that ends up in the tweet —
those tables are sampled, can be stale, and may be truncated.

/prices-history — historical price time-series for one outcome token
  Required: market=<CLOB token_id>                 (NOT conditionId!)
  Pick ONE windowing form:
    interval=1h|6h|1d|1w|max            relative window ending now
    startTs=<unix>&endTs=<unix>         explicit window (both required together)
  Optional: fidelity=<minutes>                     granularity (1 = minute candles)
  Response: {{"history": [{{"t": <unix_seconds>, "p": <price>}}, ...]}}  — full series,
  no 200-row cap, no LIMIT truncation risk.

  To get a token_id:
    1. call_gamma("/markets", {{"condition_ids": "<conditionId>"}})
    2. response[0]["clobTokenIds"] is a JSON string of [yes_token, no_token]
       (or [token_for_outcome_0, token_for_outcome_1] — match by index to
       market["outcomes"]).

  For a "price moved from X to Y in the last hour" claim: use interval=1h +
  fidelity=1, then read `history[0].p` (earliest) and `history[-1].p` (latest)
  — and/or min/max across the full array. Do NOT trust price_candles for this.

/book — current order book for a token
  Required: token_id=<CLOB token_id>
  Response: {{"bids": [...], "asks": [...], "timestamp": ...}}

## Thread style (3-5 tweets — this is the engaging part, do not skip)
Build a micro-story across 3-5 tweets posted as a reply chain. Each tweet
must stand on its own AND advance the narrative.

Structure:
- Tweet 1 (HOOK): Lead with the single most striking specific fact — the
  number or pattern that makes someone stop scrolling. Numbers over
  adjectives. Not "alert: wallet X bet $Y on Z".
  Good hook examples:
    "A wallet that's hit 14 of its last 15 bets just loaded $82k on the No"
    "Three wallets funded by the same address quietly piled into UNDER 2.5 in the last 40 minutes"
    "Volume on this market 9x'd in 2 hours — and 73% of it is one wallet taking YES at 0.31"
- Tweets 2-4 (BODY): Each tweet advances ONE concrete beat — the track
  record, the timing, the price move, the shared funder, the cross-market
  thesis, the orderbook context, what makes this surprising vs. consensus.
  Don't restate the hook. Don't stuff two beats into one tweet — give each
  its own room.
- Final tweet (CLOSE): One last specific detail or "what to watch for" —
  e.g. resolution timing, next catalyst, price level to watch. End with a
  soft CTA to bio: "→ full breakdown in bio", "full thesis in bio 👀".

Hard style rules (apply to EVERY tweet in the thread):
- Each tweet <= {TWEET_MAX_CHARS} characters. Count yourself.
- NO thread numbering ("1/", "2/5", "🧵"). The reply chain IS the numbering.
- NO URLs. NO @mentions.
- 0-2 relevant emojis per tweet, only if they add something.
- 0-2 topic-specific hashtags across the thread (not #Polymarket). Most
  tweets should have zero.
- Voice: sharp trading desk analyst. Punchy. Confident. A little playful
  when warranted. Same voice across every tweet.
- Someone landing on tweet 3 by itself should still get value — each
  tweet needs its own concrete detail, not connective tissue.

## Fact fidelity (hard rule — this is where threads go wrong)
Every number, count, percentage, dollar figure, and timeframe — in ANY
tweet in the thread — must trace to a specific value in a tool response
you actually received. Not inferred, not rounded from context, not assumed.
More tweets = more places this rule can fail.

In particular:
- If you claim a price move over a timeframe ("from 0.46 to 0.74 in 20 min"),
  the query that produced those prices MUST be bounded to that timeframe.
  Don't run `MIN/MAX` over all time and then attach "in the last N min" to
  it — that's fabrication.
- If you claim "N wallets" or "$X total", the aggregate must come from a
  single query whose scope matches the claim. Don't sum numbers across
  different queries with different filters.
- If you claim a win rate or streak, cite wallet_profiles values verbatim;
  don't recompute or round them in ways the underlying numbers don't support.
- If a stat you want isn't in any tool response, either pull it or drop the
  claim. Never estimate.

## When to skip
If research reveals the picked alert(s) aren't actually a great story —
track record weaker than the signals suggested, no surprising numbers
beyond what's already in the alert, or the narrative just doesn't hold
up — return decision=skip. Don't force a thread.

## Output format (strict JSON — your final assistant content)
{{
  "decision": "post" | "skip",
  "reason": "one short sentence explaining the pick or the skip",
  "tweets": ["<tweet 1>", "<tweet 2>", ...] | null,   // 3-5 items, each ≤{TWEET_MAX_CHARS} chars, posted as a reply chain
  "alert_ids": [<int>, ...] | null                    // alerts this thread is about (for dedup recording)
}}

When decision=post, `tweets` must have exactly 3, 4, or 5 items and
`alert_ids` must be real IDs from the `alerts` table you saw in tool
responses.

Budget: up to {MAX_TOOL_CALLS} tool calls. If you hit the budget, write the
thread with what you have — do not keep digging.
"""


def build_kickoff_message(chosen_alerts: list[dict]) -> str:
    """Kickoff user message for stage 2: the alert(s) picked upstream.

    `chosen_alerts` is 1+ alerts (all sharing the same `event_slug` when >1).
    """
    assert chosen_alerts, "chosen_alerts must be non-empty"
    if len(chosen_alerts) == 1:
        payload = json.dumps(chosen_alerts[0], default=str, indent=2)
        return (
            "A preceding triage pass picked this alert as the best story "
            "for the hour. Research it with the four tools, then write the "
            "thread — or skip if research reveals it's not actually "
            "interesting. Remember: engaging 3-5 tweet story, not alert "
            "recap.\n\n"
            f"chosen_alert:\n{payload}"
        )
    slug = chosen_alerts[0].get("event_slug") or "(unknown event)"
    payload = json.dumps(chosen_alerts, default=str, indent=2)
    return (
        f"A preceding triage pass picked these {len(chosen_alerts)} alerts "
        f"— all on event '{slug}' — as the best story for the hour. Treat "
        "them as ONE story: look for signal overlap and what they "
        "collectively reveal. Research with the four tools, then write "
        "the thread — or skip if research reveals it's not actually "
        "interesting. Remember: engaging 3-5 tweet story, not alert "
        "recap.\n\n"
        f"chosen_alerts ({len(chosen_alerts)} rows):\n{payload}"
    )


# --- Picker (stage 1) --------------------------------------------------------

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


PICKER_SYSTEM_PROMPT = f"""You triage the top alerts from the last 3 hours \
for PolySpotter's hourly story bot. Downstream, a researcher model will pick \
up your choice and write a 3-5 tweet thread about it.

You see a compact list of up to {MAX_SEED_ALERTS} alerts (id, composite_score,
signals, headline, market, wallet, $ size, event_slug, tags, timing). Pick the
single best **story** for the hour, or skip if nothing stands out.

A story is usually one event, not one alert. Alerts come in clusters: the
same event may generate a composite alert + a cluster alert, or multiple
wallets may fire on the same market. When that happens, include ALL the
alerts for that event in your pick — the researcher uses them together to
spot signal overlap (e.g. wallet_clustering + concentrated_one_sided =
coordinated squad). Group by `event_slug`.

Favor:
- High-severity signals (wallet_clustering, timing_relative_resolution,
  concentrated_one_sided, new_wallet_large_bet at 5+)
- Events with multiple alerts reinforcing each other
- Specific numeric hooks (large $ size, coordinated flow, sharp timing)
- Surprising / story-worthy angles over generic big bets

Skip if:
- All alerts are small or lack a clear narrative
- Nothing stands out above the noise

Return exactly this JSON and nothing else:
{{"decision": "post" | "skip", "alert_ids": [<int>, ...] | null, \
"reason": "<one short sentence>"}}

When decision=post, `alert_ids` must be 1+ IDs from the list. If more than
one, ALL of them must share the same `event_slug`.
"""


def pick_story(llm_client, seed_alerts: list[dict], *,
               usage: dict | None = None,
               timings: list[dict] | None = None) -> dict:
    """Stage 1: pick the alert(s) that make the hour's story. No tools.

    Returns the raw model JSON ({"decision", "alert_ids", "reason"}). On
    invalid JSON, returns a skip decision with the parse error as reason.
    """
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    t0 = time.monotonic()
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PICKER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=10000,
        reasoning_effort="high",
        response_format={"type": "json_object"},
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if usage is not None:
        _accumulate_usage(usage, response)
    if timings is not None:
        timings.append({"stage": "pick", "ms": elapsed_ms})
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "alert_ids": None,
                "reason": f"picker returned invalid JSON: {exc}"}


def resolve_pick(pick: dict, seed_alerts: list[dict]
                 ) -> tuple[list[dict] | None, str | None]:
    """Map a picker decision onto the seed list. Returns (chosen_alerts, error).

    chosen_alerts is None on error. Enforces: IDs exist in the seed list, and
    multi-alert picks all share the same event_slug.
    """
    ids = pick.get("alert_ids")
    if not isinstance(ids, list) or not ids:
        return None, "alert_ids must be a non-empty list"
    by_id = {a.get("id"): a for a in seed_alerts}
    chosen: list[dict] = []
    for i in ids:
        try:
            aid = int(i)
        except (TypeError, ValueError):
            return None, f"alert_ids must be integers, got {i!r}"
        alert = by_id.get(aid)
        if alert is None:
            return None, f"alert_id {aid} not in seed list"
        chosen.append(alert)
    if len(chosen) > 1:
        slugs = {a.get("event_slug") for a in chosen}
        if len(slugs) != 1 or None in slugs:
            return None, f"multi-alert picks must share one event_slug, got {slugs!r}"
    return chosen, None


# --- Agent loop --------------------------------------------------------------

class AgentError(Exception):
    pass


def _assistant_tool_message(msg) -> dict:
    return {
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in msg.tool_calls
        ],
    }


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


def run_agent(llm_client, *, chosen_alerts: list[dict],
              on_tool_call=None, transcript: list[dict] | None = None,
              usage: dict | None = None,
              timings: list[dict] | None = None) -> dict:
    """Drive the function-calling loop until the LLM emits final JSON.

    `chosen_alerts` is the 1+ alerts already picked by `pick_story()` (all
    sharing one `event_slug` when >1); they're injected into the kickoff
    user message so the researcher can go straight to digging.

    If `transcript` is provided, every message (system, user, assistant, tool)
    is appended in-place — caller retains the full transcript even if we raise.
    If `usage` is provided, per-request token totals are accumulated in-place
    — caller retains partial usage even if we raise.
    If `timings` is provided, one entry is appended per research iteration
    with LLM + per-tool-call durations.

    `on_tool_call` is called with (name, args, env, elapsed_ms) after each
    tool dispatches.
    """
    messages: list[dict] = transcript if transcript is not None else []
    messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": build_kickoff_message(chosen_alerts)})
    calls_used = 0
    forcing_final = False
    final_json_retries = 0

    for iter_idx in range(MAX_ITERATIONS):
        remaining = MAX_TOOL_CALLS - calls_used
        kwargs = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "temperature": 1,
            "max_completion_tokens": 12000,
            "reasoning_effort": "high",
        }
        if remaining > 0 and not forcing_final:
            kwargs["tool_choice"] = "auto"
        else:
            kwargs["tool_choice"] = "none"
            kwargs["response_format"] = {"type": "json_object"}

        t_llm = time.monotonic()
        response = llm_client.chat.completions.create(**kwargs)
        llm_ms = int((time.monotonic() - t_llm) * 1000)
        if usage is not None:
            _accumulate_usage(usage, response)
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        iter_timing = {"stage": "research_iter", "iter": iter_idx + 1,
                       "llm_ms": llm_ms, "tool_calls": []}
        if timings is not None:
            timings.append(iter_timing)

        if tool_calls:
            messages.append(_assistant_tool_message(msg))
            dispatched = 0
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    env = _envelope(error=f"bad arguments JSON: {exc}")
                    tool_ms = 0
                else:
                    if not forcing_final and dispatched < remaining:
                        t_tool = time.monotonic()
                        env = dispatch(call.function.name, args)
                        tool_ms = int((time.monotonic() - t_tool) * 1000)
                        dispatched += 1
                    else:
                        env = _envelope(error="tool budget exhausted")
                        tool_ms = 0
                iter_timing["tool_calls"].append({
                    "name": call.function.name,
                    "ms": tool_ms,
                    "error": env.get("error"),
                    "truncated": env.get("truncated", False),
                })
                if on_tool_call is not None:
                    on_tool_call(call.function.name,
                                 args if isinstance(args, dict) else {},
                                 env, tool_ms)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(env, default=str),
                })
            calls_used += dispatched
            if calls_used >= MAX_TOOL_CALLS and not forcing_final:
                forcing_final = True
                messages.append({
                    "role": "user",
                    "content": "Tool budget exhausted. Return your final JSON decision now.",
                })
            continue

        content = msg.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            if final_json_retries >= 1:
                return {
                    "decision": "skip",
                    "reason": f"agent could not produce valid JSON ({exc})",
                    "tweets": None,
                    "alert_ids": None,
                }
            final_json_retries += 1
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response was empty or not valid JSON. "
                    "Respond with exactly one JSON object and nothing else, matching: "
                    "{\"decision\":\"post\"|\"skip\",\"reason\":\"…\","
                    "\"tweets\":[\"…\",\"…\",\"…\"]|null,\"alert_ids\":[…]|null}."
                ),
            })
            forcing_final = True
            continue

    raise AgentError("agent exceeded MAX_ITERATIONS without final JSON")


# --- Validation --------------------------------------------------------------

def validate_decision(decision: dict) -> tuple[bool, str]:
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"
    tweets = decision.get("tweets")
    if not isinstance(tweets, list):
        return False, "tweets must be a list of strings"
    if not 3 <= len(tweets) <= 5:
        return False, f"tweets must have 3-5 items, got {len(tweets)}"
    for i, t in enumerate(tweets):
        if not isinstance(t, str) or not t.strip():
            return False, f"tweets[{i}] must be a non-empty string"
        if len(t) > TWEET_MAX_CHARS:
            return False, f"tweets[{i}] length {len(t)} exceeds {TWEET_MAX_CHARS}"
    ids = decision.get("alert_ids") or []
    if not isinstance(ids, list) or not ids:
        return False, "alert_ids must be a non-empty list when posting"
    try:
        [int(i) for i in ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {ids!r}"
    return True, ""


# --- Twitter + recording -----------------------------------------------------

def _build_twitter_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=X_CONSUMER_KEY,
        consumer_secret=X_CONSUMER_KEY_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )


def post_thread(tweets: list[str], *, twitter_client, dry_run: bool) -> list[str]:
    """Post a reply-chain thread. Returns the list of tweet ids (root first)."""
    if dry_run:
        return [f"dryrun-{uuid.uuid4().hex[:12]}" for _ in tweets]
    tweet_ids: list[str] = []
    reply_to: str | None = None
    for text in tweets:
        kwargs: dict[str, Any] = {"text": text}
        if reply_to:
            kwargs["in_reply_to_tweet_id"] = reply_to
        resp = twitter_client.create_tweet(**kwargs)
        data = getattr(resp, "data", None) or {}
        tweet_id = str(data.get("id") or "")
        if not tweet_id:
            raise RuntimeError(f"create_tweet returned no id: {resp!r}")
        tweet_ids.append(tweet_id)
        reply_to = tweet_id
    return tweet_ids


def record_tweet(alert_ids: list[int], tweet_id: str, tweet_text: str) -> None:
    """Insert one tweeted_alerts row per alert. Re-uses the table the existing
    twitter_bot writes to, so both bots share dedup state."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Look up wallet + condition_id for each alert so we keep the columns
        # meaningful (the existing bot populates them).
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


# --- Dry-run transcript dump -------------------------------------------------

_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")


def _dump_dry_run(run_id: str, transcript: list[dict], *,
                  pick: dict | None = None,
                  decision: dict | None = None, error: str | None = None,
                  usage: dict | None = None,
                  timings: list[dict] | None = None) -> str:
    """Write the full chain (stage-1 pick, stage-2 transcript, final decision,
    per-step timings) to storybot/dry_runs/<run_id>.json."""
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"{run_id}.json")
    payload = {
        "run_id": run_id,
        "model": MODEL,
        "tweet_max_chars": TWEET_MAX_CHARS,
        "max_tool_calls": MAX_TOOL_CALLS,
        "max_iterations": MAX_ITERATIONS,
        "pick": pick,
        "transcript": transcript,
        "final_decision": decision,
        "error": error,
        "llm_usage": usage or {},
        "timings": timings or [],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


# --- Entrypoint --------------------------------------------------------------

def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    log("run_start", run_id=run_id, dry_run=STORYBOT_DRY_RUN)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)

    def _on_tool(name: str, args: dict, env: dict, elapsed_ms: int) -> None:
        if STORYBOT_DRY_RUN:
            preview = args.get("sql") or args.get("path") or json.dumps(args)[:200]
            status = f"ERROR: {env['error']}" if env.get("error") else \
                     ("ok (truncated)" if env.get("truncated") else "ok")
            print(f"  tool  {name}  ({elapsed_ms} ms)\n    {preview}\n    → {status}",
                  flush=True)
        else:
            log("tool_call", run_id=run_id, name=name,
                args_preview=(args.get("sql") or args.get("path") or "")[:200],
                error=env.get("error"), truncated=env.get("truncated", False),
                elapsed_ms=elapsed_ms)

    transcript: list[dict] | None = [] if STORYBOT_DRY_RUN else None
    usage_totals: dict = {}
    timings: list[dict] = []
    pick: dict | None = None
    run_start_t = time.monotonic()

    t_seed = time.monotonic()
    try:
        seed_alerts = fetch_seed_alerts()
    except Exception as exc:
        log("seed_fetch_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    seed_ms = int((time.monotonic() - t_seed) * 1000)
    timings.append({"stage": "seed_fetch", "ms": seed_ms, "count": len(seed_alerts)})
    log("seed_fetched", run_id=run_id, count=len(seed_alerts), elapsed_ms=seed_ms)
    if STORYBOT_DRY_RUN:
        print(f"[dry-run] seeded {len(seed_alerts)} alerts ({seed_ms} ms)", flush=True)

    if not seed_alerts:
        log("skip", run_id=run_id, reason="no alerts in the last 3 hours")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    # Stage 1: pick the story (or skip the hour).
    try:
        pick = pick_story(llm_client, seed_alerts, usage=usage_totals, timings=timings)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("pick_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    pick_ms = next((t["ms"] for t in reversed(timings) if t.get("stage") == "pick"), 0)
    log("pick", run_id=run_id, decision=pick.get("decision"),
        alert_ids=pick.get("alert_ids"), reason=pick.get("reason"),
        elapsed_ms=pick_ms)
    if STORYBOT_DRY_RUN:
        print(
            f"[dry-run] pick: {pick.get('decision')} "
            f"alert_ids={pick.get('alert_ids')} — {pick.get('reason')} "
            f"({pick_ms} ms)",
            flush=True,
        )

    if pick.get("decision") != "post":
        log("llm_usage", run_id=run_id, **usage_totals)
        log("skip", run_id=run_id, reason=pick.get("reason") or "picker chose to skip")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings)
            print(f"[dry-run] transcript → {path}", flush=True)
        return 0

    chosen_alerts, err = resolve_pick(pick, seed_alerts)
    if chosen_alerts is None:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("pick_error", run_id=run_id, error=err, pick=pick)
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"invalid pick: {err}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1

    # Stage 2: research + write.
    try:
        decision = run_agent(
            llm_client, chosen_alerts=chosen_alerts,
            on_tool_call=_on_tool, transcript=transcript,
            usage=usage_totals, timings=timings,
        )
    except AgentError as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("agent_error", run_id=run_id, error=str(exc))
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"AgentError: {exc}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"{type(exc).__name__}: {exc}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1

    log("llm_usage", run_id=run_id, **usage_totals)

    if STORYBOT_DRY_RUN:
        iters = [t for t in timings if t.get("stage") == "research_iter"]
        tool_total = sum(len(t.get("tool_calls") or []) for t in iters)
        research_ms = sum(t.get("llm_ms", 0) for t in iters) + sum(
            tc.get("ms", 0) for t in iters for tc in t.get("tool_calls") or []
        )
        print(
            f"[dry-run] timings: seed={seed_ms/1000:.2f}s "
            f"pick={pick_ms/1000:.2f}s "
            f"research={research_ms/1000:.2f}s "
            f"({len(iters)} iters, {tool_total} tool calls) "
            f"total={int((time.monotonic() - run_start_t) * 1000)/1000:.2f}s",
            flush=True,
        )
        print(
            f"[dry-run] llm usage: "
            f"prompt={usage_totals.get('prompt_tokens', 0):,} "
            f"completion={usage_totals.get('completion_tokens', 0):,} "
            f"reasoning={usage_totals.get('reasoning_tokens', 0):,} "
            f"cached={usage_totals.get('cached_prompt_tokens', 0):,} "
            f"total={usage_totals.get('total_tokens', 0):,} "
            f"requests={usage_totals.get('requests', 0)}",
            flush=True,
        )
        if transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 decision=decision)
            print(f"[dry-run] transcript → {path}", flush=True)

    ok, err = validate_decision(decision)
    if not ok:
        log("validation_error", run_id=run_id, error=err, decision=decision)
        return 1

    if decision["decision"] == "skip":
        log("skip", run_id=run_id, reason=decision.get("reason"))
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    tweets: list[str] = [t for t in decision["tweets"]]
    alert_ids = [int(i) for i in decision["alert_ids"]]
    thread_text = "\n\n".join(tweets)

    try:
        twitter_client = _build_twitter_client()
        tweet_ids = post_thread(tweets, twitter_client=twitter_client, dry_run=STORYBOT_DRY_RUN)
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    root_tweet_id = tweet_ids[0]
    log("posted", run_id=run_id, tweet_id=root_tweet_id, tweet_ids=tweet_ids,
        alert_ids=alert_ids, tweet_count=len(tweets),
        tweet_lengths=[len(t) for t in tweets])
    for i, t in enumerate(tweets, 1):
        print(f"\n--- Tweet {i}/{len(tweets)} ({len(t)} chars) ---\n{t}", flush=True)
    print("", flush=True)

    if STORYBOT_DRY_RUN:
        log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=root_tweet_id,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    try:
        record_tweet(alert_ids, root_tweet_id, thread_text)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        # Thread is live — still a success.
        log("run_end", run_id=run_id, posted=True, tweet_id=root_tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=root_tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
