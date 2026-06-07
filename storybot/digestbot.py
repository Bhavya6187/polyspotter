"""
PolySpotter daily digest generator.

Picks notable Polymarket events (resolving today + a mixed top-this-week pool),
uses two `claude -p --model opus` passes to choose and write the digest, renders
a styled HTML email file, and upserts the digest into the `digests` table for the
website (/digest/<date>).

Usage:
    DRY_RUN=true python storybot/digestbot.py   # preview into storybot/dry_runs/
    python storybot/digestbot.py                # write email + publish to website
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log

# --- Config -----------------------------------------------------------------

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
CLAUDE_MODEL = "opus"
SITE_URL = os.environ.get("SITE_URL", "https://polyspotter.com")
WEEK_POOL_LIMIT = 25      # max this-week candidates sent to the PICK pass
WEEK_PICKS_MAX = 5        # max this-week events in the final digest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DIGESTS_DIR = os.path.join(_THIS_DIR, "digests")
DRY_RUNS_DIR = os.path.join(_THIS_DIR, "dry_runs")


# --- Pure helpers -----------------------------------------------------------

def _loads(value, default):
    """json.loads a TEXT column that may already be parsed or be NULL/blank."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def leaning_str(copy_action) -> str:
    """Human one-liner for which side PolySpotter leans, from llm_copy_action."""
    if not copy_action or not copy_action.get("outcome"):
        return "No clear lean"
    outcome = copy_action["outcome"]
    entry = copy_action.get("entry_price")
    if isinstance(entry, (int, float)):
        return f"{outcome} @ {entry:.2f}"
    return str(outcome)


def shape_candidate(row: dict) -> dict:
    """Turn a raw alerts row into a compact candidate dict (the unit we pass to
    the PICK pass and later hydrate from)."""
    copy_action = _loads(row.get("llm_copy_action"), {})
    effective = row.get("event_end_estimate") or row.get("end_date")
    return {
        "event_slug": row.get("event_slug") or row.get("condition_id"),
        "title": row.get("market_title"),
        "market_url": row.get("market_url"),
        "resolution_time": effective.isoformat() if effective else None,
        "total_usd": row.get("total_usd"),
        "trade_count": row.get("trade_count"),
        "composite_score": row.get("composite_score"),
        "tags": _loads(row.get("tags"), []),
        "leaning": leaning_str(copy_action),
    }


def dedupe_by_event(cands: list[dict]) -> list[dict]:
    """Keep one candidate per event_slug — the one with the highest composite_score."""
    best: dict[str, dict] = {}
    for c in cands:
        slug = c["event_slug"]
        if slug not in best or (c.get("composite_score") or 0) > (best[slug].get("composite_score") or 0):
            best[slug] = c
    return list(best.values())


# --- claude -p ---------------------------------------------------------------

def run_claude(prompt: str, payload: str) -> str:
    """Invoke the Claude CLI headlessly. `payload` is piped on stdin. No tools."""
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", CLAUDE_MODEL,
         "--dangerously-skip-permissions"],
        input=payload,
        text=True,
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (exit {proc.returncode}): {proc.stderr[:500]}"
        )
    return proc.stdout


def parse_json_response(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating ```json fences/prose."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def run_claude_json(prompt: str, payload: str) -> dict:
    """run_claude + parse_json_response with one retry on non-JSON output."""
    last_err: Exception | None = None
    for attempt in range(2):
        out = run_claude(prompt, payload)
        try:
            return parse_json_response(out)
        except (json.JSONDecodeError, ValueError) as err:
            last_err = err
            log("digest_bad_json", attempt=attempt, error=str(err))
    raise RuntimeError(f"claude -p returned non-JSON twice: {last_err}")
