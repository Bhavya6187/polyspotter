"""Publish a draft articlebot row to polyspotter.com + post the teaser tweet.

Usage:
    python storybot/publish_article.py <run_id>
    DRY_RUN=true python storybot/publish_article.py <run_id>

Replaces mark_published.py — articles now live on our own site, and the
linked tweet is auto-posted at publish time.
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
_ARTICLE_URL_PREFIX = POLYSPOTTER_BASE + "/article/"


def _get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


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

        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if cover_bytes else None

        # Print + confirm in DRY_RUN
        print(f"\n--- Tweet ({_tweet_length(tweet)} twitter chars) ---")
        print(tweet)
        print(f"\nArticle URL: {article_url}")
        print(f"Cover: {len(cover_bytes) if cover_bytes else 0} bytes")

        if DRY_RUN:
            try:
                answer = input("\nPost this for real? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer not in ("y", "yes"):
                log("publish_article_dryrun_aborted", run_id=run_id)
                return 0

        try:
            tweet_id = post_tweet(
                tweet,
                twitter_client=twitter_client,
                twitter_api_v1=twitter_api_v1,
                media_png=cover_bytes,
                dry_run=False,
            )
        except Exception as exc:
            log("publish_article_post_error", run_id=run_id,
                error=f"{type(exc).__name__}: {exc}")
            return 1

        x_tweet_url = f"https://x.com/i/web/status/{tweet_id}"

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
    print(f"    tweet:   {x_tweet_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
