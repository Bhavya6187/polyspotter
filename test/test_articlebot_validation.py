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
        "tweet_text": "A 178-20 wallet just stacked $80k on the underdog tonight.",
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


def test_article_system_prompt_contains_style_rules_and_article_specifics():
    import articlebot

    p = articlebot.SYSTEM_PROMPT

    # Inherits voice rules
    assert "Hard style rules" in p
    assert "Analyst-speak" in p or "analyst-speak" in p.lower()
    # Article-specific framing
    assert "SEO-indexed page on polyspotter.com" in p
    assert "general audience" in p.lower()
    # Length and structure rules surfaced to the model
    assert "500-700" in p or "600 words" in p or "450" in p
    assert "## H2" in p or "H2" in p
    # Output schema
    assert '"decision"' in p and '"article"' in p
    assert '"body_markdown"' in p
    assert '"cover_chart_spec"' in p
    # Mandatory polyspotter link
    assert "polyspotter.com" in p


def test_render_cover_chart_writes_png_and_returns_path(tmp_path, monkeypatch):
    import articlebot

    spec = {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}}
    chosen_alerts = [{"id": 42, "wallet": "0xabc", "market_title": "M",
                      "condition_id": "0xc1"}]

    captured = {}

    def _fake_render(chart_type, alert, params=None):
        captured["chart_type"] = chart_type
        captured["params"] = params
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _fake_render)

    png_bytes, cover_path = articlebot.render_cover_chart(
        spec, chosen_alerts, str(tmp_path / "cover.png")
    )
    # Spec params were forwarded (empty dict passes through unchanged)
    assert captured["params"] == {}
    assert cover_path == str(tmp_path / "cover.png")
    assert png_bytes == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "cover.png").exists()
    assert (tmp_path / "cover.png").read_bytes().startswith(b"\x89PNG")


def test_render_cover_chart_returns_none_when_spec_is_null():
    import articlebot
    assert articlebot.render_cover_chart(None, [], "/tmp/x.png") == (None, None)


def test_render_cover_chart_returns_none_when_renderer_returns_none(tmp_path, monkeypatch):
    import articlebot
    monkeypatch.setattr(articlebot, "_dispatch_chart_render",
                        lambda chart_type, alert, params=None: None)

    out = articlebot.render_cover_chart(
        {"chart_type": "price_sparkline", "alert_id": 1, "params": {}},
        [{"id": 1, "wallet": "0xa", "market_title": "M", "condition_id": "0xc"}],
        str(tmp_path / "cover.png"),
    )
    assert out == (None, None)
    assert not (tmp_path / "cover.png").exists()


def test_render_cover_chart_soft_faults_on_render_error(tmp_path, monkeypatch):
    import articlebot

    def _boom(chart_type, alert, params=None):
        raise RuntimeError("render busted")
    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _boom)

    out = articlebot.render_cover_chart(
        {"chart_type": "price_sparkline", "alert_id": 1, "params": {}},
        [{"id": 1, "wallet": "0xa", "market_title": "M", "condition_id": "0xc"}],
        str(tmp_path / "cover.png"),
    )
    assert out == (None, None)
    assert not (tmp_path / "cover.png").exists()


def test_render_cover_chart_returns_none_when_alert_id_not_found(tmp_path, monkeypatch):
    import articlebot
    # Even if the dispatcher is OK, missing alert means we don't render.
    monkeypatch.setattr(articlebot, "_dispatch_chart_render",
                         lambda c, a, params=None: b"\x89PNG\r\n\x1a\n")
    out = articlebot.render_cover_chart(
        {"chart_type": "wallet_record_card", "alert_id": 999, "params": {}},
        [{"id": 1}],
        str(tmp_path / "cover.png"),
    )
    assert out == (None, None)


def test_tweet_text_missing_fails():
    import articlebot
    d = _valid_decision()
    d.pop("tweet_text")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet_text" in err.lower()


def test_tweet_text_empty_fails():
    import articlebot
    d = _valid_decision(tweet_text="   ")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet_text" in err.lower()


def test_tweet_text_too_long_fails():
    import articlebot
    # 256 visible chars + "\n\n" + URL(23) > 280
    d = _valid_decision(tweet_text="x" * 256)
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "tweet" in err.lower()


def test_tweet_text_banned_phrase_fails():
    import articlebot
    d = _valid_decision(tweet_text="Read the full breakdown of this play.")
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "banned" in err.lower()


def test_tweet_text_inline_polyspotter_url_fails():
    import articlebot
    d = _valid_decision(
        tweet_text="A wallet just stacked $80k. https://polyspotter.com/alert/123"
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok and "polyspotter" in err.lower()
