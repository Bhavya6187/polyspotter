"""Tests for sync_article_from_md: parser, validation, and DB UPDATE."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _build_md(*, headline="Headline", subhead="Subhead",
              body=None, tweet="Tweet body here", cover_basename="abc.png",
              run_id="abc12345", event_slug="some-event",
              alert_ids=(11, 12)) -> str:
    """Build a .md file matching the format _format_md_file emits."""
    if body is None:
        body = (
            "Opening hook.\n\n"
            "## The wallet\n\n"
            "Wallet paragraph.\n\n"
            "## The bet\n\n"
            "Bet paragraph.\n\n"
            "## What to watch\n\n"
            "Watch paragraph. https://polyspotter.com/market/x\n\n"
            "Closing line."
        )
    parts = [f"# {headline}", "", f"*{subhead}*", ""]
    if cover_basename:
        parts.extend([f"![cover]({cover_basename})", ""])
    parts.extend([body, "", "---", "", "## Tweet", "", tweet, "",
                  "---", "",
                  f"run_id: {run_id} | event_slug: {event_slug} | "
                  f"alert_ids: {list(alert_ids)}",
                  "posted_url: <fill in after publishing>", ""])
    return "\n".join(parts)


def test_parse_md_happy_path():
    import sync_article_from_md as sync

    md = _build_md()
    parsed = sync._parse_md(md)

    assert parsed["headline"] == "Headline"
    assert parsed["subhead"] == "Subhead"
    assert parsed["tweet_text"] == "Tweet body here"
    # Body should NOT contain the cover image line.
    assert "![cover]" not in parsed["body_markdown"]
    # Body SHOULD contain its own H2s and the polyspotter link.
    assert "## The wallet" in parsed["body_markdown"]
    assert "https://polyspotter.com/market/x" in parsed["body_markdown"]
    # Body should not contain the trailing --- or tweet section.
    assert "## Tweet" not in parsed["body_markdown"]
    assert "---" not in parsed["body_markdown"]


def test_parse_md_missing_headline_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("# Headline", "Headline")
    with pytest.raises(ValueError, match="could not find headline"):
        sync._parse_md(md)


def test_parse_md_missing_subhead_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("*Subhead*", "Subhead")
    with pytest.raises(ValueError, match="could not find subhead"):
        sync._parse_md(md)


def test_parse_md_missing_tweet_section_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md().replace("## Tweet", "## Not Tweet")
    with pytest.raises(ValueError, match="could not find '## Tweet'"):
        sync._parse_md(md)


def test_parse_md_extra_rule_errors():
    """If Claude introduces a stray --- in the body, we must reject — the
    parser would otherwise mis-locate the body/tweet boundary."""
    import sync_article_from_md as sync
    import pytest

    body_with_rule = (
        "Opening.\n\n"
        "## The wallet\n\n"
        "Wallet line.\n\n---\n\n"   # stray rule inside body
        "## The bet\n\n"
        "Bet line.\n\n"
        "## What to watch\n\n"
        "Watch line. https://polyspotter.com/market/x"
    )
    md = _build_md(body=body_with_rule)
    with pytest.raises(ValueError, match="expected exactly 2 horizontal rules"):
        sync._parse_md(md)


def test_parse_md_empty_tweet_errors():
    import sync_article_from_md as sync
    import pytest

    md = _build_md(tweet="")
    with pytest.raises(ValueError, match="tweet text is empty"):
        sync._parse_md(md)
