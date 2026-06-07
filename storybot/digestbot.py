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


# --- Prompts -----------------------------------------------------------------

PICK_PROMPT = (
    "You are the editor of PolySpotter, a Polymarket smart-money tracker. "
    "Stdin is JSON with two candidate lists: `resolving_today` (markets that "
    "resolve today) and `week_pool` (a mix of upcoming-resolution and recently-"
    "active markets). Each candidate has event_slug, title, resolution_time, "
    "total_usd (money behind it), trade_count, composite_score (signal strength, "
    "higher=stronger), and leaning (which side we favor). "
    "Pick the most newsworthy events. Choose ALL genuinely interesting "
    "resolving_today events (max 6). From week_pool choose the 3-5 best, "
    "deliberately balancing popular (high total_usd/trade_count) against "
    "high-conviction (high composite_score). Do not pick the same event_slug "
    "twice. Respond with ONLY JSON, no prose, in this exact shape: "
    '{"resolving_today": [{"event_slug": "...", "reason": "..."}], '
    '"top_this_week": [{"event_slug": "...", "reason": "..."}]}'
)

WRITE_PROMPT = (
    "You are writing the PolySpotter daily digest email. Stdin is JSON with "
    "`resolving_today` and `top_this_week`, each a list of picked events "
    "(event_slug, title, resolution_time, total_usd, trade_count, "
    "composite_score, leaning). Write a punchy subject line, a 1-2 sentence "
    "intro, and for EACH event a short headline (<=8 words) and a 1-2 sentence "
    "blurb explaining why the smart money is interesting and which way we lean. "
    "Be concrete, no hype, no emojis. Do NOT invent prices or URLs. "
    "Respond with ONLY JSON, no prose, in this exact shape: "
    '{"subject": "...", "intro": "...", "writeups": '
    '[{"event_slug": "...", "headline": "...", "blurb": "..."}]}'
)

_SECTIONS = [
    ("resolving_today", "Resolving Today"),
    ("top_this_week", "Top This Week"),
]


# --- Content assembly --------------------------------------------------------

def assemble_content(write_out: dict, today_picks: list[dict],
                     week_picks: list[dict]) -> dict:
    """Merge LLM prose (headline/blurb) with factual fields (leaning/url/title)
    from the DB picks, keyed by event_slug. Factual fields never come from the
    LLM. Empty sections are omitted."""
    writeups = {w["event_slug"]: w for w in write_out.get("writeups", [])}

    def build_items(picks: list[dict]) -> list[dict]:
        items = []
        for p in picks:
            w = writeups.get(p["event_slug"], {})
            items.append({
                "event_slug": p["event_slug"],
                "title": p.get("title"),
                "headline": w.get("headline") or p.get("title") or "",
                "blurb": w.get("blurb") or "",
                "leaning": p.get("leaning") or "No clear lean",
                "url": p.get("market_url") or f"{SITE_URL}/event/{p['event_slug']}",
            })
        return items

    picks_by_key = {"resolving_today": today_picks, "top_this_week": week_picks}
    sections = []
    for key, title in _SECTIONS:
        items = build_items(picks_by_key[key])
        if items:
            sections.append({"key": key, "title": title, "items": items})

    return {
        "subject": write_out.get("subject") or "PolySpotter Daily",
        "intro": write_out.get("intro") or "",
        "sections": sections,
    }


# --- Email HTML rendering ----------------------------------------------------

def _esc(text) -> str:
    s = "" if text is None else str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def render_email_html(content: dict) -> str:
    """Self-contained, inline-styled HTML for pasting into Gmail. No <style>/<link>."""
    wrap = "max-width:640px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#111;"
    parts = [f'<div style="{wrap}">']
    parts.append(
        f'<h1 style="font-size:22px;margin:0 0 4px;">{_esc(content["subject"])}</h1>'
    )
    if content.get("intro"):
        parts.append(
            f'<p style="font-size:15px;color:#444;margin:0 0 20px;">{_esc(content["intro"])}</p>'
        )
    for section in content.get("sections", []):
        parts.append(
            f'<h2 style="font-size:16px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#666;border-bottom:1px solid #eee;padding-bottom:6px;margin:24px 0 12px;">'
            f'{_esc(section["title"])}</h2>'
        )
        for item in section["items"]:
            parts.append('<div style="margin:0 0 16px;">')
            parts.append(
                f'<div style="font-size:16px;font-weight:bold;margin:0 0 2px;">'
                f'{_esc(item["headline"])}</div>'
            )
            parts.append(
                f'<div style="display:inline-block;font-size:13px;font-weight:bold;'
                f'background:#eef6ff;color:#0b6bcb;padding:2px 8px;border-radius:10px;'
                f'margin:0 0 4px;">Leaning: {_esc(item["leaning"])}</div>'
            )
            parts.append(
                f'<p style="font-size:14px;color:#333;margin:4px 0;">{_esc(item["blurb"])}</p>'
            )
            parts.append(
                f'<a href="{_esc(item["url"])}" style="font-size:13px;color:#0b6bcb;">'
                f'View market →</a>'
            )
            parts.append('</div>')
    parts.append(
        '<p style="font-size:12px;color:#999;margin-top:28px;border-top:1px solid #eee;'
        'padding-top:12px;">PolySpotter — smart money on Polymarket.</p>'
    )
    parts.append('</div>')
    return "\n".join(parts)
