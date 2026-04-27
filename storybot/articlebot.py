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

from bot_utils import (
    MODEL,
    _accumulate_usage,
    _gamma_status_for_markets,
    _is_settled,
    log,
    query_postgres,
)


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
