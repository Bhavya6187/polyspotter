"""
Daily X article generator for PolySpotter.

Picks ONE event-level story from the last 24h via a tournament picker, hands
it off to the existing `query`-tool research agent (run_agent in storybot.py),
and writes a 500-700 word article + cover chart for human paste into the X
article composer.

Run via cron:
    python storybot/articlebot.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid

from openai import OpenAI

from bot_utils import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    MODEL,
    _accumulate_usage,
    _gamma_status_for_markets,
    _is_settled,
    log,
    query_postgres,
)
from style_rules import STYLE_RULES
from tweet_utils import _BANNED_TWEET_PHRASES, _POLYSPOTTER_URL_RE

import storybot                  # for prefetch_bundle, run_agent, etc.
import articlebot_storage as _storage


# Tool-call budgets are higher than storybot's: articles need deeper research.
ARTICLE_MAX_TOOL_CALLS = 40
ARTICLE_MAX_ITERATIONS = 35


SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service
that surfaces notable bets on Polymarket (whales, sharp wallets, coordinated
flow, informed edge). Once a day, a cron triggers you to look at what sharp
money has done in the last 24 hours and write ONE short X article (~600
words) about the most interesting story.

Audience: a general audience. Curious news readers, not desk traders. People
who follow the news but don't speak desk slang. The article should be
comprehensible without jargon and should make a stranger care about a
specific bet on a specific market.

## Your job, in order

1. The kickoff message contains the alert(s) for the chosen event, picked by
   a tournament-picker upstream. Their full fields are embedded; no need to
   re-query.

2. RESEARCH. A great article cites specific, surprising facts the raw alerts
   don't already contain. Same data sources storybot's thread bot uses:
   - The wallet(s) — wallet_profiles, wallet_funders, wallet_event_history,
     Data API /trades?user=…
   - The market(s) — Gamma /markets, CLOB /prices-history, /book
   - The event — Gamma /events?slug=…, alerts on the same tag, wallet_theses
   You have ONE research tool: `query(intent, hint?)` — describe WHAT you
   want in natural language. The compressor picks the backend.

3. WRITE the article.

## Article shape (~500-700 words)

- **Headline** — ≤90 chars. Specific. Stakes baked in. NOT a summary; a hook.
- **Subhead** — ≤160 chars. One sentence that adds context the headline
  doesn't have room for. Don't restate the headline.
- **Body markdown** — 450-800 words (target 500-700). Three to four `## H2`
  sections. Pick from this menu:
    - `## The wallet` (or `## The squad` for clusters)
    - `## The bet`
    - `## What the market thinks`
    - `## What to watch`
    - `## The track record`
    - `## The other side`
  Pick 3-4 that fit your story. The article is one continuous piece of
  prose with these section breaks — not a bulleted list.

  Open with a 2-3 sentence opening paragraph BEFORE the first H2 — the hook
  paragraph that makes the reader keep reading. Close with a paragraph
  AFTER the last H2 — the catalyst, level, or wallet to track.

- **Polyspotter link(s) MANDATORY** — at least one inline markdown link
  somewhere in the body. Prefer the closing paragraph. Use up to 2 links.
  Build URLs against `https://polyspotter.com`:
    - market: `https://polyspotter.com/market/<slug>` where <slug> is
      kebab-cased market_title (lowercase, non-alnum → single dash, max 80
      chars) + "-" + first 7 chars of `condition_id`.
    - wallet: `https://polyspotter.com/wallet/<full 0x address>`
    - alert:  `https://polyspotter.com/alert/<id>`
    - tag:    `https://polyspotter.com/tag/<tag-slug>`

- **Cover chart** — pick ONE chart from this menu, or null if no chart fits:
    - `wallet_record_card` — when one sharp wallet's track record carries the story
    - `price_sparkline`    — when the market's price moved
    - `volume_bar`         — when there was a volume surge
    - `cluster_card`       — when a coordinated squad is the story
    - null                 — when no chart adds anything

- **Cover alt text** — ≤200 chars. Plain English description of the chart.

{STYLE_RULES}

## When to skip

If research reveals the picked event is weaker than it looked (track record
softer than the signals suggested, no surprising numbers beyond what's
already in the alert, the narrative just doesn't hold up for a general
audience), return decision=skip. Don't force an article.

## Output format (strict JSON — your final assistant content)

{{
  "decision": "post" | "skip",
  "reason": "one short sentence",
  "article": {{
    "headline": "...",
    "subhead": "...",
    "body_markdown": "...",
    "cover_alt_text": "..."
  }},
  "alert_ids": [<int>, ...],
  "cover_chart_spec": {{
    "chart_type": "wallet_record_card" | "price_sparkline" |
                  "volume_bar" | "cluster_card",
    "alert_id": <int>,
    "params": {{}}
  }}
}}

When decision=skip, set `article` and `cover_chart_spec` to null and
`alert_ids` to null.

Budget: up to {ARTICLE_MAX_TOOL_CALLS} tool calls. If you hit the budget,
write the article with what you have — do not keep digging.
"""


# 24h SQL: alerts grouped by event_slug, with rich JSON_AGG for downstream
# pickers. Same sports/non-sports time filter as fetch_seed_alerts so we
# don't shortlist already-decided events.
EVENT_SUMMARIES_SQL = """
    SELECT
        a.event_slug,
        MAX(a.composite_score)        AS top_composite,
        SUM(a.total_usd)              AS event_usd,
        COUNT(*)                      AS alert_count,
        (
            SELECT array_agg(DISTINCT s.strategy)
            FROM alert_signals s
            JOIN alerts a2 ON a2.id = s.alert_id
            WHERE a2.event_slug = a.event_slug
              AND s.strategy IS NOT NULL
        ) AS strategies_fired,
        JSONB_AGG(jsonb_build_object(
            'id', a.id,
            'composite_score', a.composite_score,
            'alert_type', a.alert_type,
            'market_title', a.market_title,
            'condition_id', a.condition_id,
            'wallet', a.wallet,
            'total_usd', a.total_usd,
            'tags', a.tags,
            'llm_headline', a.llm_headline,
            'cluster_headline', a.cluster_headline,
            'game_start_time', a.game_start_time,
            'event_end_estimate', a.event_end_estimate,
            'end_date', a.end_date,
            'created_at', a.created_at,
            'signals', COALESCE(sig.signals, '[]'::jsonb)
        ) ORDER BY a.composite_score DESC) AS alerts,
        (ARRAY_AGG(a.condition_id ORDER BY a.composite_score DESC))[1] AS top_condition_id,
        MIN(a.created_at)             AS first_alert_at,
        MAX(a.created_at)             AS last_alert_at
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
    ) sig ON true
    WHERE a.created_at >= NOW() - INTERVAL '24 hours'
      AND (
          (a.game_start_time IS NOT NULL AND a.game_start_time > NOW())
          OR (a.game_start_time IS NULL
              AND COALESCE(a.event_end_estimate, a.end_date) > NOW())
      )
      AND a.event_slug IS NOT NULL
    GROUP BY a.event_slug
    ORDER BY top_composite DESC
    LIMIT 300
"""


def fetch_24h_event_summaries() -> list[dict]:
    """All events with at least one alert in the last 24h, settled events
    filtered out via Gamma. Returns up to 300 rows ordered by top_composite DESC.
    """
    candidates = query_postgres(EVENT_SUMMARIES_SQL)
    if not candidates:
        return []

    cids = [c["top_condition_id"] for c in candidates if c.get("top_condition_id")]
    status_by_cid = _gamma_status_for_markets(cids)

    kept: list[dict] = []
    n_settled = 0
    for row in candidates:
        cid = row.get("top_condition_id")
        if cid and _is_settled(status_by_cid.get(cid)):
            n_settled += 1
            continue
        kept.append(row)

    log("articlebot_event_summaries",
        sql_candidates=len(candidates),
        gamma_settled=n_settled,
        kept=len(kept))
    return kept


PICKER_STAGE1_SYSTEM_PROMPT = """You are surfacing the most STORY-WORTHY events
for a daily Polymarket article aimed at a general audience (curious news
readers, not pros).

You see up to 40 events from the last 24 hours, each with: top composite_score,
total $ across alerts, distinct strategies that fired, and the top alerts on
that event.

Pick the TOP 3 events by storytelling potential — NOT by composite_score alone.
A high-score event with no human angle is less interesting than a medium-score
event with a sharp-wallet character, a coordinated squad, a surprise market,
or late-game timing. Favor:

- Specific characters (one wallet's track record, a new account, a cluster)
- Surprising contrasts (an obscure market with sudden volume; a sharp wallet
  on the contrarian side)
- Concrete catalysts a reader can watch (game tonight; resolution this week)

Avoid: events that are just "big bet, no story", or events that look like
duplicates of other recent ones.

If a chunk has fewer than 3 events, return all of them. Skip is NOT an option
in this stage — pick the best 3 you've got. The next stage handles skipping.

Return strict JSON:
{"finalists": ["slug-a", "slug-b", "slug-c"], "reasoning": "<one sentence>"}
"""


_PICKER_STAGE1_FIELDS = (
    "event_slug", "top_composite", "event_usd", "alert_count",
    "strategies_fired", "first_alert_at", "last_alert_at",
)
_PICKER_STAGE1_ALERT_FIELDS = (
    "id", "composite_score", "alert_type", "market_title", "wallet",
    "total_usd", "llm_headline", "cluster_headline",
)


def _compact_event_for_picker(event: dict) -> dict:
    """Trim an event row down to the fields the picker needs."""
    out = {k: event.get(k) for k in _PICKER_STAGE1_FIELDS if event.get(k) is not None}
    alerts = event.get("alerts") or []
    if alerts:
        out["top_alerts"] = [
            {k: a.get(k) for k in _PICKER_STAGE1_ALERT_FIELDS if a.get(k) is not None}
            for a in alerts[:3]
        ]
    return out


def pick_finalists_chunk(llm_client, chunk: list[dict],
                         *, usage: dict | None = None) -> list[str]:
    """Run one stage-1 picker LLM call over up to 40 events. Returns up to 3
    `event_slug` strings. Empty list on any error or invalid JSON.
    """
    if not chunk:
        return []

    compact = [_compact_event_for_picker(e) for e in chunk]
    user_msg = (
        f"{len(compact)} events from the last 24h, sorted by composite_score "
        f"DESC:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PICKER_STAGE1_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=1,
            max_completion_tokens=4000,
            reasoning_effort="medium",
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        log("articlebot_stage1_error", error=f"{type(exc).__name__}: {exc}")
        return []

    if usage is not None:
        _accumulate_usage(usage, response)

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        log("articlebot_stage1_invalid_json", error=str(exc))
        return []

    finalists = parsed.get("finalists") or []
    if not isinstance(finalists, list):
        return []

    valid_slugs = {e["event_slug"] for e in chunk}
    return [s for s in finalists if isinstance(s, str) and s in valid_slugs][:3]


PICKER_STAGE2_SYSTEM_PROMPT = """You pick the SINGLE BEST story for today's
Polymarket article — or skip if nothing on this list is good enough to write
about for a general audience.

Constraints:
- The article will be ~600 words. It will quote specific numbers. It is the
  ONLY thing we publish today.
- The audience is curious news readers, not pros. The story should be
  comprehensible without trader jargon — pick a story that has a real human
  hook (a sharp wallet, a coordinated squad, a surprising market, late timing).
- Avoid generic "big bet" stories with no character.
- Recently-covered events MUST BE SKIPPED unless something materially new
  has happened (a new sharper wallet, a meaningful price move, a resolution).

If you pick an event, return the alert_ids that belong to that event from
the data shown to you (NOT alert_ids from elsewhere — only the alerts already
listed on your chosen event_slug).

Voice context: smart financial Twitter that a curious news-following adult
who doesn't speak desk slang can read. Same publication as the existing
PolySpotter thread bot.

Return strict JSON:
{
  "decision": "post" | "skip",
  "event_slug": "<slug>" | null,
  "alert_ids": [<int>, ...] | null,
  "reason": "<one short sentence>"
}
"""


def pick_final_event(llm_client, finalists: list[dict],
                     *, recent_event_slugs: list[str],
                     usage: dict | None = None) -> dict:
    """Run the stage-2 final picker. Returns a decision dict (the same shape
    storybot.pick_story produces today, plus an explicit `event_slug`).

    On any LLM error or invalid JSON, returns decision=skip with the error
    message in `reason`. Defense-in-depth: if the model returns an
    `event_slug` not in the finalists, also returns skip.
    """
    if not finalists:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "no finalists from stage 1"}

    compact = [_compact_event_for_picker(e) for e in finalists]
    # Re-attach the full alerts (not just top_alerts) so the model can pick
    # specific alert_ids belonging to the chosen event.
    for c, src in zip(compact, finalists):
        c["alerts"] = src.get("alerts") or []

    user_msg = (
        f"Stage-2 finalists ({len(compact)} events):\n"
        f"{json.dumps(compact, default=str, indent=2)}\n\n"
        f"recent_event_slugs (already covered in last 7 days, skip unless "
        f"materially new): {json.dumps(recent_event_slugs)}"
    )

    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": PICKER_STAGE2_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=1,
            max_completion_tokens=8000,
            reasoning_effort="high",
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": f"stage-2 LLM error: {type(exc).__name__}: {exc}"}

    if usage is not None:
        _accumulate_usage(usage, response)

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": f"stage-2 returned invalid JSON: {exc}"}

    if parsed.get("decision") == "post":
        chosen_slug = parsed.get("event_slug")
        valid_slugs = {e["event_slug"] for e in finalists}
        if chosen_slug not in valid_slugs:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": f"stage-2 returned unknown event_slug: {chosen_slug!r}"}

    return {
        "decision": parsed.get("decision", "skip"),
        "event_slug": parsed.get("event_slug"),
        "alert_ids": parsed.get("alert_ids"),
        "reason": parsed.get("reason") or "",
    }


PICKER_CHUNK_SIZE = 40
RECENT_ARTICLES_WINDOW_DAYS = 7


def fetch_recent_article_slugs() -> list[str]:
    """event_slugs we've published in the last RECENT_ARTICLES_WINDOW_DAYS
    days (skipped rows excluded — see spec § Decisions)."""
    sql = f"""
        SELECT DISTINCT event_slug
        FROM articles
        WHERE created_at >= NOW() - INTERVAL '{RECENT_ARTICLES_WINDOW_DAYS} days'
          AND status != 'skipped'
    """
    try:
        rows = query_postgres(sql)
    except Exception as exc:
        log("articlebot_recent_slugs_error", error=f"{type(exc).__name__}: {exc}")
        return []
    return [r["event_slug"] for r in rows if r.get("event_slug")]


def pick_article_story(llm_client, *, usage: dict | None = None) -> dict:
    """Tournament picker. Returns a dict shaped like pick_final_event's output
    plus the chosen event's full alerts list (so caller can resolve alert_ids
    to alert dicts without a second query)."""
    events = fetch_24h_event_summaries()
    if not events:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "no events in the last 24h"}

    # Stage 1: chunked finalist picker
    finalist_slugs: list[str] = []
    for i in range(0, len(events), PICKER_CHUNK_SIZE):
        chunk = events[i:i + PICKER_CHUNK_SIZE]
        finalist_slugs.extend(pick_finalists_chunk(llm_client, chunk, usage=usage))

    # Dedup while preserving order
    seen: dict[str, None] = {}
    for s in finalist_slugs:
        seen.setdefault(s, None)
    finalist_slugs = list(seen)

    finalists = [e for e in events if e["event_slug"] in seen]
    log("articlebot_stage1_done",
        chunk_count=(len(events) + PICKER_CHUNK_SIZE - 1) // PICKER_CHUNK_SIZE,
        finalists=len(finalists))

    if not finalists:
        return {"decision": "skip", "event_slug": None, "alert_ids": None,
                "reason": "stage 1 produced no finalists"}

    # Stage 2: final picker
    recent = fetch_recent_article_slugs()
    decision = pick_final_event(llm_client, finalists,
                                recent_event_slugs=recent, usage=usage)

    # Attach the chosen event's alerts so downstream can resolve alert_ids → alert dicts
    if decision["decision"] == "post":
        chosen = next((e for e in finalists if e["event_slug"] == decision["event_slug"]), None)
        if chosen is None:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": "stage-2 chose an event not in finalists (post-validation)"}
        wanted_ids = set(decision["alert_ids"] or [])
        chosen_alerts = [a for a in (chosen.get("alerts") or []) if a.get("id") in wanted_ids]
        if not chosen_alerts:
            return {"decision": "skip", "event_slug": None, "alert_ids": None,
                    "reason": f"stage-2 returned alert_ids not in chosen event"}
        decision["chosen_alerts"] = chosen_alerts

    return decision


# ---------------------------------------------------------------------------
# Article output validator
# ---------------------------------------------------------------------------

HEADLINE_MAX_CHARS = 90
SUBHEAD_MAX_CHARS = 160
COVER_ALT_MAX_CHARS = 200
BODY_WORD_MIN = 450
BODY_WORD_MAX = 800
BODY_H2_MIN = 3
BODY_H2_MAX = 4

_H2_LINE_RE = re.compile(r"(?m)^## \S")
_WORD_RE = re.compile(r"\w+")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def validate_article_decision(decision: dict) -> tuple[bool, str]:
    """Returns (ok, error_message). Mirrors the contract of
    storybot.validate_decision but for article output shape."""
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"

    article = decision.get("article")
    if not isinstance(article, dict):
        return False, "article must be an object when decision=post"

    headline = article.get("headline") or ""
    if not isinstance(headline, str) or not headline.strip():
        return False, "article.headline must be a non-empty string"
    if len(headline) > HEADLINE_MAX_CHARS:
        return False, f"article.headline length {len(headline)} exceeds {HEADLINE_MAX_CHARS}"

    subhead = article.get("subhead") or ""
    if not isinstance(subhead, str) or not subhead.strip():
        return False, "article.subhead must be a non-empty string"
    if len(subhead) > SUBHEAD_MAX_CHARS:
        return False, f"article.subhead length {len(subhead)} exceeds {SUBHEAD_MAX_CHARS}"

    cover_alt = article.get("cover_alt_text") or ""
    if cover_alt and len(cover_alt) > COVER_ALT_MAX_CHARS:
        return False, f"article.cover_alt_text length {len(cover_alt)} exceeds {COVER_ALT_MAX_CHARS}"

    body = article.get("body_markdown") or ""
    if not isinstance(body, str) or not body.strip():
        return False, "article.body_markdown must be a non-empty string"

    wc = _word_count(body)
    if not (BODY_WORD_MIN <= wc <= BODY_WORD_MAX):
        return False, f"body word count {wc} outside [{BODY_WORD_MIN}, {BODY_WORD_MAX}]"

    h2_count = len(_H2_LINE_RE.findall(body))
    if not (BODY_H2_MIN <= h2_count <= BODY_H2_MAX):
        return False, f"body has {h2_count} H2 sections, expected {BODY_H2_MIN}-{BODY_H2_MAX}"

    if not _POLYSPOTTER_URL_RE.search(body):
        return False, "body must contain at least one polyspotter.com link"

    body_lower = body.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in body_lower:
            return False, f"body contains banned phrase {phrase!r}"

    alert_ids = decision.get("alert_ids") or []
    if not isinstance(alert_ids, list) or not alert_ids:
        return False, "alert_ids must be a non-empty list when decision=post"
    try:
        [int(i) for i in alert_ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {alert_ids!r}"

    return True, ""


# ---------------------------------------------------------------------------
# Cover chart renderer
# ---------------------------------------------------------------------------

def _dispatch_chart_render(chart_type: str, alert: dict) -> bytes | None:
    """Thin wrapper around storybot/charts.render_chart_for_alert. Tested
    separately via monkeypatch. May raise; caller catches."""
    import charts
    return charts.render_chart_for_alert(chart_type, alert)


def render_cover_chart(spec: dict | None, chosen_alerts: list[dict],
                       out_path: str) -> str | None:
    """Render the cover chart specified by `cover_chart_spec`. Returns the
    output path on success, None on any failure (soft fault). When spec is
    null, returns None without touching the filesystem."""
    if not spec:
        return None
    chart_type = spec.get("chart_type")
    alert_id = spec.get("alert_id")
    if not chart_type:
        return None
    alert = next((a for a in chosen_alerts if a.get("id") == alert_id), None)
    if alert is None:
        log("articlebot_chart_skip", reason=f"alert_id {alert_id} not in chosen_alerts")
        return None
    try:
        png_bytes = _dispatch_chart_render(chart_type, alert)
    except Exception as exc:
        log("articlebot_chart_error",
            chart_type=chart_type, alert_id=alert_id,
            error=f"{type(exc).__name__}: {exc}")
        return None
    if not png_bytes:
        log("articlebot_chart_empty", chart_type=chart_type, alert_id=alert_id)
        return None
    try:
        with open(out_path, "wb") as f:
            f.write(png_bytes)
    except OSError as exc:
        log("articlebot_chart_write_error",
            out_path=out_path, error=f"{type(exc).__name__}: {exc}")
        return None
    return out_path


# ---------------------------------------------------------------------------
# Dry-run configuration and helpers
# ---------------------------------------------------------------------------

ARTICLEBOT_DRY_RUN = os.environ.get("ARTICLEBOT_DRY_RUN", "false").lower() == "true"

_DRY_RUN_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dry_runs"
)


def _build_kickoff_message(chosen_alerts: list[dict]) -> tuple[str, dict, dict]:
    """Build the article-shaped kickoff message. Returns (message, scope, prefetched).

    Uses storybot's prefetched-block format but with article-specific framing.
    """
    scope = storybot._derive_scope(chosen_alerts)
    prefetched = storybot.prefetch_bundle(scope)
    prefix = storybot._format_prefetched_block(prefetched) if prefetched else ""

    if len(chosen_alerts) == 1:
        payload = json.dumps(chosen_alerts[0], default=str, indent=2)
        body = (
            "A 24h tournament picker chose THIS alert as the day's article "
            "story. Research it deeply with the query tool, then write a "
            "~600 word X article — or skip if research reveals it's not "
            "actually a great story for a general audience.\n\n"
            f"chosen_alert:\n{payload}"
        )
    else:
        slug = chosen_alerts[0].get("event_slug") or "(unknown event)"
        payload = json.dumps(chosen_alerts, default=str, indent=2)
        body = (
            f"A 24h tournament picker chose these {len(chosen_alerts)} alerts "
            f"— all on event '{slug}' — as the day's article story. Treat "
            "them as ONE story. Research deeply with the query tool, then "
            "write a ~600 word X article — or skip if research reveals it's "
            "not actually a great story for a general audience.\n\n"
            f"chosen_alerts ({len(chosen_alerts)} rows):\n{payload}"
        )
    return prefix + body, scope, prefetched


def _dump_dry_run(run_id: str, *, pick: dict, decision: dict | None,
                  transcript: list | None, usage: dict, error: str | None) -> str:
    """Dump the run state to dry_runs/articlebot_<run_id>.json for inspection."""
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"articlebot_{run_id}.json")
    payload = {
        "run_id": run_id,
        "model": MODEL,
        "max_tool_calls": ARTICLE_MAX_TOOL_CALLS,
        "max_iterations": ARTICLE_MAX_ITERATIONS,
        "pick": pick,
        "transcript": transcript or [],
        "final_decision": decision,
        "error": error,
        "llm_usage": usage,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _retry_with_validation_hint(llm_client, transcript: list, error_msg: str,
                                usage: dict | None) -> dict | None:
    """Make ONE more LLM call appending a targeted validation hint.

    Appends a user message naming the violated rule, sends the full transcript
    to the model with tool_choice="none" and json_object response format, and
    returns the parsed decision dict.  Returns None if the response is not
    valid JSON (caller treats None as a second failure).
    """
    transcript.append({
        "role": "user",
        "content": (
            f"Your previous article failed validation: {error_msg}. "
            "Please return a corrected JSON object that fixes this issue. "
            "Same schema as before."
        ),
    })
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=transcript,
        temperature=1,
        max_completion_tokens=12000,
        tool_choice="none",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    transcript.append({"role": "assistant", "content": content})
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None  # caller treats None as a second failure


def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    log("articlebot_run_start", run_id=run_id, dry_run=ARTICLEBOT_DRY_RUN)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    usage_totals: dict = {}
    # Always capture the messages list so we can use it for the validation
    # retry path (transcript is a few KB; cost is negligible).
    messages_list: list = []
    transcript: list = messages_list

    # Stage 1+2: tournament pick
    pick = pick_article_story(llm_client, usage=usage_totals)
    log("articlebot_pick", run_id=run_id, decision=pick.get("decision"),
        event_slug=pick.get("event_slug"), reason=pick.get("reason"))

    if pick["decision"] != "post":
        if not ARTICLEBOT_DRY_RUN:
            try:
                _storage.record_skipped_run(run_id=run_id,
                                            event_slug=pick.get("event_slug") or "",
                                            reason=pick.get("reason") or "")
            except Exception as exc:
                log("articlebot_skip_record_error", run_id=run_id,
                    error=f"{type(exc).__name__}: {exc}")
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=None,
                          transcript=transcript, usage=usage_totals, error=None)
        return 0

    chosen_alerts = pick.get("chosen_alerts") or []

    # Stage 3: research + write
    kickoff, _scope, _prefetched = _build_kickoff_message(chosen_alerts)
    try:
        decision = storybot.run_agent(
            llm_client,
            chosen_alerts=chosen_alerts,
            transcript=messages_list,
            usage=usage_totals,
            system_prompt=SYSTEM_PROMPT,
            kickoff_message=kickoff,
            max_tool_calls=ARTICLE_MAX_TOOL_CALLS,
            max_iterations=ARTICLE_MAX_ITERATIONS,
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        log("articlebot_agent_error", run_id=run_id, error=err)
        if not ARTICLEBOT_DRY_RUN:
            try:
                _storage.record_skipped_run(run_id=run_id,
                                            event_slug=pick.get("event_slug") or "",
                                            reason=f"agent error: {err}")
            except Exception:
                pass
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=None,
                          transcript=transcript, usage=usage_totals, error=err)
        return 1

    # Carry the chosen event_slug into the decision (downstream needs it)
    decision["event_slug"] = pick["event_slug"]

    # Validate — with a one-shot retry on first failure
    ok, err = validate_article_decision(decision)
    if not ok:
        log("articlebot_validation_retry", run_id=run_id, error=err)
        retry_decision = _retry_with_validation_hint(
            llm_client, messages_list, err, usage_totals,
        )
        if retry_decision is not None:
            retry_decision["event_slug"] = pick["event_slug"]
            ok, err = validate_article_decision(retry_decision)
            if ok:
                decision = retry_decision
    if not ok:
        log("articlebot_validation_error", run_id=run_id, error=err)
        if not ARTICLEBOT_DRY_RUN:
            try:
                _storage.record_skipped_run(run_id=run_id,
                                            event_slug=pick.get("event_slug") or "",
                                            reason=f"validation: {err}")
            except Exception:
                pass
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=decision,
                          transcript=transcript, usage=usage_totals,
                          error=f"validation: {err}")
        return 1

    if decision["decision"] == "skip":
        log("articlebot_skip", run_id=run_id, reason=decision.get("reason"))
        if not ARTICLEBOT_DRY_RUN:
            try:
                _storage.record_skipped_run(run_id=run_id,
                                            event_slug=pick.get("event_slug") or "",
                                            reason=decision.get("reason") or "")
            except Exception:
                pass
        if ARTICLEBOT_DRY_RUN:
            _dump_dry_run(run_id, pick=pick, decision=decision,
                          transcript=transcript, usage=usage_totals, error=None)
        return 0

    # Stage 4: cover chart
    cover_target_dir = _DRY_RUN_DIR if ARTICLEBOT_DRY_RUN else _storage.ARTICLES_DIR
    os.makedirs(cover_target_dir, exist_ok=True)
    cover_path_target = os.path.join(cover_target_dir, f"{run_id}.png")
    cover_path = render_cover_chart(decision.get("cover_chart_spec"),
                                    chosen_alerts, cover_path_target)

    # Stage 5: persist
    if ARTICLEBOT_DRY_RUN:
        # Write the .md file into dry_runs (not articles/) and dump a transcript
        md_text = _storage._format_md_file(run_id, decision, cover_path)
        md_path = os.path.join(_DRY_RUN_DIR, f"{run_id}.md")
        with open(md_path, "w") as f:
            f.write(md_text)
        _dump_dry_run(run_id, pick=pick, decision=decision,
                      transcript=transcript, usage=usage_totals, error=None)
        print(f"[articlebot dry-run] md={md_path} cover={cover_path or 'none'}")
        return 0

    try:
        result = _storage.persist_article(
            run_id=run_id, decision=decision, cover_path=cover_path,
        )
    except Exception as exc:
        log("articlebot_persist_error", run_id=run_id,
            error=f"{type(exc).__name__}: {exc}")
        return 1

    print(f"[articlebot] run_id={run_id} md={result['md_path']} "
          f"cover={cover_path or 'none'} words={result['word_count']}")
    print(f"[articlebot] paste into X composer, then: "
          f"python storybot/mark_published.py {run_id} <x_article_url>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
