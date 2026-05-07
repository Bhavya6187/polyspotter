"""Sync edits from storybot/articles/<run_id>.md back into the Postgres
articles row before publish_article.py runs.

The .md file is the single human-editable surface (article body + tweet
text). publish_article.py reads tweet_text from the DB and the on-site
article reads body_markdown from the DB, so without a sync step Claude's
edits to the .md never reach production. This module parses the .md,
re-validates against the same rules articlebot uses (length, banned
phrases, polyspotter link, etc.), and UPDATEs the row's headline /
subhead / body_markdown / tweet_text / word_count.

Usage:
    python storybot/sync_article_from_md.py <run_id>
"""
from __future__ import annotations

import os
import re
import sys

import psycopg2

from articlebot import validate_article_decision
from articlebot_storage import ARTICLES_DIR, _word_count
from bot_utils import DATABASE_URL, QUERY_TIMEOUT_SECONDS, log


_HEADLINE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_SUBHEAD_RE = re.compile(r"^\*([^*].*?[^*])\*$", re.MULTILINE)
_RULE_RE = re.compile(r"^---$", re.MULTILINE)
_COVER_RE = re.compile(r"^!\[cover\]\([^)]+\)\s*$", re.MULTILINE)
_TWEET_HEADER_RE = re.compile(r"^## Tweet$", re.MULTILINE)


def _parse_md(md_text: str) -> dict:
    """Parse a <run_id>.md file produced by articlebot_storage._format_md_file.

    Returns {"headline", "subhead", "body_markdown", "tweet_text"}.
    Raises ValueError with a specific message on any structural violation.

    The format is under our control (see articlebot_storage._format_md_file).
    The two `---` rules and the `## Tweet` heading are load-bearing.
    """
    m_h = _HEADLINE_RE.search(md_text)
    if not m_h:
        raise ValueError("could not find headline (line starting with '# ')")
    headline = m_h.group(1).strip()

    m_s = _SUBHEAD_RE.search(md_text, m_h.end())
    if not m_s:
        raise ValueError("could not find subhead (line wrapped in *...*) after headline")
    subhead = m_s.group(1).strip()

    rules = list(_RULE_RE.finditer(md_text, m_s.end()))
    if len(rules) != 2:
        raise ValueError(
            f"expected exactly 2 horizontal rules ('---') after subhead, "
            f"found {len(rules)} — Claude may have introduced extra rules in body"
        )

    # Body: between subhead and first rule, with cover image line stripped.
    body_raw = md_text[m_s.end():rules[0].start()]
    body = _COVER_RE.sub("", body_raw).strip()
    if not body:
        raise ValueError("body section is empty between subhead and first '---'")

    # Tweet: between '## Tweet' header and second rule.
    tweet_section = md_text[rules[0].end():rules[1].start()]
    m_t = _TWEET_HEADER_RE.search(tweet_section)
    if not m_t:
        raise ValueError("could not find '## Tweet' heading in tweet section")
    tweet = tweet_section[m_t.end():].strip()
    if not tweet:
        raise ValueError("tweet text is empty after '## Tweet' heading")

    return {
        "headline": headline,
        "subhead": subhead,
        "body_markdown": body,
        "tweet_text": tweet,
    }


def _validate_synced(parsed: dict, *, alert_ids: list,
                     cover_alt_text: str | None) -> tuple[bool, str]:
    """Run the parsed .md through articlebot's existing validator by building
    a synthetic decision dict. cover_alt_text and alert_ids come from the DB
    row (they are not editable via the .md)."""
    decision = {
        "decision": "post",
        "article": {
            "headline": parsed["headline"],
            "subhead": parsed["subhead"],
            "body_markdown": parsed["body_markdown"],
            "cover_alt_text": cover_alt_text or "",
        },
        "tweet_text": parsed["tweet_text"],
        "alert_ids": list(alert_ids),
    }
    return validate_article_decision(decision)


def _get_conn():
    """Return a Postgres connection. Hookable in tests via monkeypatch."""
    return psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)


def sync_run(run_id: str) -> None:
    """Parse storybot/articles/<run_id>.md, validate, UPDATE the matching
    articles row. Calls sys.exit(1) on any failure (missing row, wrong
    status, missing file, parse error, validation error).

    Only fields editable via the .md are written: headline, subhead,
    body_markdown, tweet_text, word_count. cover_alt_text, alert_ids,
    event_slug, cover_bytes are left as-is.
    """
    md_path = os.path.join(ARTICLES_DIR, f"{run_id}.md")
    if not os.path.exists(md_path):
        log("sync_article_missing_md", run_id=run_id, md_path=md_path)
        print(f"error: no .md file at {md_path}", file=sys.stderr)
        sys.exit(1)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, status, cover_alt_text, alert_ids "
                "FROM articles WHERE run_id = %s LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            log("sync_article_no_row", run_id=run_id)
            print(f"error: no articles row for run_id={run_id!r}", file=sys.stderr)
            sys.exit(1)
        _, status, cover_alt_text, alert_ids = row
        if status != "draft":
            log("sync_article_wrong_status", run_id=run_id, status=status)
            print(
                f"error: row status={status!r}, expected 'draft'. "
                "Refusing to overwrite a published or skipped row.",
                file=sys.stderr,
            )
            sys.exit(1)

        with open(md_path) as f:
            md_text = f.read()

        try:
            parsed = _parse_md(md_text)
        except ValueError as exc:
            log("sync_article_parse_error", run_id=run_id, error=str(exc))
            print(f"error: failed to parse {md_path}: {exc}", file=sys.stderr)
            sys.exit(1)

        ok, err = _validate_synced(parsed, alert_ids=list(alert_ids or []),
                                   cover_alt_text=cover_alt_text)
        if not ok:
            log("sync_article_validation_error", run_id=run_id, error=err)
            print(f"error: edited article failed validation: {err}",
                  file=sys.stderr)
            sys.exit(1)

        word_count = _word_count(parsed["body_markdown"])

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE articles
                SET headline = %s,
                    subhead = %s,
                    body_markdown = %s,
                    tweet_text = %s,
                    word_count = %s
                WHERE run_id = %s AND status = 'draft'
                """,
                (parsed["headline"], parsed["subhead"],
                 parsed["body_markdown"], parsed["tweet_text"],
                 word_count, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                log("sync_article_update_zero_rows",
                    run_id=run_id, rowcount=cur.rowcount)
                print(
                    f"error: UPDATE affected {cur.rowcount} rows "
                    f"(row may have been published or deleted between "
                    f"the status check and the UPDATE)",
                    file=sys.stderr,
                )
                sys.exit(1)
        conn.commit()

        log("sync_article_done", run_id=run_id, word_count=word_count,
            headline_chars=len(parsed["headline"]),
            tweet_chars=len(parsed["tweet_text"]))
        print(f"[sync] run_id={run_id} headline={parsed['headline']!r} "
              f"words={word_count} tweet_chars={len(parsed['tweet_text'])}")
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: sync_article_from_md.py <run_id>", file=sys.stderr)
        return 2
    sync_run(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
