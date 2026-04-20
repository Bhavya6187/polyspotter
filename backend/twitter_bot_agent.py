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
