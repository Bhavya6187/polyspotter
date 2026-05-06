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
