"""
Agentic composer for backend/twitter_bot.py.

The bot hands this module the top 5 recent alerts. compose_tweet() drives a
GPT-5.4 function-calling loop with up to 5 tool calls, then returns the same
decision dict the bot expects (post/skip, alert_ids, tweet, is_composite).

All tools are read-only. No schema changes. No new endpoints. No langchain.
"""

from __future__ import annotations

import json
from typing import Any

import jmespath


# --- Constants ---------------------------------------------------------------

MAX_TOOL_CALLS = 5
MAX_ITERATIONS = 7  # 5 tool rounds + 1 forcing + 1 safety
RESPONSE_CAP_BYTES = 8192


# --- Errors ------------------------------------------------------------------

class ProjectionError(Exception):
    """Raised when a JMESPath expression fails to compile or evaluate."""


class AgentOutputError(Exception):
    """Raised when the agent fails to produce valid final JSON."""


# --- Envelope helpers --------------------------------------------------------

def build_envelope(data: Any, *, error: str | None = None, truncated: bool = False) -> dict:
    """Build the response envelope the LLM sees for every tool call."""
    if error is not None:
        return {"error": error}
    return {"data": data, "truncated": truncated}


def apply_projection(raw: Any, projection: str | None) -> Any:
    """Evaluate a JMESPath projection against raw data, or return raw if projection is None."""
    if projection is None:
        return raw
    try:
        compiled = jmespath.compile(projection)
    except jmespath.exceptions.ParseError as exc:
        raise ProjectionError(f"invalid: {exc}") from exc
    try:
        return compiled.search(raw)
    except Exception as exc:
        raise ProjectionError(f"failed: {exc}") from exc


def truncate_payload(data: Any, *, cap_bytes: int = RESPONSE_CAP_BYTES) -> tuple[Any, bool]:
    """Truncate a payload to fit within cap_bytes when JSON-serialized.

    - Top-level lists get trimmed item-by-item from the end.
    - Dicts (or other values) get JSON-stringified and tail-cut with `…` suffix.
    Returns (possibly-truncated-value, was_truncated).
    """
    serialized = json.dumps(data, default=str)
    if len(serialized) <= cap_bytes:
        return data, False

    if isinstance(data, list):
        trimmed = list(data)
        while trimmed and len(json.dumps(trimmed, default=str)) > cap_bytes:
            trimmed.pop()
        return trimmed, True

    # Fall-through: dict, scalar, or anything else. Stringify and cut.
    return serialized[: cap_bytes - 1] + "…", True


# --- HTTP helper -------------------------------------------------------------

HTTP_TIMEOUT_SECONDS = 5


class HTTPToolError(Exception):
    """Raised for HTTP failures (timeout, non-2xx, bad JSON)."""


def _http_get_json(url: str, *, http, params: dict | None = None, timeout: int = HTTP_TIMEOUT_SECONDS) -> Any:
    """GET a URL and return parsed JSON, or raise HTTPToolError."""
    try:
        resp = http.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPToolError(f"{type(exc).__name__}: {exc}") from exc


def _safe_tool(fn):
    """Wrap a tool so exceptions become error envelopes, and apply projection + truncation.

    The wrapped tool must return raw data (any JSON-serializable value). The
    decorator applies projection (if `projection` kwarg is set), truncates to
    8KB, and wraps the result in an envelope. Exceptions surface as error
    envelopes.
    """
    def wrapped(*args, projection: str | None = None, **kwargs):
        try:
            raw = fn(*args, **kwargs)
        except ProjectionError as exc:
            return build_envelope(None, error=f"projection {exc}")
        except HTTPToolError as exc:
            return build_envelope(None, error=f"http: {exc}")
        except Exception as exc:
            return build_envelope(None, error=f"{type(exc).__name__}: {exc}")

        try:
            projected = apply_projection(raw, projection)
        except ProjectionError as exc:
            return build_envelope(None, error=f"projection {exc}")

        truncated_value, was_truncated = truncate_payload(projected)
        return build_envelope(truncated_value, truncated=was_truncated)

    wrapped.__name__ = fn.__name__
    wrapped.__wrapped__ = fn
    return wrapped


# --- Backend API tools -------------------------------------------------------

@_safe_tool
def get_wallet_profile(*, wallet: str, http, api_url: str) -> Any:
    """Profile + recent alerts (≤10) + bet history (≤20) for a wallet."""
    url = f"{api_url.rstrip('/')}/api/wallets/{wallet}"
    return _http_get_json(url, http=http)


@_safe_tool
def get_alert_detail(*, alert_id: int, http, api_url: str) -> Any:
    """Full trades + signals for a single alert."""
    url = f"{api_url.rstrip('/')}/api/alerts/{int(alert_id)}"
    return _http_get_json(url, http=http)


@_safe_tool
def get_market_price_history(*, condition_id: str, hours: int = 24, http, api_url: str) -> Any:
    """Price candles for a market over the last N hours."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/price-history"
    return _http_get_json(url, http=http, params={"hours": int(hours)})


@_safe_tool
def get_market_holders(*, condition_id: str, http, api_url: str) -> Any:
    """Top holders per outcome for a market."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/holders"
    return _http_get_json(url, http=http)


@_safe_tool
def get_live_market(*, condition_id: str, http, api_url: str) -> Any:
    """Live sports/event state for a market, when available."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/live"
    return _http_get_json(url, http=http)


# --- Postgres tools ----------------------------------------------------------

from psycopg2.extras import RealDictCursor


def _pg_fetchall(db_conn_pg, query: str, params: tuple) -> list[dict]:
    """Run a SELECT and return RealDictCursor rows as plain dicts.

    On any error, rolls back the connection so subsequent queries in the same
    run aren't blocked by an aborted transaction state.
    """
    cur = db_conn_pg.cursor(cursor_factory=RealDictCursor)
    try:
        try:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            try:
                db_conn_pg.rollback()
            except Exception:
                pass
            raise
    finally:
        cur.close()


@_safe_tool
def get_market_alerts(*, condition_id: str, limit: int = 10, db_conn_pg) -> Any:
    """Other alerts on the same market (highest composite_score first)."""
    query = """
        SELECT id, composite_score, wallet, total_usd, llm_headline, created_at
        FROM alerts WHERE condition_id = %s
        ORDER BY composite_score DESC
        LIMIT %s
    """
    return _pg_fetchall(db_conn_pg, query, (condition_id, int(limit)))


@_safe_tool
def get_event_alerts(*, event_slug: str, limit: int = 20, db_conn_pg) -> Any:
    """Alerts on sibling markets in the same event."""
    query = """
        SELECT id, composite_score, wallet, market_title, condition_id,
               total_usd, llm_headline, created_at
        FROM alerts WHERE event_slug = %s
        ORDER BY composite_score DESC
        LIMIT %s
    """
    return _pg_fetchall(db_conn_pg, query, (event_slug, int(limit)))


@_safe_tool
def search_alerts_by_tag(*, tag: str, hours: int = 24, limit: int = 20, db_conn_pg) -> Any:
    """Alerts from the last N hours whose tags array contains this tag (case-insensitive).

    Thematic synthesis, e.g., tag="Iran" → every Iran-tagged alert in the window.
    """
    query = """
        SELECT id, composite_score, wallet, market_title, condition_id,
               total_usd, llm_headline, created_at
        FROM alerts
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(tags::jsonb) AS t
            WHERE LOWER(t) = LOWER(%s)
        )
          AND created_at >= NOW() - make_interval(hours => %s)
        ORDER BY composite_score DESC
        LIMIT %s
    """
    return _pg_fetchall(db_conn_pg, query, (tag, int(hours), int(limit)))


# --- Hybrid tools ------------------------------------------------------------

@_safe_tool
def get_theses(
    *,
    wallet: str | None = None,
    condition_id: str | None = None,
    event_slug: str | None = None,
    http,
    api_url: str,
) -> Any:
    """Cross-market thesis groupings, filtered by exactly one of the three args."""
    filters = [wallet, condition_id, event_slug]
    provided = sum(1 for f in filters if f)
    if provided != 1:
        raise ValueError("exactly one of wallet/condition_id/event_slug required")

    base = api_url.rstrip("/")
    if condition_id:
        return _http_get_json(f"{base}/api/market/{condition_id}/theses", http=http)

    # Wallet or event_slug: fetch full list and filter client-side. The list
    # endpoint may return either a bare list or {theses: [...]}.
    raw = _http_get_json(f"{base}/api/theses", http=http)
    items = raw.get("theses") if isinstance(raw, dict) else raw
    if wallet:
        return [t for t in items if t.get("wallet") == wallet]
    return [t for t in items if t.get("event_slug") == event_slug]


# --- SQLite tools ------------------------------------------------------------

def _sqlite_rows(db_conn_sqlite, query: str, params: tuple, *, keys: list[str]) -> list[dict]:
    """Run a SELECT and zip column-order keys into per-row dicts."""
    cur = db_conn_sqlite.execute(query, params)
    return [dict(zip(keys, row)) for row in cur.fetchall()]


@_safe_tool
def get_wallet_pnl_positions(*, wallet: str, limit: int = 20, db_conn_sqlite) -> Any:
    """Per-position detail (outcome, avg_price, cur_price, realized_pnl) for a wallet."""
    query = """
        SELECT condition_id, outcome, avg_price, total_bought, realized_pnl,
               cur_price, position_type, end_date
        FROM wallet_pnl
        WHERE wallet = ?
        ORDER BY total_bought DESC
        LIMIT ?
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (wallet.lower(), int(limit)),
        keys=["condition_id", "outcome", "avg_price", "total_bought",
              "realized_pnl", "cur_price", "position_type", "end_date"],
    )


@_safe_tool
def get_wallet_timing_pattern(*, wallet: str, db_conn_sqlite) -> Any:
    """How often this wallet bets near resolution (excluding short-duration markets)."""
    row = db_conn_sqlite.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT condition_id),
               AVG(minutes_to_resolution), MIN(minutes_to_resolution),
               SUM(usd_value)
        FROM timing_flags
        WHERE wallet = ?
          AND (market_duration_hours IS NULL OR market_duration_hours >= 1.0)
        """,
        (wallet.lower(),),
    ).fetchone()
    return {
        "total_flags": row[0] or 0,
        "distinct_markets": row[1] or 0,
        "avg_minutes": row[2] or 0.0,
        "min_minutes": row[3] or 0.0,
        "total_usd": row[4] or 0.0,
    }


@_safe_tool
def get_wallet_event_history(*, wallet: str, event_slug: str, db_conn_sqlite) -> Any:
    """Every trade (not just flagged) this wallet made on a given event."""
    query = """
        SELECT condition_id, outcome, side, usd_value, trade_timestamp, price, market_title
        FROM wallet_event_history
        WHERE wallet = ? AND event_slug = ?
        ORDER BY trade_timestamp ASC
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (wallet.lower(), event_slug),
        keys=["condition_id", "outcome", "side", "usd_value",
              "trade_timestamp", "price", "market_title"],
    )


@_safe_tool
def get_funder_cluster(*, wallet: str, db_conn_sqlite) -> Any:
    """Wallets sharing a funder with this one (wallet inclusive if present)."""
    w = wallet.lower()
    row = db_conn_sqlite.execute(
        "SELECT funder FROM wallet_funders WHERE wallet = ?", (w,)
    ).fetchone()
    if not row or not row[0]:
        return {"funder": None, "wallets": []}
    funder = row[0]
    peers = db_conn_sqlite.execute(
        "SELECT wallet FROM wallet_funders WHERE funder = ?", (funder,)
    ).fetchall()
    return {"funder": funder, "wallets": [r[0] for r in peers]}


@_safe_tool
def get_orderbook_snapshot(*, condition_id: str, db_conn_sqlite) -> Any:
    """Most recent orderbook snapshot per outcome token on a market."""
    query = """
        SELECT o.token_id, o.outcome, o.best_bid, o.best_ask, o.spread,
               o.bid_depth, o.ask_depth, o.mid_price, o.snapshot_at
        FROM orderbook_snapshots AS o
        JOIN (
            SELECT token_id, MAX(snapshot_at) AS max_at
            FROM orderbook_snapshots
            WHERE condition_id = ?
            GROUP BY token_id
        ) AS latest
          ON latest.token_id = o.token_id
         AND latest.max_at = o.snapshot_at
        WHERE o.condition_id = ?
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (condition_id, condition_id),
        keys=["token_id", "outcome", "best_bid", "best_ask", "spread",
              "bid_depth", "ask_depth", "mid_price", "snapshot_at"],
    )


@_safe_tool
def get_market_volume_history(*, condition_id: str, limit: int = 50, db_conn_sqlite) -> Any:
    """Recent 24h-volume snapshots for a market (most recent first)."""
    query = """
        SELECT volume_24h, snapshot_at
        FROM market_volume_snapshots
        WHERE condition_id = ?
        ORDER BY snapshot_at DESC
        LIMIT ?
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (condition_id, int(limit)),
        keys=["volume_24h", "snapshot_at"],
    )


# --- Gamma API generic caller ------------------------------------------------

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
GAMMA_PATH_ALLOWLIST = ("/markets", "/events", "/trades")


def _gamma_path_allowed(path: str) -> bool:
    """Allow paths that start with an allowlisted prefix and contain no parent traversals."""
    if not path.startswith("/"):
        return False
    if ".." in path or "//" in path:
        return False
    return any(path == prefix or path.startswith(prefix + "/") for prefix in GAMMA_PATH_ALLOWLIST)


@_safe_tool
def call_gamma_api(*, path: str, params: dict | None = None, http) -> Any:
    """Generic GET against https://gamma-api.polymarket.com with path allowlist.

    Allowed prefixes: /markets, /events, /trades (with arbitrary subpaths).
    """
    if not _gamma_path_allowed(path):
        raise ValueError("path not allowed")
    url = f"{GAMMA_BASE_URL}{path}"
    return _http_get_json(url, http=http, params=params or None)


# --- Tool registry & dispatcher ----------------------------------------------

from dataclasses import dataclass


@dataclass
class ToolDeps:
    """Bundle of injected dependencies. Pass into the loop and the dispatcher."""
    http: Any
    api_url: str | None
    db_conn_pg: Any
    db_conn_sqlite: Any


# Registry: tool name → (callable, set of dep names it needs)
_TOOL_REGISTRY: dict[str, tuple[Any, set[str]]] = {
    "get_wallet_profile": (get_wallet_profile, {"http", "api_url"}),
    "get_alert_detail": (get_alert_detail, {"http", "api_url"}),
    "get_market_price_history": (get_market_price_history, {"http", "api_url"}),
    "get_market_holders": (get_market_holders, {"http", "api_url"}),
    "get_market_alerts": (get_market_alerts, {"db_conn_pg"}),
    "get_event_alerts": (get_event_alerts, {"db_conn_pg"}),
    "get_live_market": (get_live_market, {"http", "api_url"}),
    "get_theses": (get_theses, {"http", "api_url"}),
    "search_alerts_by_tag": (search_alerts_by_tag, {"db_conn_pg"}),
    "get_wallet_pnl_positions": (get_wallet_pnl_positions, {"db_conn_sqlite"}),
    "get_wallet_timing_pattern": (get_wallet_timing_pattern, {"db_conn_sqlite"}),
    "get_wallet_event_history": (get_wallet_event_history, {"db_conn_sqlite"}),
    "get_funder_cluster": (get_funder_cluster, {"db_conn_sqlite"}),
    "get_orderbook_snapshot": (get_orderbook_snapshot, {"db_conn_sqlite"}),
    "get_market_volume_history": (get_market_volume_history, {"db_conn_sqlite"}),
    "call_gamma_api": (call_gamma_api, {"http"}),
}


def _projection_param() -> dict:
    return {
        "type": "string",
        "description": (
            "Optional JMESPath expression applied to the result before it "
            "reaches you. Example: 'length(bet_history)'."
        ),
    }


TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "get_wallet_profile",
        "description": (
            "Profile + up to 10 recent alerts + up to 20 bet history items for a wallet. "
            "Example projection: 'length(bet_history)' to count bets only."
        ),
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_alert_detail",
        "description": "Full trades + signals for a single alert id.",
        "parameters": {"type": "object", "required": ["alert_id"], "properties": {
            "alert_id": {"type": "integer"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_price_history",
        "description": "Price candles for a market over the last N hours (default 24).",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "hours": {"type": "integer", "default": 24},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_holders",
        "description": "Top holders per outcome for a market.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_alerts",
        "description": "Other PolySpotter alerts on the same market, highest score first.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_event_alerts",
        "description": "Alerts on sibling markets in the same event (e.g., different props on the same game).",
        "parameters": {"type": "object", "required": ["event_slug"], "properties": {
            "event_slug": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_live_market",
        "description": "Live sports/event state (score, clock, phase) when available.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_theses",
        "description": (
            "Cross-market thesis groupings. Provide exactly one of wallet, condition_id, or event_slug."
        ),
        "parameters": {"type": "object", "properties": {
            "wallet": {"type": "string"},
            "condition_id": {"type": "string"},
            "event_slug": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "search_alerts_by_tag",
        "description": (
            "Alerts in the last N hours whose tags array contains the given tag. "
            "Use for thematic synthesis (e.g., tag='Iran')."
        ),
        "parameters": {"type": "object", "required": ["tag"], "properties": {
            "tag": {"type": "string"},
            "hours": {"type": "integer", "default": 24},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_pnl_positions",
        "description": "Per-position detail from polybot.db: outcome, avg_price, cur_price, realized_pnl, position_type.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_timing_pattern",
        "description": "How often this wallet bets near resolution: total_flags, distinct_markets, avg/min minutes.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_event_history",
        "description": "Every trade (flagged or not) this wallet made on a given event.",
        "parameters": {"type": "object", "required": ["wallet", "event_slug"], "properties": {
            "wallet": {"type": "string"},
            "event_slug": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_funder_cluster",
        "description": "Wallets sharing a funder (Etherscan-derived) with this one.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_orderbook_snapshot",
        "description": "Most recent orderbook snapshot per outcome token (spread, depth, mid price).",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_volume_history",
        "description": "Recent 24h-volume snapshots for a market, most recent first.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "call_gamma_api",
        "description": (
            "Generic GET to https://gamma-api.polymarket.com. Allowed path prefixes: "
            "/markets, /events, /trades. Example: path='/events/my-event'."
        ),
        "parameters": {"type": "object", "required": ["path"], "properties": {
            "path": {"type": "string"},
            "params": {"type": "object"},
            "projection": _projection_param(),
        }},
    }},
]


def dispatch_tool(name: str, arguments: dict, *, deps: ToolDeps) -> dict:
    """Look up a tool by name, inject deps, run it, return the envelope."""
    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return build_envelope(None, error=f"unknown tool: {name}")

    fn, needed = entry
    kwargs = dict(arguments) if isinstance(arguments, dict) else {}
    for dep_name in needed:
        kwargs[dep_name] = getattr(deps, dep_name)
    try:
        return fn(**kwargs)
    except TypeError as exc:
        # Wrong argument types / missing required args.
        return build_envelope(None, error=f"TypeError: {exc}")


def dispatch_tool_over_budget(name: str, *, deps: ToolDeps) -> dict:
    """Return a budget-exhausted error envelope without running the tool.

    Used when a single assistant turn requests more tool calls than the
    remaining budget: the first N are dispatched normally, the rest get this.
    """
    return build_envelope(None, error="tool budget exhausted")
