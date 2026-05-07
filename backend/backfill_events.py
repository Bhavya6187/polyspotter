#!/usr/bin/env python3
"""
backfill_events.py — populate the events table from existing alerts.

Three phases (each can be skipped with a flag):

  1. Touch    INSERT distinct event_slug from alerts. Cheap SQL.
  2. Hydrate  Fetch Gamma metadata for rows with title IS NULL.
              Rate-limited to ~6 req/sec to match gamma_cache.
  3. SEO      Call Azure OpenAI to fill seo_* on hydrated rows that
              don't have them yet.

Idempotent: every phase has a NULL guard, so re-running picks up where a
prior run was killed. Safe to interrupt with Ctrl+C — partial progress
is committed per row.

Usage (from project root or backend/, .env auto-loaded from project root):

    python backend/backfill_events.py                  # all three phases
    python backend/backfill_events.py --touch-only     # SQL only, instant
    python backend/backfill_events.py --no-seo         # skip LLM phase
    python backend/backfill_events.py --limit 200      # cap hydrate+SEO
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Load .env from project root BEFORE importing backend modules — database.py
# reads DATABASE_URL at import time and raises if it's missing.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Make sibling backend modules importable when invoked from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import get_conn
from events import upsert_event
from event_seo_generator import generate_event_seo_content

# Match gamma_cache.MARKET_LOOKUP_DELAY — Polymarket has been comfortable
# with this rate from elsewhere in the project.
GAMMA_DELAY_SEC = 0.15


def phase_touch() -> int:
    """Insert placeholder rows for every distinct event_slug in alerts."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO events (event_slug)
                SELECT DISTINCT event_slug FROM alerts
                WHERE event_slug IS NOT NULL
                ON CONFLICT DO NOTHING
            """)
            inserted = cur.rowcount
        conn.commit()
        return inserted
    finally:
        conn.close()


def phase_hydrate(limit: int | None) -> tuple[int, int]:
    """Fetch Gamma metadata for events with NULL title.

    Returns (succeeded, failed). Rate-limited per GAMMA_DELAY_SEC.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = "SELECT event_slug FROM events WHERE title IS NULL ORDER BY event_slug"
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            slugs = [r["event_slug"] for r in cur.fetchall()]
    finally:
        conn.close()

    if not slugs:
        print("[hydrate] no events need hydration.")
        return (0, 0)

    print(f"[hydrate] {len(slugs)} event(s) need Gamma metadata...")
    succeeded = failed = 0
    for i, slug in enumerate(slugs, 1):
        row = upsert_event(slug)
        if row and row.get("title"):
            succeeded += 1
        else:
            failed += 1
        if i == 1 or i % 25 == 0 or i == len(slugs):
            print(f"  [{i}/{len(slugs)}] succeeded={succeeded} failed={failed}")
        time.sleep(GAMMA_DELAY_SEC)
    return (succeeded, failed)


def _load_seo_context(slug: str) -> tuple[list[str], list[str], int, float]:
    """Pull child markets, top alert headlines, and aggregates for one event."""
    conn = get_conn()
    try:
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
                SELECT COUNT(*) AS alert_count, COALESCE(SUM(total_usd), 0) AS total_usd
                FROM alerts WHERE event_slug = %s
            """, (slug,))
            agg = cur.fetchone() or {}
    finally:
        conn.close()

    return (
        market_titles,
        headlines,
        int(agg.get("alert_count") or 0),
        float(agg.get("total_usd") or 0),
    )


def _persist_seo(slug: str, result: dict) -> None:
    """UPDATE events with the LLM result. Own connection so we never hold
    one open across an LLM call."""
    conn = get_conn()
    try:
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
        conn.commit()
    finally:
        conn.close()


def phase_seo(limit: int | None) -> int:
    """Generate SEO content for hydrated events that don't have it yet."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT e.event_slug, e.title, e.description,
                       e.end_date::text AS end_date, e.tags
                FROM events e
                WHERE e.title IS NOT NULL
                  AND e.seo_generated_at IS NULL
                  AND EXISTS (SELECT 1 FROM alerts a WHERE a.event_slug = e.event_slug)
                ORDER BY e.event_slug
            """
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[seo] no events need SEO generation.")
        return 0

    print(f"[seo] {len(rows)} event(s) need SEO content...")
    generated = 0
    for i, row in enumerate(rows, 1):
        slug = row["event_slug"]
        market_titles, headlines, alert_count, total_usd = _load_seo_context(slug)

        tags_list: list[str] = []
        try:
            raw_tags = row.get("tags") or "[]"
            parsed = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
            tags_list = [
                t.get("label") for t in parsed
                if isinstance(t, dict) and t.get("label")
            ]
        except (json.JSONDecodeError, TypeError):
            pass

        result = generate_event_seo_content(
            event_title=row["title"],
            description=row.get("description"),
            tags=tags_list,
            end_date=row.get("end_date"),
            market_titles=market_titles,
            total_usd=total_usd,
            alert_count=alert_count,
            alert_headlines=headlines,
        )

        if result:
            _persist_seo(slug, result)
            generated += 1

        if i == 1 or i % 10 == 0 or i == len(rows):
            preview = (row["title"] or slug)[:60]
            print(f"  [{i}/{len(rows)}] generated={generated} — last: {preview}")

    return generated


def main():
    parser = argparse.ArgumentParser(
        description="Backfill the events table from existing alerts."
    )
    parser.add_argument(
        "--touch-only", action="store_true",
        help="Only insert placeholder rows; skip Gamma + LLM phases.",
    )
    parser.add_argument(
        "--no-hydrate", action="store_true",
        help="Skip Gamma metadata fetch.",
    )
    parser.add_argument(
        "--no-seo", action="store_true",
        help="Skip LLM SEO generation.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap number of events processed in hydrate / SEO phases.",
    )
    args = parser.parse_args()

    started = time.time()

    inserted = phase_touch()
    print(f"[touch] {inserted} placeholder row(s) inserted.")
    if args.touch_only:
        print(f"\nDone in {time.time() - started:.1f}s.")
        return

    if not args.no_hydrate:
        succeeded, failed = phase_hydrate(args.limit)
        print(f"[hydrate] succeeded={succeeded} failed={failed}.")

    if not args.no_seo:
        if not os.environ.get("AZURE_OPENAI_API_KEY"):
            print("[seo] AZURE_OPENAI_API_KEY not set — skipping SEO phase.")
        else:
            generated = phase_seo(args.limit)
            print(f"[seo] {generated} event SEO record(s) generated.")

    print(f"\nDone in {time.time() - started:.1f}s.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Interrupted — partial progress is committed per-row.")
        sys.exit(130)
