"""Publish a draft articlebot row to polyspotter.com.

Usage:
    python storybot/publish_article.py <run_id>
    DRY_RUN=true python storybot/publish_article.py <run_id>

Prints the teaser tweet (and writes the cover image to /tmp) so you can
post it manually on Twitter — Twitter's API costs ~20¢ per tweet, so
we'd rather copy/paste. The article still goes live on polyspotter.com
and the DB row is flipped to 'published'. After posting, paste the
tweet URL back at the prompt and we'll fill in tweet_id/posted_url.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log
from tweet_utils import (
    TWEET_MAX_CHARS,
    _BANNED_TWEET_PHRASES,
    _tweet_length,
)


DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

POLYSPOTTER_BASE = "https://polyspotter.com"
_ARTICLE_URL_PREFIX = POLYSPOTTER_BASE + "/article/"

_TWEET_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:x|twitter)\.com/\S*?/status/(\d+)(?:[/?#].*)?$"
)


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def _parse_tweet_url(raw: str) -> tuple[str, str] | None:
    """Return (tweet_id, normalized_url) for a pasted tweet URL, or None."""
    m = _TWEET_URL_RE.match(raw.strip())
    if not m:
        return None
    tweet_id = m.group(1)
    return tweet_id, f"https://x.com/i/web/status/{tweet_id}"


def _validate_tweet(text: str) -> tuple[bool, str]:
    """Defensive re-validation in case a human edited the row directly."""
    if _tweet_length(text) > TWEET_MAX_CHARS:
        return False, (
            f"final tweet exceeds {TWEET_MAX_CHARS} chars "
            f"(twitter-counted={_tweet_length(text)})"
        )
    lower = text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned phrase {phrase!r}"
    if _ARTICLE_URL_PREFIX not in text:
        return False, "tweet is missing the polyspotter article URL"
    return True, ""


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: publish_article.py <run_id>", file=sys.stderr)
        return 2
    run_id = argv[0]

    log("publish_article_start", run_id=run_id, dry_run=DRY_RUN)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, event_slug, status, cover_bytes, tweet_text
                FROM articles
                WHERE run_id = %s
                LIMIT 1
                """,
                (run_id,),
            )
            row = cur.fetchone()

        if row is None:
            print(f"error: no article found for run_id={run_id!r}", file=sys.stderr)
            return 1

        _, event_slug, status, cover_bytes_raw, tweet_text = row

        if status != "draft":
            print(
                f"error: article {run_id!r} is status={status!r}, expected 'draft'. "
                "Refusing to re-publish.",
                file=sys.stderr,
            )
            return 1

        if not tweet_text or not tweet_text.strip():
            print(
                f"error: article {run_id!r} has no tweet_text. "
                "This is a pre-migration draft — re-run articlebot.py to regenerate.",
                file=sys.stderr,
            )
            return 1

        published_date = date.today()
        article_url = f"{POLYSPOTTER_BASE}/article/{published_date.isoformat()}/{event_slug}"
        tweet = f"{tweet_text}\n\n{article_url}"

        ok, err = _validate_tweet(tweet)
        if not ok:
            print(f"error: {err}", file=sys.stderr)
            return 1

        cover_bytes = bytes(cover_bytes_raw) if cover_bytes_raw else None
        cover_path = None
        if cover_bytes:
            cover_path = Path("/tmp") / f"{run_id}_cover.png"
            cover_path.write_bytes(cover_bytes)

        print(f"\n--- Tweet ({_tweet_length(tweet)} twitter chars) ---")
        print(tweet)
        print("--- end tweet ---")
        print(f"\nArticle URL: {article_url}")
        if cover_path:
            print(f"Cover image: {cover_path} ({len(cover_bytes)} bytes) — attach this to the tweet")
        else:
            print("Cover image: (none)")

        if DRY_RUN:
            print("\n[DRY_RUN] not updating DB.")
            log("publish_article_dryrun", run_id=run_id)
            return 0

        print(
            "\nCopy the tweet above and post it on Twitter."
            "\nThen paste the tweet URL below to record it (or press enter to skip)."
            "\nLeave blank and answer 'n' to abort."
        )
        try:
            pasted = input("Tweet URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            pasted = ""

        tweet_id: str | None = None
        x_tweet_url: str | None = None
        if pasted:
            parsed = _parse_tweet_url(pasted)
            if parsed is None:
                print(
                    f"error: {pasted!r} doesn't look like a tweet URL "
                    "(expected https://x.com/<user>/status/<id>). DB not updated.",
                    file=sys.stderr,
                )
                return 1
            tweet_id, x_tweet_url = parsed

        try:
            answer = input(
                "Mark article as published? [y/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            print("aborted — DB not updated.")
            log("publish_article_aborted", run_id=run_id)
            return 0

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE articles
                SET status='published',
                    published_date=%s,
                    tweet_id=%s,
                    posted_url=%s,
                    posted_at=NOW()
                WHERE run_id=%s AND status='draft'
                """,
                (published_date, tweet_id, x_tweet_url, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                print(
                    f"error: UPDATE rowcount={cur.rowcount}, expected 1. "
                    "Concurrent publish? Refusing without committing.",
                    file=sys.stderr,
                )
                return 1
        conn.commit()
    finally:
        conn.close()

    log("publish_article_done", run_id=run_id, tweet_id=tweet_id,
        published_date=published_date.isoformat())

    print(f"\n[publish_article] published run_id={run_id}")
    print(f"    article: {article_url}")
    if x_tweet_url:
        print(f"    tweet:   {x_tweet_url}")
    else:
        print("    tweet:   (no URL recorded)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
