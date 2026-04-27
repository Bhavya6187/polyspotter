"""Tests for articlebot output validator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _valid_body(word_count: int = 600) -> str:
    """Build a body with exactly `word_count` words, 3 H2s, 1 polyspotter link."""
    body_words = ["lorem"] * (word_count - 30)
    return (
        "Opening paragraph here that hooks the reader.\n\n"
        "## The wallet\n\n" + " ".join(body_words[:200]) + "\n\n"
        "## The bet\n\n" + " ".join(body_words[200:400]) + "\n\n"
        "## What to watch\n\n" + " ".join(body_words[400:]) + "\n\n"
        "Closing line. Watch [the market](https://polyspotter.com/market/foo)."
    )


def _valid_decision(**overrides):
    base = {
        "decision": "post",
        "reason": "sharp",
        "article": {
            "headline": "Headline",
            "subhead": "Subhead",
            "body_markdown": _valid_body(600),
            "cover_alt_text": "alt",
        },
        "alert_ids": [1],
        "cover_chart_spec": None,
    }
    base.update(overrides)
    return base


def test_valid_post_passes():
    import articlebot
    ok, err = articlebot.validate_article_decision(_valid_decision())
    assert ok, err


def test_skip_passes():
    import articlebot
    ok, err = articlebot.validate_article_decision({"decision": "skip", "reason": "weak"})
    assert ok, err


def test_word_count_too_low_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = _valid_body(400)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "word count" in err.lower()


def test_word_count_too_high_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = _valid_body(900)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "word count" in err.lower()


def test_missing_polyspotter_link_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = d["article"]["body_markdown"].replace(
        "https://polyspotter.com/market/foo", "https://example.com/")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "polyspotter" in err.lower()


def test_too_few_h2s_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = (
        "Opening.\n\n## Only one\n\n" + " ".join(["word"] * 600) +
        "\n\nClose. https://polyspotter.com/market/foo"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "h2" in err.lower()


def test_too_many_h2s_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["body_markdown"] = (
        "Opening.\n\n"
        "## A\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## B\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## C\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## D\n\n" + " ".join(["w"] * 100) + "\n\n"
        "## E\n\n" + " ".join(["w"] * 100) + "\n\n"
        "Close. https://polyspotter.com/market/foo"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "h2" in err.lower()


def test_headline_too_long_fails():
    import articlebot
    d = _valid_decision()
    d["article"]["headline"] = "x" * 100
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "headline" in err.lower()


def test_banned_phrase_in_body_fails():
    import articlebot
    d = _valid_decision()
    # "link below" is in _BANNED_TWEET_PHRASES
    d["article"]["body_markdown"] = d["article"]["body_markdown"].replace(
        "Opening paragraph", "The link below shows")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "banned" in err.lower()


def test_missing_alert_ids_on_post_fails():
    import articlebot
    d = _valid_decision()
    d["alert_ids"] = []
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "alert_ids" in err.lower()
