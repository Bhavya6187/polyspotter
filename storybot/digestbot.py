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

import argparse
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone

import psycopg2
import requests
from psycopg2.extras import RealDictCursor

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log

# --- Config -----------------------------------------------------------------

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
CLAUDE_MODEL = "opus"
SITE_URL = os.environ.get("SITE_URL", "https://polyspotter.com")
WEEK_POOL_LIMIT = 25      # max this-week candidates sent to the PICK pass
WEEK_PICKS_MAX = 5        # max this-week events in the final digest

# Conviction floor — keep lone tiny bets (a single $1k wager) out of the digest.
# A candidate qualifies on EITHER heavy money OR many trades (coordinated flow).
MIN_CONVICTION_USD = 10000
MIN_CONVICTION_TRADES = 8

# Don't re-feature an event the digest already ran in the last few days (the
# week pool otherwise repeats the same 5 events for a week straight).
FEATURED_LOOKBACK_DAYS = 3

# Append to on-site links so digest traffic is attributable in analytics.
_UTM = "utm_source=digest&utm_medium=email&utm_campaign=daily"

# --- Email delivery (Resend) -------------------------------------------------
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_ENDPOINT = "https://api.resend.com/emails"
# Must be a domain verified in Resend, else sends are rejected. Override in .env.
DIGEST_FROM_EMAIL = os.environ.get("DIGEST_FROM_EMAIL", "PolySpotter <team@polyspotter.com>")
# Base URL of the hosted backend that serves /api/unsubscribe.
UNSUBSCRIBE_BASE_URL = os.environ.get(
    "UNSUBSCRIBE_BASE_URL", os.environ.get("POLYBOT_BACKEND_URL", "https://api.polyspotter.com")
).rstrip("/")

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
        return f"{outcome} ({entry * 100:.0f}% implied)"
    return str(outcome)


def _with_utm(url: str) -> str:
    """Append the digest UTM params, choosing ? or & based on the existing query."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{_UTM}"


def link_for_pick(pick: dict) -> str:
    """Where 'View market' should point. Prefer the on-site event page (keeps the
    reader on polyspotter, which links out to Polymarket itself) and tag it with
    UTM. Fall back to the raw market_url only when we don't have a real event
    slug (e.g. a 0x condition_id), which the on-site router can't resolve."""
    slug = pick.get("event_slug")
    if slug and not str(slug).startswith("0x"):
        return _with_utm(f"{SITE_URL}/event/{slug}")
    return pick.get("market_url") or _with_utm(f"{SITE_URL}/event/{slug}")


def browser_url(digest_date: str) -> str:
    """On-site permalink for the day's digest ('View in browser')."""
    return _with_utm(f"{SITE_URL}/digest/{digest_date}")


def meets_conviction(cand: dict) -> bool:
    """A candidate clears the floor on EITHER heavy money OR many trades. Keeps
    lone tiny bets (a single $1k wager) out of a 'smart money' digest."""
    usd = cand.get("total_usd") or 0
    trades = cand.get("trade_count") or 0
    return usd >= MIN_CONVICTION_USD or trades >= MIN_CONVICTION_TRADES


def extract_event_slugs(content_json) -> set:
    """All event_slugs referenced by a stored digest's content_json (any section).
    Tolerates a JSON string, None, or malformed shapes."""
    content = _loads(content_json, {})
    if not isinstance(content, dict):
        return set()
    slugs = set()
    sections = content.get("sections")
    if not isinstance(sections, list):
        return slugs
    for section in sections:
        for item in (section or {}).get("items", []) if isinstance(section, dict) else []:
            slug = (item or {}).get("event_slug") if isinstance(item, dict) else None
            if slug:
                slugs.add(slug)
    return slugs


def build_week_pool(upcoming: list[dict], hot: list[dict],
                    today_slugs: set, featured_slugs: set) -> list[dict]:
    """The 'Top This Week' candidate pool: dedupe upcoming+hot by event, drop
    anything already in Resolving Today, already featured in a recent digest, or
    below the conviction floor; then sort by composite score and cap."""
    week = dedupe_by_event(upcoming + hot)
    week = [c for c in week
            if c["event_slug"] not in today_slugs
            and c["event_slug"] not in featured_slugs
            and meets_conviction(c)]
    week.sort(key=lambda c: c.get("composite_score") or 0, reverse=True)
    return week[:WEEK_POOL_LIMIT]


# Operational/automation tags Polymarket attaches that mean nothing to a reader.
# Matched as lowercased substrings so "Rewards Automation 1000, 4.5, 100",
# "rewards 100, 4.5, 100", "Earn 4%" etc. all fall out.
_JUNK_TAG_SUBSTR = (
    "hide from new", "recurring", "reward", "earn ", "automation", "up or down",
    "multi strike", "hit price", "crypto prices", "daily-close", "finance updown",
    "pyth finance", "equity daily", "parent for derivative", "main election", "🚀",
)
# Exact (lowercased) operational tags that aren't worth showing on their own.
_JUNK_TAG_EXACT = frozenset({"games", "world", "5m", "1h", "daily", "weekly", "monthly"})
# Umbrella categories — kept, but shown as the "broad" half of the chip and never
# chosen as the specific half when a narrower tag exists.
_BROAD_TAGS = ("esports", "sports", "politics", "geopolitics", "crypto", "finance",
               "culture", "tech", "elections")
# Connectors left lowercase when title-casing an all-lowercase tag.
_SMALL_WORDS = frozenset({"of", "the", "and", "a", "an", "to", "in", "x", "vs"})


def _is_junk_tag(tag: str) -> bool:
    low = tag.lower().strip()
    if low in _JUNK_TAG_EXACT:
        return True
    return any(sub in low for sub in _JUNK_TAG_SUBSTR)


def _pretty_tag(tag: str) -> str:
    """Tidy casing only for all-lowercase tags; leave 'MLB', 'Dota 2' untouched."""
    if tag != tag.lower():
        return tag
    words = tag.split()
    return " ".join(
        w if (w in _SMALL_WORDS and i) else w.capitalize()
        for i, w in enumerate(words)
    )


# Specifics whose umbrella Polymarket sometimes omits — infer it so we never
# render a lonely 'Iran' chip with no broad half.
_GEO_SUBJECTS = frozenset({
    "iran", "israel", "ukraine", "russia", "china", "taiwan", "gaza", "palestine",
    "syria", "north korea", "venezuela", "us x iran", "u.s. x iran", "iran ceasefire",
})
_CRYPTO_SUBJECTS = frozenset({"bitcoin", "ethereum", "solana", "xrp", "dogecoin", "crude oil"})
# Canonical spellings for a few specifics that show up inconsistently.
_SPECIFIC_ALIASES = {
    "counter strike": "Counter-Strike", "counter strike 2": "Counter-Strike 2",
    "cs2": "Counter-Strike 2", "csgo": "Counter-Strike",
}
# Generic specifics that lose to a more specific tag (so a match chips as its
# tournament when one is tagged, not the bare sport).
_GENERIC_SPECIFICS = frozenset({"soccer", "football", "basketball", "baseball", "hockey"})


def _infer_broad(clean_lowers: set) -> str | None:
    """Guess the umbrella for tags carrying only a specific (e.g. {'iran'} →
    'Politics'). Mirrors appeal_rank priority. Returns a display-cased label."""
    if clean_lowers & _TIER_ESPORTS:
        return "Esports"
    if (clean_lowers & _TIER_POLITICS) or (clean_lowers & _GEO_SUBJECTS):
        return "Politics"
    if clean_lowers & _TIER_MAJOR_SPORTS:
        return "Sports"
    if clean_lowers & _CRYPTO_SUBJECTS:
        return "Crypto"
    return None


def category_label(tags) -> str | None:
    """Derive a short 'Broad · Specific' chip (e.g. 'Esports · Dota 2') from raw
    Polymarket tags. Infers the broad half when only a specific is present, and
    returns None rather than a lonely, umbrella-less specific."""
    if not isinstance(tags, list):
        return None
    clean = [t for t in tags if isinstance(t, str) and t.strip() and not _is_junk_tag(t)]
    by_lower = {t.lower(): t for t in clean}
    # Pick the broad half by _BROAD_TAGS priority (e.g. Esports over Sports) so the
    # same domain always chips the same way regardless of raw tag order.
    broad = next((by_lower[b] for b in _BROAD_TAGS if b in by_lower), None)
    # Specific half: prefer a non-generic specific (a tournament over bare 'Soccer').
    non_broad = [t for t in clean if t.lower() not in _BROAD_TAGS]
    specific = (next((t for t in non_broad if t.lower() not in _GENERIC_SPECIFICS), None)
                or next(iter(non_broad), None))

    if broad is None:
        broad = _infer_broad(set(by_lower))
    if broad is None:
        return None  # never emit an umbrella-less chip

    if specific:
        specific = _SPECIFIC_ALIASES.get(specific.lower(), specific)
    parts = [p for p in (broad, specific) if p]
    return " · ".join(_pretty_tag(p) for p in parts)


# Click-appeal tiers (lower rank = shown first). Derived from tags so the digest
# leads with broadly-appealing topics (US-Iran, elections, big games) and buries
# niche markets, regardless of raw dollar size. Esports is checked first because
# those markets are ALSO tagged "Sports".
_TIER_ESPORTS = frozenset({
    "esports", "league of legends", "dota 2", "dota2", "counter strike",
    "counter strike 2", "cs2", "csgo", "valorant",
})
_TIER_POLITICS = frozenset({
    "politics", "geopolitics", "elections", "election", "us election",
    "global elections", "world elections", "primaries",
})
_TIER_MAJOR_SPORTS = frozenset({
    "nba", "nfl", "mlb", "baseball", "basketball", "football", "soccer", "epl",
    "premier league", "tennis", "ufc", "mma", "boxing", "nhl", "hockey", "golf",
    "f1", "formula 1", "cricket",
})


def appeal_rank(tags) -> int:
    """Map tags to a click-appeal tier: 0=politics/geopolitics, 1=major sports,
    2=crypto/business/culture/unknown, 3=niche esports. Lower sorts first."""
    lows = {t.lower() for t in tags if isinstance(t, str)} if isinstance(tags, list) else set()
    if lows & _TIER_ESPORTS:
        return 3
    if lows & _TIER_POLITICS:
        return 0
    if lows & _TIER_MAJOR_SPORTS:
        return 1
    return 2


def order_by_appeal(picks: list[dict]) -> list[dict]:
    """Sort picks by appeal tier, breaking ties by dollar size (bigger first)."""
    return sorted(
        picks,
        key=lambda p: (appeal_rank(p.get("tags") or []), -(p.get("total_usd") or 0)),
    )


def shape_candidate(row: dict) -> dict:
    """Turn a raw alerts row into a compact candidate dict (the unit we pass to
    the PICK pass and later hydrate from)."""
    copy_action = _loads(row.get("llm_copy_action"), {})
    effective = row.get("event_end_estimate") or row.get("end_date")
    return {
        "event_slug": row.get("event_slug") or row.get("condition_id"),
        "title": row.get("market_title"),
        "market_url": row.get("market_url"),
        "image": row.get("market_image"),
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
    "Pick the most newsworthy, broadly-appealing events — favor topics a general "
    "audience clicks on (geopolitics, politics, elections, major sports, crypto, "
    "business, pop culture) over niche ones. Niche esports markets (League of "
    "Legends, Dota 2, Counter-Strike) can be interesting but must NOT dominate: "
    "include at most 2 across the whole digest, and only the most notable. "
    "Choose the genuinely interesting resolving_today events (max 6). From "
    "week_pool choose the 3-5 best, deliberately balancing popular (high "
    "total_usd/trade_count) against high-conviction (high composite_score). Do "
    "not pick the same event_slug twice. Respond with ONLY JSON, no prose, in "
    "this exact shape: "
    '{"resolving_today": [{"event_slug": "...", "reason": "..."}], '
    '"top_this_week": [{"event_slug": "...", "reason": "..."}]}'
)

WRITE_PROMPT = (
    "You are writing the PolySpotter daily digest email. Stdin is JSON with "
    "`resolving_today` and `top_this_week`, each a list of picked events "
    "(event_slug, title, resolution_time, total_usd, trade_count, "
    "composite_score, leaning, tags). Write a punchy subject line, a 1-2 sentence "
    "intro, and for EACH event a short headline (<=10 words) and a 1-2 sentence "
    "blurb explaining why the smart money is interesting and which way we lean. "
    "Be concrete, no hype, no emojis. Do NOT invent prices or URLs. "
    "The `leaning` field is authoritative: it already names the exact side the "
    "smart money bought and the market's implied probability FOR THAT SIDE. Never "
    "invert it and never re-attribute its percentage to the opposite outcome — if "
    "leaning is 'No (36% implied)', that means the No side is priced at 36% (so "
    "the event is ~64% likely); do NOT write '36% on Yes'. State the side in plain "
    "words so a reader never has to guess what 'Yes'/'No' refers to. "
    "CRITICAL — write for a casual reader who does NOT follow esports or niche "
    "elections. Use `tags` to identify the domain. Every headline and blurb must "
    "be self-explanatory: name the sport/league/tournament and the matchup — "
    "never a bare team code or a standalone 'Game N'. Bad: 'Team Yandex backed in "
    "BLAST playoffs'. Good: 'Dota 2: smart money on Team Yandex in BLAST playoffs'. "
    "Bad: 'Sharp money backs KT in Game 4'. Good: 'LoL: sharps back KT vs DK in "
    "Game 4'. For political or geopolitical markets, name the countries/people "
    "involved and what is at stake — not just 'ceasefire extension' but 'US-Iran "
    "ceasefire extension'. "
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
                "category": category_label(p.get("tags")),
                "image": p.get("image"),
                "headline": w.get("headline") or p.get("title") or "",
                "blurb": w.get("blurb") or "",
                "leaning": p.get("leaning") or "No clear lean",
                "url": link_for_pick(p),
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


def render_email_html(content: dict, unsubscribe_url: str | None = None,
                      browser_url: str | None = None) -> str:
    """Self-contained, inline-styled HTML for pasting into Gmail. No <style>/<link>.
    When unsubscribe_url is given (one per recipient at send time), an unsubscribe
    line is appended to the footer; the pasted/preview version omits it. When
    browser_url is given, a 'View in browser' link to the on-site digest permalink
    is shown at the top."""
    wrap = "max-width:640px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;color:#111;"
    parts = [f'<div style="{wrap}">']
    # Hidden preheader — controls the inbox preview snippet instead of letting the
    # client scrape arbitrary body text.
    preheader = content.get("intro") or content.get("subject") or ""
    parts.append(
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">'
        f'{_esc(preheader)}</div>'
    )
    if browser_url:
        parts.append(
            '<p style="font-size:11px;color:#999;text-align:right;margin:0 0 8px;">'
            f'<a href="{_esc(browser_url)}" style="color:#999;">View in browser →</a></p>'
        )
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
            if item.get("image"):
                # Some Polymarket S3 keys contain literal spaces — encode them so
                # the <img src> isn't broken in strict clients (e.g. Gmail).
                img_src = str(item["image"]).replace(" ", "%20")
                parts.append(
                    f'<img src="{_esc(img_src)}" alt="" width="64" height="64" '
                    f'style="width:64px;height:64px;border-radius:8px;object-fit:cover;'
                    f'display:block;margin:0 0 6px;border:0;">'
                )
            if item.get("category"):
                parts.append(
                    f'<div style="font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:0.6px;color:#888;font-weight:bold;margin:0 0 3px;">'
                    f'{_esc(item["category"])}</div>'
                )
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
    footer = "PolySpotter — smart money on Polymarket."
    if unsubscribe_url:
        footer += (
            '<br>You\'re receiving this because you signed up at polyspotter.com. '
            f'<a href="{_esc(unsubscribe_url)}" style="color:#999;">Unsubscribe</a>.'
        )
    parts.append(
        '<p style="font-size:12px;color:#999;margin-top:28px;border-top:1px solid #eee;'
        f'padding-top:12px;">{footer}</p>'
    )
    parts.append('</div>')
    return "\n".join(parts)


# --- Database ----------------------------------------------------------------

def _get_conn():
    # Pin the session to UTC so date_trunc('day', now()) in the pool queries
    # frames "today" in the same UTC day as the Python-computed digest_date
    # (datetime.now(timezone.utc)). Without this, a non-UTC DB session could
    # shift the resolving-today window a day off from the digest's own date.
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=QUERY_TIMEOUT_SECONDS,
        options="-c timezone=UTC",
    )


_RESOLVING_TODAY_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE COALESCE(a.event_end_estimate, a.end_date) IS NOT NULL
      AND COALESCE(a.event_end_estimate, a.end_date) >= date_trunc('day', now())
      AND COALESCE(a.event_end_estimate, a.end_date) <  date_trunc('day', now()) + interval '1 day'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""

_WEEK_UPCOMING_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE COALESCE(a.event_end_estimate, a.end_date) > now()
      AND COALESCE(a.event_end_estimate, a.end_date) <= now() + interval '7 days'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""

_WEEK_HOT_SQL = """
    SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
        a.event_slug, a.condition_id, a.market_title, a.market_url, a.market_image,
        a.end_date, a.event_end_estimate, a.total_usd, a.trade_count,
        a.composite_score, a.llm_copy_action, a.tags
    FROM alerts a
    WHERE a.created_at >= now() - interval '7 days'
    ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
"""

# Digests published in the last few days — so the week pool doesn't re-feature the
# same handful of events for a week straight. date - int = date minus N days.
_RECENT_FEATURED_SQL = """
    SELECT content_json
    FROM digests
    WHERE digest_date >= (now() AT TIME ZONE 'UTC')::date - %s
"""


def fetch_recent_featured_slugs(days: int = FEATURED_LOOKBACK_DAYS) -> set:
    """event_slugs featured in digests over the last `days`. Best-effort: returns
    an empty set on any DB issue (e.g. digests table not yet migrated) so the
    dedup never blocks a run."""
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(_RECENT_FEATURED_SQL, (days,))
        slugs: set = set()
        for row in cur.fetchall():
            slugs |= extract_event_slugs(row[0])
        return slugs
    except Exception as err:
        log("digest_featured_lookup_failed", error=str(err))
        return set()
    finally:
        if conn is not None:
            conn.close()


def fetch_candidates() -> dict:
    """Query the three pools and return shaped, deduped candidate lists. Both
    pools enforce the conviction floor; week_pool also excludes anything already
    in resolving_today or featured in a recent digest, and is capped."""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(_RESOLVING_TODAY_SQL)
        today = dedupe_by_event([shape_candidate(dict(r)) for r in cur.fetchall()])
        cur.execute(_WEEK_UPCOMING_SQL)
        upcoming = [shape_candidate(dict(r)) for r in cur.fetchall()]
        cur.execute(_WEEK_HOT_SQL)
        hot = [shape_candidate(dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()

    today = [c for c in today if meets_conviction(c)]
    today_slugs = {c["event_slug"] for c in today}
    featured = fetch_recent_featured_slugs()
    week = build_week_pool(upcoming, hot, today_slugs, featured)
    return {"resolving_today": today, "week_pool": week}


# --- Persistence -------------------------------------------------------------

def output_dir() -> str:
    return DRY_RUNS_DIR if DRY_RUN else DIGESTS_DIR


def persist_digest(digest_date: str, run_id: str, content: dict) -> None:
    """Upsert the digest row (published). No-op in DRY_RUN."""
    if DRY_RUN:
        log("digest_persist_skipped_dry_run", digest_date=digest_date)
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO digests (digest_date, run_id, subject, intro,
                                     content_json, status, published_at)
                VALUES (%s, %s, %s, %s, %s, 'published', NOW())
                ON CONFLICT (digest_date) DO UPDATE SET
                    run_id       = EXCLUDED.run_id,
                    subject      = EXCLUDED.subject,
                    intro        = EXCLUDED.intro,
                    content_json = EXCLUDED.content_json,
                    status       = 'published',
                    published_at = NOW()
            """, (
                digest_date, run_id, content["subject"], content.get("intro", ""),
                json.dumps(content),
            ))
        conn.commit()
    finally:
        conn.close()


# --- Email delivery (Resend) -------------------------------------------------

# Only mail confirmed subscribers who haven't opted out.
_SUBSCRIBERS_SQL = """
    SELECT email, unsubscribe_token
    FROM subscribers
    WHERE unsubscribed_at IS NULL AND confirmed
    ORDER BY created_at
"""


def fetch_subscribers() -> list[dict]:
    """Active, confirmed subscribers as [{email, unsubscribe_token}, ...]."""
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(_SUBSCRIBERS_SQL)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def unsubscribe_url(token) -> str:
    return f"{UNSUBSCRIBE_BASE_URL}/api/unsubscribe?token={token}"


def send_digest(content: dict, subscribers: list[dict],
                browser_link: str | None = None) -> dict:
    """Send the digest to each subscriber via Resend, one personalized message
    apiece (each carries its own unsubscribe link + List-Unsubscribe headers).
    Never raises per-recipient — failures are logged and counted. Returns
    {"sent": int, "failed": int}."""
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not set — cannot send")
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    sent = failed = 0
    for sub in subscribers:
        unsub = unsubscribe_url(sub["unsubscribe_token"])
        body = {
            "from": DIGEST_FROM_EMAIL,
            "to": [sub["email"]],
            "subject": content["subject"],
            "html": render_email_html(content, unsubscribe_url=unsub,
                                      browser_url=browser_link),
            "headers": {
                "List-Unsubscribe": f"<{unsub}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
        try:
            resp = requests.post(RESEND_ENDPOINT, json=body, headers=headers, timeout=30)
            if resp.status_code >= 400:
                failed += 1
                log("digest_send_failed", email=sub["email"],
                    status=resp.status_code, body=resp.text[:300])
            else:
                sent += 1
                log("digest_sent", email=sub["email"],
                    id=(resp.json() or {}).get("id"))
        except requests.RequestException as err:
            failed += 1
            log("digest_send_error", email=sub["email"], error=str(err))
    return {"sent": sent, "failed": failed}


# --- Orchestration -----------------------------------------------------------

def main(argv=None) -> int:
    args = _parse_args(argv)
    run_id = uuid.uuid4().hex[:8]
    digest_date = datetime.now(timezone.utc).date().isoformat()
    log("digest_run_start", run_id=run_id, digest_date=digest_date,
        dry_run=DRY_RUN, send=args.send)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1

    candidates = fetch_candidates()
    n_today = len(candidates["resolving_today"])
    n_week = len(candidates["week_pool"])
    log("digest_candidates", run_id=run_id, resolving_today=n_today, week_pool=n_week)
    if n_today == 0 and n_week == 0:
        log("digest_noop", run_id=run_id, reason="no candidates")
        return 0

    # PICK
    selection = run_claude_json(PICK_PROMPT, json.dumps(candidates, default=str))
    by_slug = {c["event_slug"]: c
               for c in candidates["resolving_today"] + candidates["week_pool"]}
    today_picks = [by_slug[p["event_slug"]]
                   for p in selection.get("resolving_today", [])
                   if p.get("event_slug") in by_slug]
    week_picks = [by_slug[p["event_slug"]]
                  for p in selection.get("top_this_week", [])
                  if p.get("event_slug") in by_slug][:WEEK_PICKS_MAX]
    # Reorder each section so broad-appeal markets (geopolitics, big games) lead
    # and niche esports trail, independent of the LLM's returned order.
    today_picks = order_by_appeal(today_picks)
    week_picks = order_by_appeal(week_picks)
    log("digest_picked", run_id=run_id,
        today=len(today_picks), week=len(week_picks))
    if not today_picks and not week_picks:
        log("digest_noop", run_id=run_id, reason="nothing picked")
        return 0

    # WRITE
    write_payload = json.dumps(
        {"resolving_today": today_picks, "top_this_week": week_picks}, default=str)
    write_out = run_claude_json(WRITE_PROMPT, write_payload)
    content = assemble_content(write_out, today_picks, week_picks)
    browser_link = browser_url(digest_date)

    # Render email file
    os.makedirs(output_dir(), exist_ok=True)
    html_path = os.path.join(output_dir(), f"digest-{digest_date}.html")
    with open(html_path, "w") as f:
        f.write(render_email_html(content, browser_url=browser_link))
    log("digest_email_written", run_id=run_id, path=html_path)

    # Publish to website. The email file is already on disk, so a publish
    # failure is non-fatal for the operator — surface it clearly and exit
    # non-zero rather than crashing with a bare traceback. (If the digests
    # table is missing, the backend's init_db migration hasn't run yet.)
    try:
        persist_digest(digest_date, run_id, content)
    except Exception as err:
        log("digest_publish_failed", run_id=run_id, digest_date=digest_date,
            email=html_path, error=str(err))
        return 1

    # Email subscribers (opt-in via --send). In DRY_RUN we resolve the recipient
    # list but never call Resend, so the flag is safe to preview with.
    if args.send:
        subscribers = fetch_subscribers()
        if DRY_RUN:
            log("digest_send_skipped_dry_run", run_id=run_id,
                recipients=len(subscribers))
        elif not subscribers:
            log("digest_send_noop", run_id=run_id, reason="no subscribers")
        else:
            result = send_digest(content, subscribers, browser_link=browser_link)
            log("digest_send_done", run_id=run_id, **result)

    log("digest_run_done", run_id=run_id, digest_date=digest_date,
        published=not DRY_RUN, email=html_path)
    return 0


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate (and optionally email) the daily digest.")
    p.add_argument("--send", action="store_true",
                   help="Email the digest to confirmed subscribers via Resend "
                        "(no-op under DRY_RUN=true).")
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
