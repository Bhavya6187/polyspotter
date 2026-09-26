"""
SEO worker — standalone backfill of market SEO, event hydration, and event SEO.

Lives outside the FastAPI process: external HTTP/LLM calls inside DB
transactions caused idle-in-transaction orphans on Railway Postgres
(see incident 2026-05-07). This script does ONE pass and exits. Intended
to be wrapped in a shell loop:

    screen -S polyspotter-seo
    source venv/bin/activate
    while true; do python backend/seo_worker.py; sleep 600; done
    # Ctrl+A, D to detach

Connections are autocommit, so every UPDATE is its own transaction —
no transaction is ever held open across an LLM/Gamma HTTP call.
"""

from __future__ import annotations

import json
import sys
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from database import get_conn  # noqa: E402
from events import upsert_event  # noqa: E402
from seo_generator import ContentFilterError, generate_seo_content  # noqa: E402
from event_seo_generator import generate_event_seo_content  # noqa: E402

MARKET_SEO_LIMIT = 10
EVENT_HYDRATE_LIMIT = 20
EVENT_SEO_LIMIT = 5

# Markets and events resolving sooner than this get no SEO page copy: 47% of
# alerted markets end within a day of their first alert and 70% within three,
# while market pages drew 63 organic-search sessions in 30 days — the page is
# dead before a crawler can index it (2026-09-26 cost review). Such rows are
# stamped seo_skip_reason='short_lived' so they leave the candidate pool.
SEO_MIN_DAYS_TO_END = 3

_SKIP_SHORT_LIVED_MARKETS_SQL = """
    UPDATE alerts SET seo_skip_reason = 'short_lived'
    WHERE seo_generated_at IS NULL
      AND seo_skip_reason IS NULL
      AND condition_id IS NOT NULL
      AND end_date IS NOT NULL
      AND end_date < NOW() + make_interval(days => %s)
"""

_SKIP_SHORT_LIVED_EVENTS_SQL = """
    UPDATE events SET seo_skip_reason = 'short_lived'
    WHERE seo_generated_at IS NULL
      AND seo_skip_reason IS NULL
      AND end_date IS NOT NULL
      AND end_date < NOW() + make_interval(days => %s)
"""


def _autocommit_conn():
    conn = get_conn()
    conn.autocommit = True
    return conn


def _parse_tags(raw) -> list[str]:
    """Tags column is JSON: list[str] for alerts, list[{label}] for events."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    for item in parsed:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("label"):
            out.append(item["label"])
    return out


# New alert rows land with seo_generated_at NULL even when their market already
# has SEO; copy the market's existing fields onto them instead of treating the
# market as a fresh candidate (which re-sent it to GPT on every new alert).
_COPY_EXISTING_MARKET_SEO_SQL = """
    UPDATE alerts a SET
        seo_title = src.seo_title,
        seo_description = src.seo_description,
        seo_summary = src.seo_summary,
        seo_faqs = src.seo_faqs,
        seo_generated_at = src.seo_generated_at
    FROM (
        SELECT DISTINCT ON (s.condition_id)
               s.condition_id, s.seo_title, s.seo_description, s.seo_summary,
               s.seo_faqs, s.seo_generated_at
        FROM alerts s
        WHERE s.seo_generated_at IS NOT NULL
          AND s.seo_title IS NOT NULL
          AND s.condition_id IN (
              SELECT condition_id FROM alerts
              WHERE seo_generated_at IS NULL AND condition_id IS NOT NULL
          )
        ORDER BY s.condition_id, s.seo_generated_at DESC
    ) src
    WHERE a.condition_id = src.condition_id
      AND a.seo_generated_at IS NULL
"""


def run_market_seo() -> int:
    generated = 0
    with closing(_autocommit_conn()) as conn:
        with conn.cursor() as cur:
            cur.execute(_COPY_EXISTING_MARKET_SEO_SQL)
            cur.execute(_SKIP_SHORT_LIVED_MARKETS_SQL, (SEO_MIN_DAYS_TO_END,))
            cur.execute("""
                SELECT condition_id, MAX(market_title) as market_title,
                       MAX(market_description) as market_description,
                       MAX(tags) as tags, MAX(end_date::text) as end_date,
                       SUM(total_usd) as total_usd, COUNT(*) as alert_count,
                       MAX(scanned_at) as latest_scanned_at
                FROM alerts
                WHERE condition_id IS NOT NULL
                  AND seo_generated_at IS NULL
                  AND seo_skip_reason IS NULL
                  AND market_title IS NOT NULL
                GROUP BY condition_id
                ORDER BY latest_scanned_at DESC
                LIMIT %s
            """, (MARKET_SEO_LIMIT,))
            candidates = cur.fetchall()

        for row in candidates:
            cid = row["condition_id"]

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT llm_headline FROM alerts
                    WHERE condition_id = %s AND llm_headline IS NOT NULL
                    ORDER BY composite_score DESC LIMIT 5
                """, (cid,))
                headlines = [r["llm_headline"] for r in cur.fetchall()]

            try:
                result = generate_seo_content(
                    market_title=row["market_title"],
                    description=row.get("market_description"),
                    tags=_parse_tags(row["tags"]),
                    end_date=row.get("end_date"),
                    total_usd=row["total_usd"] or 0,
                    alert_count=row["alert_count"] or 0,
                    alert_headlines=headlines,
                )
            except ContentFilterError:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE alerts SET seo_skip_reason = 'content_filter' WHERE condition_id = %s",
                        (cid,),
                    )
                print(
                    f"[seo_worker:market] content-filtered, skipping permanently: {row['market_title']}",
                    flush=True,
                )
                continue
            except Exception as e:
                print(f"[seo_worker:market] LLM error for {row['market_title']}: {e}", flush=True)
                continue

            if not result:
                continue

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE alerts SET
                        seo_title = %s,
                        seo_description = %s,
                        seo_summary = %s,
                        seo_faqs = %s,
                        seo_generated_at = NOW()
                    WHERE condition_id = %s
                """, (
                    result["seo_title"],
                    result["seo_description"],
                    result["seo_summary"],
                    json.dumps(result["seo_faqs"]),
                    cid,
                ))
            generated += 1
            print(f"[seo_worker:market] {row['market_title']}", flush=True)
    return generated


def run_event_hydration() -> int:
    hydrated = 0
    with closing(_autocommit_conn()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT event_slug FROM events
                WHERE title IS NULL
                ORDER BY fetched_at DESC
                LIMIT %s
            """, (EVENT_HYDRATE_LIMIT,))
            slugs = [r["event_slug"] for r in cur.fetchall()]

    for slug in slugs:
        try:
            row = upsert_event(slug)
        except Exception as e:
            print(f"[seo_worker:hydrate] error for {slug}: {e}", flush=True)
            continue
        if row and row.get("title"):
            hydrated += 1
            print(f"[seo_worker:hydrate] {slug}", flush=True)
    return hydrated


def run_event_seo() -> int:
    generated = 0
    with closing(_autocommit_conn()) as conn:
        with conn.cursor() as cur:
            cur.execute(_SKIP_SHORT_LIVED_EVENTS_SQL, (SEO_MIN_DAYS_TO_END,))
            cur.execute("""
                SELECT e.event_slug, e.title, e.description,
                       e.end_date::text AS end_date, e.tags
                FROM events e
                WHERE e.title IS NOT NULL
                  AND e.seo_generated_at IS NULL
                  AND e.seo_skip_reason IS NULL
                  AND EXISTS (SELECT 1 FROM alerts a WHERE a.event_slug = e.event_slug)
                ORDER BY e.last_refreshed_at DESC NULLS LAST
                LIMIT %s
            """, (EVENT_SEO_LIMIT,))
            candidates = cur.fetchall()

        for row in candidates:
            slug = row["event_slug"]

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT market_title FROM alerts
                    WHERE event_slug = %s AND market_title IS NOT NULL
                    LIMIT 10
                """, (slug,))
                market_titles = [r["market_title"] for r in cur.fetchall()]

                cur.execute("""
                    SELECT llm_headline FROM alerts
                    WHERE event_slug = %s AND llm_headline IS NOT NULL
                    ORDER BY composite_score DESC LIMIT 5
                """, (slug,))
                headlines = [r["llm_headline"] for r in cur.fetchall()]

                cur.execute("""
                    SELECT COUNT(*) AS alert_count,
                           COALESCE(SUM(total_usd), 0) AS total_usd
                    FROM alerts WHERE event_slug = %s
                """, (slug,))
                agg = cur.fetchone() or {}

            try:
                result = generate_event_seo_content(
                    event_title=row["title"],
                    description=row.get("description"),
                    tags=_parse_tags(row.get("tags")),
                    end_date=row.get("end_date"),
                    market_titles=market_titles,
                    total_usd=float(agg.get("total_usd") or 0),
                    alert_count=int(agg.get("alert_count") or 0),
                    alert_headlines=headlines,
                )
            except ContentFilterError:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE events SET seo_skip_reason = 'content_filter' WHERE event_slug = %s",
                        (slug,),
                    )
                print(
                    f"[seo_worker:event] content-filtered, skipping permanently: {row['title']}",
                    flush=True,
                )
                continue
            except Exception as e:
                print(f"[seo_worker:event] LLM error for {row['title']}: {e}", flush=True)
                continue

            if not result:
                continue

            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE events SET
                        seo_title = %s,
                        seo_description = %s,
                        seo_summary = %s,
                        seo_faqs = %s,
                        seo_generated_at = NOW()
                    WHERE event_slug = %s
                """, (
                    result["seo_title"],
                    result["seo_description"],
                    result["seo_summary"],
                    json.dumps(result["seo_faqs"]),
                    slug,
                ))
            generated += 1
            print(f"[seo_worker:event] {row['title']}", flush=True)
    return generated


def main() -> int:
    print("[seo_worker] start", flush=True)
    market_count = hydrate_count = event_seo_count = 0
    try:
        market_count = run_market_seo()
    except Exception as e:
        print(f"[seo_worker] market pass FAILED: {e}", flush=True)
    try:
        hydrate_count = run_event_hydration()
    except Exception as e:
        print(f"[seo_worker] hydrate pass FAILED: {e}", flush=True)
    try:
        event_seo_count = run_event_seo()
    except Exception as e:
        print(f"[seo_worker] event SEO pass FAILED: {e}", flush=True)
    print(
        f"[seo_worker] done: markets={market_count} "
        f"hydrated={hydrate_count} events={event_seo_count}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
