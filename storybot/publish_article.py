"""Publish a draft articlebot row: post the teaser tweet to Twitter (without
the article URL), flip the DB row to 'published', then print the article URL
so the human can add it manually as a reply.

Usage:
    python storybot/publish_article.py <run_id>
    DRY_RUN=true python storybot/publish_article.py <run_id>

Twitter charges ~20¢ per tweet that contains a URL, so we keep the article
URL out of the tweet body and reply with it manually after the fact. The
cover image is uploaded as media on the original tweet.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import psycopg2

from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log
from tweet_utils import (
    TWEET_MAX_CHARS,
    _BANNED_TWEET_PHRASES,
    _build_twitter_api_v1,
    _build_twitter_client,
    _tweet_length,
    post_tweet,
)


DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

POLYSPOTTER_BASE = "https://polyspotter.com"


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def _validate_tweet(text: str) -> tuple[bool, str]:
    """Defensive re-validation in case a human edited the row directly.
    The article URL is intentionally NOT in the tweet body (added later as
    a reply, to dodge X's per-URL fee), so we don't check for it here."""
    if _tweet_length(text) > TWEET_MAX_CHARS:
        return False, (
            f"tweet exceeds {TWEET_MAX_CHARS} chars "
            f"(twitter-counted={_tweet_length(text)})"
        )
    lower = text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned phrase {phrase!r}"
    return True, ""


def _tweet_url(tweet_id: str) -> str:
    """Username-free permalink — x.com redirects this to the canonical URL."""
    return f"https://x.com/i/web/status/{tweet_id}"


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

        ok, err = _validate_tweet(tweet_text)
        if not ok:
            print(f"error: {err}", file=sys.stderr)
            return 1

        published_date = date.today()
        article_url = f"{POLYSPOTTER_BASE}/article/{published_date.isoformat()}/{event_slug}"
        cover_bytes = bytes(cover_bytes_raw) if cover_bytes_raw else None

        print(f"\n--- Tweet ({_tweet_length(tweet_text)} twitter chars) ---")
        print(tweet_text)
        print("--- end tweet ---")
        if cover_bytes:
            print(f"Cover image: {len(cover_bytes)} bytes — will be attached to the tweet")
        else:
            print("Cover image: (none)")

        if DRY_RUN:
            print(f"\nArticle URL (for manual reply): {article_url}")
            print("\n[DRY_RUN] not posting, not updating DB.")
            log("publish_article_dryrun", run_id=run_id)
            return 0

        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if cover_bytes is not None else None
        try:
            tweet_id = post_tweet(
                tweet_text,
                twitter_client=twitter_client,
                twitter_api_v1=twitter_api_v1,
                media_png=cover_bytes,
                dry_run=False,
            )
        except Exception as exc:
            log("publish_article_post_error",
                run_id=run_id, error=f"{type(exc).__name__}: {exc}")
            print(
                f"error: failed to post tweet: {type(exc).__name__}: {exc}. "
                "DB not updated.",
                file=sys.stderr,
            )
            return 1

        posted_url = _tweet_url(tweet_id)
        log("publish_article_posted",
            run_id=run_id, tweet_id=tweet_id, posted_url=posted_url)

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
                (published_date, tweet_id, posted_url, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                print(
                    f"error: UPDATE rowcount={cur.rowcount}, expected 1. "
                    "Concurrent publish? Tweet was posted but DB was NOT updated — "
                    f"posted_url={posted_url}",
                    file=sys.stderr,
                )
                return 1
        conn.commit()
    finally:
        conn.close()

    log("publish_article_done", run_id=run_id, tweet_id=tweet_id,
        published_date=published_date.isoformat())

    print(f"\n[publish_article] published run_id={run_id}")
    print(f"    tweet:   {posted_url}")
    print(f"    article: {article_url}")
    print(f"\nReply to {posted_url} with this URL to dodge the URL fee:")
    print(f"    {article_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
