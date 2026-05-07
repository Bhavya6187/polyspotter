"""
Polymarket event metadata: lazy fetch + cache.

Populates the `events` table from Gamma /events?slug= on first read. Used
by GET /api/event/{slug} to power SEO event hub pages — multi-market
events where one URL aggregates everything a user googling for the event
wants. Past-resolved events are kept indefinitely; active events refresh
in the background after REFRESH_AFTER_SECONDS so we pick up things like
title/description corrections, late-added child markets, and updated
tags.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import requests as _requests

from database import get_conn

GAMMA_API = "https://gamma-api.polymarket.com"
GAMMA_TIMEOUT = 10
# Refresh cached event metadata if older than this AND end_date is still
# in the future. Resolved events don't change; we keep them as-is to save
# API calls and so historical pages stay deterministic.
REFRESH_AFTER_SECONDS = 7 * 24 * 3600


def fetch_event_from_gamma(slug: str) -> dict | None:
    """Fetch raw event payload from Gamma. Returns None if not found."""
    try:
        resp = _requests.get(
            f"{GAMMA_API}/events", params={"slug": slug}, timeout=GAMMA_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
    except _requests.RequestException as e:
        print(
            f"[WARN] Gamma /events lookup failed for slug={slug}: {e}",
            file=sys.stderr,
        )
    return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _normalize_event(raw: dict) -> dict:
    """Pick the columns we store from a Gamma event payload."""
    tags_raw = raw.get("tags") or []
    tags = [
        {
            "id": str(t.get("id", "")),
            "label": t.get("label", ""),
            "slug": t.get("slug", ""),
        }
        for t in tags_raw
        if isinstance(t, dict) and t.get("label")
    ]
    return {
        "gamma_event_id": str(raw.get("id", "")) or None,
        "title": raw.get("title"),
        "description": raw.get("description"),
        "image": raw.get("image"),
        "icon": raw.get("icon"),
        "start_date": _parse_iso(raw.get("startDate")),
        "end_date": _parse_iso(raw.get("endDate")),
        "tags": json.dumps(tags),
    }


def upsert_event(slug: str) -> dict | None:
    """Fetch event from Gamma and write to the events table.

    Returns the row that's now in the DB (dict shape), or None if Gamma
    didn't recognize the slug.
    """
    raw = fetch_event_from_gamma(slug)
    if not raw:
        return None
    norm = _normalize_event(raw)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (
                    event_slug, gamma_event_id, title, description, image, icon,
                    start_date, end_date, tags, last_refreshed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (event_slug) DO UPDATE SET
                    gamma_event_id    = EXCLUDED.gamma_event_id,
                    title             = EXCLUDED.title,
                    description       = EXCLUDED.description,
                    image             = EXCLUDED.image,
                    icon              = EXCLUDED.icon,
                    start_date        = EXCLUDED.start_date,
                    end_date          = EXCLUDED.end_date,
                    tags              = EXCLUDED.tags,
                    last_refreshed_at = NOW()
                RETURNING *
                """,
                (
                    slug,
                    norm["gamma_event_id"],
                    norm["title"],
                    norm["description"],
                    norm["image"],
                    norm["icon"],
                    norm["start_date"],
                    norm["end_date"],
                    norm["tags"],
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def get_event_or_fetch(slug: str) -> dict | None:
    """Read events row for slug. If missing or stale-and-active, refresh from Gamma.

    Returns None if Gamma also doesn't recognize the slug. Callers can use
    None to decide whether to noindex / 404 / fall back to a humanized slug.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE event_slug = %s", (slug,))
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return upsert_event(slug)

    now = datetime.now(timezone.utc)
    last_refreshed = row.get("last_refreshed_at") or row.get("fetched_at")
    end_date = row.get("end_date")
    is_active = end_date is None or end_date > now
    is_stale = (
        last_refreshed is None
        or (now - last_refreshed).total_seconds() > REFRESH_AFTER_SECONDS
    )
    if is_active and is_stale:
        refreshed = upsert_event(slug)
        if refreshed:
            return refreshed

    return dict(row)
