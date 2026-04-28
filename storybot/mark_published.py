"""Mark an articlebot draft as published.

Usage:
    python storybot/mark_published.py <run_id> <x_article_url>

Updates the articles row: status='published', posted_url=<url>, posted_at=NOW().
"""
from __future__ import annotations

import sys

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: mark_published.py <run_id> <x_article_url>", file=sys.stderr)
        return 2

    run_id, url = argv
    if not (url.startswith("https://x.com/") or url.startswith("https://twitter.com/")):
        print(f"error: url must be https://x.com/... or https://twitter.com/..., got {url!r}",
              file=sys.stderr)
        return 1

    sql = """
        UPDATE articles
        SET status = 'published',
            posted_url = %s,
            posted_at = NOW()
        WHERE run_id = %s
          AND status = 'draft'
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (url, run_id))
            rc = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    if rc == 0:
        print(f"error: no article found for run_id={run_id!r} (or already published)",
              file=sys.stderr)
        return 1
    print(f"marked {run_id} published → {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
