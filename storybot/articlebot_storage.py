"""Article storage: Postgres insert + .md file write + skipped-run audit rows.

Lives in its own module so the file-IO + DB-write path can be tested in
isolation from the rest of articlebot.
"""
from __future__ import annotations

import os
import re
from typing import Any

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log


ARTICLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles")

_WORD_RE = re.compile(r"\w+")


def _get_conn():
    """Return a Postgres connection. Hookable in tests via monkeypatch."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _format_md_file(run_id: str, decision: dict, cover_path: str | None) -> str:
    """Build the paste-ready markdown file body."""
    article = decision.get("article") or {}
    headline = article.get("headline", "")
    subhead = article.get("subhead", "")
    body = article.get("body_markdown", "")
    event_slug = decision.get("event_slug") or ""
    alert_ids = decision.get("alert_ids") or []

    parts = [f"# {headline}", "", f"*{subhead}*", ""]
    if cover_path:
        parts.extend([f"![cover]({os.path.basename(cover_path)})", ""])
    parts.extend([body, "", "---",
                  f"run_id: {run_id} | event_slug: {event_slug} | "
                  f"alert_ids: {alert_ids}",
                  "posted_url: <fill in after publishing>",
                  ""])
    return "\n".join(parts)


def persist_article(*, run_id: str, decision: dict,
                    cover_bytes: bytes | None,
                    cover_path: str | None) -> dict:
    """INSERT the article row into Postgres and write the .md file to disk.

    Returns {"md_path", "word_count"}.
    Raises on DB failure (caller decides whether to keep the .md file).
    """
    os.makedirs(ARTICLES_DIR, exist_ok=True)

    article = decision.get("article") or {}
    body = article.get("body_markdown", "")
    word_count = _word_count(body)

    md_text = _format_md_file(run_id, decision, cover_path)
    md_path = os.path.join(ARTICLES_DIR, f"{run_id}.md")
    with open(md_path, "w") as f:
        f.write(md_text)

    rel_md = os.path.relpath(md_path, os.path.dirname(ARTICLES_DIR))
    rel_cover = (os.path.relpath(cover_path, os.path.dirname(ARTICLES_DIR))
                 if cover_path else None)

    sql = """
        INSERT INTO articles
            (run_id, event_slug, alert_ids, headline, subhead,
             body_markdown, cover_alt_text, cover_path, md_path,
             word_count, status, cover_bytes, tweet_text)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
    """
    params = (
        run_id,
        decision.get("event_slug") or "",
        list(decision.get("alert_ids") or []),
        article.get("headline", ""),
        article.get("subhead", ""),
        body,
        article.get("cover_alt_text"),
        rel_cover,
        rel_md,
        word_count,
        psycopg2.Binary(cover_bytes) if cover_bytes else None,
        decision.get("tweet_text") or "",
    )

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

    log("articlebot_persisted", run_id=run_id, md_path=md_path,
        word_count=word_count,
        cover=bool(cover_bytes),
        tweet_text_chars=len(decision.get("tweet_text") or ""))

    return {"md_path": md_path, "word_count": word_count}


def record_skipped_run(*, run_id: str, event_slug: str = "",
                       reason: str = "") -> None:
    """Insert a status='skipped' row for audit trail. event_slug may be empty
    when the picker skipped before choosing one."""
    sql = """
        INSERT INTO articles
            (run_id, event_slug, alert_ids, headline, subhead,
             body_markdown, md_path, word_count, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'skipped')
    """
    params = (
        run_id,
        event_slug or "",
        [],
        "",
        reason[:160] if reason else "",   # subhead doubles as skip reason
        "",
        "",
        0,
    )
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
    log("articlebot_skipped", run_id=run_id, reason=reason)
