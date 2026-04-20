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
