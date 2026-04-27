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
