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

from bot_utils import (
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
        ARRAY_AGG(DISTINCT s.strategy)
            FILTER (WHERE s.strategy IS NOT NULL) AS strategies_fired,
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
            'created_at', a.created_at
        ) ORDER BY a.composite_score DESC) AS alerts,
        (ARRAY_AGG(a.condition_id ORDER BY a.composite_score DESC))[1] AS top_condition_id,
        MIN(a.created_at)             AS first_alert_at,
        MAX(a.created_at)             AS last_alert_at
    FROM alerts a
    LEFT JOIN alert_signals s ON s.alert_id = a.id
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
