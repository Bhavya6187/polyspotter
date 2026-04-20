"""
Agentic composer for backend/twitter_bot.py.

The bot hands this module the top 20 recent alerts. compose_tweet() drives a
GPT-5.4 function-calling loop with up to 5 tool calls, then returns the same
decision dict the bot expects (post/skip, alert_ids, tweet, is_composite).

All tools are read-only. No schema changes. No new endpoints. No langchain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jmespath


# --- Constants ---------------------------------------------------------------

MAX_TOOL_CALLS = 10
MAX_ITERATIONS = 12  # 10 tool rounds + 1 forcing + 1 safety
RESPONSE_CAP_BYTES = 8192


# --- Errors ------------------------------------------------------------------

class ProjectionError(Exception):
    """Raised when a JMESPath expression fails to compile or evaluate."""


class AgentOutputError(Exception):
    """Raised when the agent fails to produce valid final JSON."""


class ShortlistValidationError(Exception):
    """Raised when stage-1 LLM output fails validation."""


@dataclass
class ShortlistItem:
    """One alert chosen by stage 1, with the angle stage 1 wants stage 2 to verify."""
    alert_id: int
    angle: str


@dataclass
class ShortlistDecision:
    """Result of stage 1.

    decision = "shortlist": shortlist + mode are populated.
    decision = "skip":      shortlist + mode are None; reason explains why.
    """
    decision: str
    reason: str
    mode: str | None
    shortlist: list[ShortlistItem] | None


_VALID_MODES = {"single", "composite"}


def validate_shortlist_decision(raw, *, valid_alert_ids: set[int]) -> ShortlistDecision:
    """Parse and validate the stage-1 LLM JSON output.

    Returns a ShortlistDecision on success. Raises ShortlistValidationError on
    any rule violation. `valid_alert_ids` is the set of alert IDs the LLM was
    allowed to choose from (i.e. the top-N input set).

    Rules:
      - raw must be a dict.
      - decision must be 'shortlist' or 'skip'.
      - skip → only `reason` matters; mode and shortlist are returned as None.
      - shortlist requires mode in {single, composite} and a list of 2-4 items,
        each with an int alert_id (∈ valid_alert_ids) and a non-empty angle.
    """
    if not isinstance(raw, dict):
        raise ShortlistValidationError(f"raw must be dict, got {type(raw).__name__}")

    decision = raw.get("decision")
    reason = raw.get("reason") or ""

    if decision == "skip":
        return ShortlistDecision(decision="skip", reason=reason, mode=None, shortlist=None)

    if decision != "shortlist":
        raise ShortlistValidationError(f"unknown decision value: {decision!r}")

    mode = raw.get("mode")
    if mode not in _VALID_MODES:
        raise ShortlistValidationError(f"mode must be one of {_VALID_MODES}, got {mode!r}")

    shortlist_raw = raw.get("shortlist")
    if not isinstance(shortlist_raw, list) or not (2 <= len(shortlist_raw) <= 4):
        raise ShortlistValidationError(
            f"shortlist must be a list of 2-4 items, got {shortlist_raw!r}"
        )

    items: list[ShortlistItem] = []
    for i, item in enumerate(shortlist_raw):
        if not isinstance(item, dict):
            raise ShortlistValidationError(f"shortlist[{i}] must be dict, got {item!r}")
        try:
            alert_id = int(item["alert_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ShortlistValidationError(f"shortlist[{i}].alert_id invalid: {exc}") from exc
        if alert_id not in valid_alert_ids:
            raise ShortlistValidationError(
                f"shortlist[{i}].alert_id {alert_id} not in valid set {sorted(valid_alert_ids)}"
            )
        angle = item.get("angle")
        if not isinstance(angle, str) or not angle.strip():
            raise ShortlistValidationError(f"shortlist[{i}].angle must be a non-empty string")
        items.append(ShortlistItem(alert_id=alert_id, angle=angle.strip()))

    return ShortlistDecision(decision="shortlist", reason=reason, mode=mode, shortlist=items)


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
    envelopes. If projection fails, the raw (unprojected) data is returned
    along with a `projection_error` field so the model sees the failure but
    doesn't waste another tool call to get the raw shape.
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

        projection_error: str | None = None
        try:
            projected = apply_projection(raw, projection)
        except ProjectionError as exc:
            projection_error = f"projection {exc} — raw data returned instead"
            projected = raw

        truncated_value, was_truncated = truncate_payload(projected)
        envelope = build_envelope(truncated_value, truncated=was_truncated)
        if projection_error is not None:
            envelope["projection_error"] = projection_error
        return envelope

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


# --- Prompt + loop -----------------------------------------------------------

STAGE1_SYSTEM_PROMPT = (
    "You are the editor for the PolySpotter Twitter feed. Each hour you see "
    "up to 20 candidate alerts (notable Polymarket bets surfaced by our scanner). "
    "Your job is to pick the 2-4 alerts most likely to make a great tweet — "
    "OR skip the hour if nothing is compelling.\n\n"

    "## How to choose\n"
    "- Pick 2-4 alerts. Never fewer than 2, never more than 4. 2 when there's one "
    "clear story (the extra is a backup in case stage 2 finds the top pick doesn't "
    "hold up on research), 3-4 when you're genuinely torn between several.\n"
    "- If only one alert is truly worth tweeting and none of the others make "
    "plausible backups, skip the hour rather than padding the shortlist with a "
    "weak second pick.\n"
    "- 'Most tweetable' is not the same as 'highest composite_score'. Look for "
    "specific, surprising, story-rich bets — sharp wallets, big size, unusual "
    "timing, named themes.\n"
    "- Skip the hour if every alert feels routine or low-signal.\n\n"

    "## Single vs composite\n"
    "- mode='single': you want a tweet about ONE alert. Stage 2 will pick the "
    "strongest from your shortlist; the others are backups in case the first "
    "doesn't hold up to research.\n"
    "- mode='composite': the alerts share a tight thread — same wallet across "
    "markets, same event, shared funder cluster, same theme — and they belong "
    "in ONE tweet together. Only pick composite if you'd genuinely combine them. "
    "Never force synthesis.\n\n"

    "## The angle field\n"
    "For each shortlisted alert, write one short sentence describing the STORY "
    "you'd want the tweet to tell. Not a recap of the headline — the angle "
    "(e.g., 'verify this wallet is actually 20-0 and size is 25× their average', "
    "or '3 wallets sharing a funder all loaded the under in the last 40 min'). "
    "Stage 2 will use your angle to focus its research tools.\n\n"

    "## Output format (strict JSON)\n"
    'For shortlist:\n'
    '{\n'
    '  "decision": "shortlist",\n'
    '  "reason": "one short sentence on why these",\n'
    '  "mode": "single" | "composite",\n'
    '  "shortlist": [\n'
    '    {"alert_id": <int>, "angle": "<short story>"},\n'
    '    ...\n'
    '  ]\n'
    '}\n\n'
    'For skip:\n'
    '{"decision": "skip", "reason": "one short sentence"}\n\n'
    "alert_id values must be integers drawn from the alerts you were shown."
)


def build_stage1_user_message(top_alerts: list[dict]) -> str:
    """Slim payload for stage 1 — fields needed for editorial judgment, no trade detail."""
    payload = []
    for a in top_alerts:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "total_usd": a.get("total_usd"),
            "market_title": a.get("market_title"),
            "tags": a.get("tags") or [],
            "condition_id": a.get("condition_id"),
            "event_slug": a.get("event_slug"),
        })
    return json.dumps({"alerts": payload}, default=str)


def select_shortlist(top_alerts: list[dict], *, llm_client) -> ShortlistDecision:
    """Run stage 1: LLM picks 2-4 alerts (with mode + angles) or decides to skip.

    Single LLM call, JSON mode, no tools. Raises ShortlistValidationError if the
    output is malformed; raises any LLM-client exception unchanged. Caller
    (twitter_bot.call_llm) is responsible for the fallback path.
    """
    valid_alert_ids = {int(a["id"]) for a in top_alerts}
    messages = [
        {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
        {"role": "user", "content": build_stage1_user_message(top_alerts)},
    ]
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=400,
    )
    content = response.choices[0].message.content
    if not content:
        raise ShortlistValidationError("empty LLM response content")
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ShortlistValidationError(f"non-JSON content: {exc}") from exc
    return validate_shortlist_decision(raw, valid_alert_ids=valid_alert_ids)


MODEL = "gpt-5.4"


SYSTEM_PROMPT = (
    "You are the social media voice for PolySpotter, a service that surfaces "
    "notable Polymarket bets from sharp wallets, whales, and coordinated flow.\n\n"

    "You'll be given up to 20 alerts from the last hour. Your job: write ONE "
    "tweet that's as engaging as possible — drawing on one OR multiple alerts "
    "— or skip the hour if nothing is compelling.\n\n"

    "## You have research tools\n"
    "You can call up to 10 tools before writing the tweet. Use them when "
    "digging deeper would sharpen the story. A good tweet cites a SPECIFIC "
    "fact the alert payload doesn't already contain (e.g., 'bought the Under "
    "at 0.35 — market now at 0.62', 'this wallet has late-timed 17 markets "
    "in 3 weeks', 'volume 12x'd in the last 4 hours'). You don't have to use "
    "all 5. Zero calls is fine if the alerts already tell a tight story.\n\n"

    "## JMESPath projection\n"
    "Every tool accepts an optional `projection` string (a JMESPath expression). "
    "Use it to pull narrow values without loading large blobs into context. "
    "Examples:\n"
    "  - `length(bet_history)` — just a count\n"
    "  - `{win_rate: win_rate, total_pnl: total_pnl}` — pick fields\n"
    "  - `bet_history[?won==`true`].pnl_usd` — filtered list\n"
    "  - `avg(bet_history[?won==`true`].entry_price)` — computed aggregate\n"
    "If the projection fails (bad JMESPath, null values, etc.), the envelope "
    "includes a `projection_error` field AND the raw (8KB-capped) data — you "
    "don't need a second call to recover. Use the raw data or retry with a "
    "safer expression (e.g., filter out nulls).\n\n"

    "## Single vs composite\n"
    "- If one alert clearly stands out, write a tight hook-driven tweet focused on it.\n"
    "- If 2+ alerts tell a bigger story together (same market, same wallet across "
    "markets, a theme like '3 whales all loaded up on Iran markets today'), "
    "compose a synthesis tweet.\n"
    "- Never force synthesis. If alerts are unrelated, just pick the best one.\n\n"

    "## Tweet rules\n"
    "- Max 260 characters (safety margin under X's 280 limit).\n"
    "- Hook-driven opening: lead with the most striking fact.\n"
    "- Use specific numbers, not vague descriptors.\n"
    "- End with a CTA driving clicks to bio: '→ link in bio', "
    "'full details in bio 👀', 'who is this wallet? bio link'.\n"
    "- 1–2 relevant hashtags max. Prefer topic-specific over generic #Polymarket.\n"
    "- 0–2 emojis, only if they add something.\n"
    "- No URLs. No @mentions.\n"
    "- Never fabricate numbers or facts. Only cite values from the alert payload "
    "or from tool responses in this conversation.\n"
    "- Write like a sharp trading desk analyst, not a corporate account.\n\n"

    "## Skip criteria\n"
    "If all alerts are routine/low-signal, return decision=skip with a short reason.\n\n"

    "## Output format (strict JSON, returned as your final assistant content)\n"
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


def build_user_message(top_alerts: list[dict]) -> str:
    """Build the JSON payload describing the 5 candidate alerts.

    Includes every field an investigative composer needs to call deeper tools:
    condition_id, event_slug, end_date, market_description, llm_bullets.
    """
    payload = []
    for a in top_alerts:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "llm_bullets": a.get("llm_bullets") or [],
            "llm_copy_action": a.get("llm_copy_action") or {},
            "market_title": a.get("market_title"),
            "market_description": a.get("market_description"),
            "condition_id": a.get("condition_id"),
            "event_slug": a.get("event_slug"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "wallet_total_pnl": a.get("total_pnl"),
            "total_usd": a.get("total_usd"),
            "trade_count": a.get("trade_count"),
            "tags": a.get("tags") or [],
            "end_date": a.get("end_date"),
        })
    return json.dumps({"alerts": payload}, default=str)


def compose_tweet(
    top_alerts: list[dict],
    *,
    llm_client,
    deps: ToolDeps,
    on_tool_call=None,
) -> dict:
    """Run the function-calling loop and return the final decision dict.

    If `on_tool_call` is provided, it's invoked as `on_tool_call(name, args, envelope)`
    after each tool dispatch (including budget-exhausted ones), giving callers a
    streaming view of what the agent did.

    Raises AgentOutputError if the model fails to emit a valid final JSON
    response within MAX_ITERATIONS.
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(top_alerts)},
    ]
    tool_calls_used = 0
    forcing_final = False

    for _ in range(MAX_ITERATIONS):
        remaining = MAX_TOOL_CALLS - tool_calls_used
        call_kwargs = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "temperature": 0.7,
            "max_completion_tokens": 800,
        }
        if remaining > 0 and not forcing_final:
            call_kwargs["tool_choice"] = "auto"
        else:
            call_kwargs["tool_choice"] = "none"
            call_kwargs["response_format"] = {"type": "json_object"}

        response = llm_client.chat.completions.create(**call_kwargs)
        msg = response.choices[0].message

        tool_calls = getattr(msg, "tool_calls", None)

        if tool_calls:
            # Record the assistant turn exactly as the API expects to echo back.
            messages.append(_assistant_tool_message(msg))
            dispatched = 0
            for call in tool_calls:
                args = json.loads(call.function.arguments or "{}")
                if not forcing_final and dispatched < remaining:
                    env = dispatch_tool(call.function.name, args, deps=deps)
                    dispatched += 1
                else:
                    # Either forcing_final, or this turn exceeds remaining budget.
                    env = dispatch_tool_over_budget(call.function.name, deps=deps)
                if on_tool_call is not None:
                    on_tool_call(call.function.name, args, env)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(env, default=str),
                })
            tool_calls_used += dispatched
            if tool_calls_used >= MAX_TOOL_CALLS and not forcing_final:
                forcing_final = True
                messages.append({
                    "role": "user",
                    "content": (
                        "Tool budget exhausted. Return your final JSON decision now — "
                        "no more tool calls."
                    ),
                })
            continue

        # No tool calls — expect final JSON content.
        content = msg.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentOutputError(f"final content was not valid JSON: {exc}") from exc

    raise AgentOutputError("agent exceeded MAX_ITERATIONS without final JSON")


def _assistant_tool_message(msg) -> dict:
    """Shape an assistant message with tool_calls for echoing back to the API."""
    return {
        "role": "assistant",
        "content": msg.content,  # usually None
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            }
            for c in msg.tool_calls
        ],
    }
