"""Tests for the May 2026 articlebot pipeline improvements.

Each block here covers one fix from the post-mortem of articlebot runs
5bdebe62 / bd9c1efb / 85844f4e / 3b474742 / 4611d23a / b31c87c6 / 39c5c12c /
79edb27a / 0ed1fd63 / 55af0137. The fixes themselves live in:
  - storybot/articlebot.py  (validators, picker enrichment, kickoff helpers)
  - storybot/compressor.py  (backend coercion, router short-circuit, empty warning)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _body(opening: str, *, h2_word_counts=(160, 160, 160),
          link_url: str = "https://polyspotter.com/market/foo") -> str:
    """Build a body with `opening` as the lede, three H2 sections of the
    given word counts, and a closing line containing `link_url`. The
    resulting word count is roughly sum(h2_word_counts) + len(opening.split()) + 5.
    """
    parts = [opening, ""]
    for i, n in enumerate(h2_word_counts):
        parts.append(f"## Section {i+1}")
        parts.append("")
        parts.append(" ".join(["lorem"] * n))
        parts.append("")
    parts.append(f"Closing line. Watch [the market]({link_url}).")
    return "\n".join(parts)


def _decision(**overrides) -> dict:
    base = {
        "decision": "post",
        "reason": "sharp",
        "article": {
            "headline": "Whale stacks $80k on the underdog tonight",
            "subhead": "Different framing about the bet's stakes",
            "body_markdown": _body("A whale just stacked $80k on a coin-flip tonight."),
            "cover_alt_text": "alt text",
        },
        "tweet_text": "A whale just stacked $80k on a coin-flip tonight — receipts are wild.",
        "alert_ids": [1],
        "cover_chart_spec": None,
    }
    base.update(overrides)
    return base


# --- Fix #1: numeric grounding (win-loss tuples) ---------------------------

def test_numeric_grounding_passes_when_no_context():
    """When chosen_alerts and transcript are both None (e.g. the existing
    test fixtures), grounding is skipped — backward compatible."""
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err


def test_numeric_grounding_rejects_ungrounded_win_loss_tuple():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    chosen_alerts = [{"id": 1, "total_usd": 5000.0, "wallet": "0xabc"}]
    transcript: list = []
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=chosen_alerts, transcript=transcript,
    )
    assert not ok
    assert "178-20" in err and "cannot be found" in err


def test_numeric_grounding_passes_when_tuple_halves_in_alerts():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    chosen_alerts = [{
        "id": 1, "wallet": "0xabc",
        "wallet_stats": {"wins": 178, "losses": 20, "closed_positions": 198},
    }]
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=chosen_alerts, transcript=[],
    )
    assert ok, err


def test_numeric_grounding_passes_when_tuple_in_transcript():
    """Numbers reachable through a tool result also count as grounded."""
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body("A 401-6 wallet bet $80k tonight.")
    transcript = [{
        "type": "function_call_output",
        "call_id": "x",
        "output": '{"data": [{"wallet": "0xabc", "wins": 401, "losses": 6}]}',
    }]
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=[{"id": 1}], transcript=transcript,
    )
    assert ok, err


def test_numeric_grounding_skips_small_tuples():
    """5-2 or 9-3 patterns are usually scores or odds, not records.
    Skip checking when total < 10 to avoid noise."""
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "A wallet went 5-2 on $80k bets last weekend tonight."
    )
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=[{"id": 1}], transcript=[],
    )
    assert ok, err


# --- Fix #3: hook lint (opening must lead with a number) -------------------

def test_opening_without_number_fails():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "Opening hook line that pulls the reader in but is purely prose."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok
    assert "concrete number" in err.lower()


def test_opening_with_dollar_amount_passes():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body("$80k just landed on the underdog.")
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err


def test_opening_with_percentage_passes():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "An account hitting 92% on this season just took the other side."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err


def test_opening_with_cents_price_passes():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "The market sat at 47¢ when a sharp wallet showed up."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err


# --- Fix #3: scene-setting templates rejected ------------------------------

def test_opening_one_of_polymarkets_template_fails():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "One of Polymarket's stranger little tells $80k just turned up."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok
    assert "scene-setting" in err.lower() or "banned" in err.lower()


def test_opening_is_not_exactly_template_fails():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "A LoL match is not exactly the Super Bowl, yet $80k landed on it."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok


def test_opening_isnt_on_radar_template_fails():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "$80k on a market that isn't on most people's radar this morning."
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok


# --- Fix #10: headline/subhead similarity ----------------------------------

def test_subhead_too_similar_to_headline_fails():
    import articlebot
    d = _decision(article={
        "headline": "A 178-20 wallet just stacked $80k on the underdog tonight",
        "subhead": "An 178-20 wallet stacked 80k on the underdog tonight again",
        "body_markdown": _body("A 178-20 wallet bet $80k tonight."),
        "cover_alt_text": "alt",
    })
    ok, err = articlebot.validate_article_decision(d)
    assert not ok
    assert "similar to headline" in err.lower() or "jaccard" in err.lower()


def test_subhead_distinct_from_headline_passes():
    import articlebot
    d = _decision(article={
        "headline": "A 178-20 wallet stacked $80k on the underdog",
        "subhead": "Cleveland sat at coin-flip prices when the order came in",
        "body_markdown": _body("$80k landed on Cleveland at 50¢ tonight."),
        "cover_alt_text": "alt",
    })
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err


# --- Fix #10: tighter BODY_WORD_MAX ---------------------------------------

def test_body_above_700_words_fails():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "$80k landed tonight.", h2_word_counts=(250, 250, 250),
    )
    ok, err = articlebot.validate_article_decision(d)
    assert not ok
    assert "word count" in err.lower()


def test_body_at_700_words_passes():
    import articlebot
    d = _decision()
    d["article"]["body_markdown"] = _body(
        "$80k landed tonight.", h2_word_counts=(225, 225, 225),
    )
    ok, err = articlebot.validate_article_decision(d)
    assert ok, err
    assert articlebot._word_count(d["article"]["body_markdown"]) <= 700


# --- Fix #4: tweet specificity --------------------------------------------

def test_short_tweet_with_no_number_fails_when_body_has_one():
    import articlebot
    d = _decision(tweet_text="A wallet just made an interesting call tonight.")
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=[{"id": 1, "wins": 178, "losses": 20}], transcript=[],
    )
    assert not ok
    assert "tweet" in err.lower() and "concrete" in err.lower()


def test_short_tweet_with_number_passes():
    import articlebot
    d = _decision(tweet_text="A 178-20 wallet just stacked $80k on the underdog.")
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=[{"id": 1, "wins": 178, "losses": 20}], transcript=[],
    )
    assert ok, err


def test_long_tweet_without_number_passes():
    """Validator only fires when tweet is short. A 220+ char tweet that
    chose to omit numbers is not the failure mode being targeted."""
    import articlebot
    long_tweet = (
        "A wallet just made an interesting call tonight on a market that "
        "almost nobody is paying attention to. The story is in who showed up "
        "and what it tells us about the next 24 hours of pricing action across "
        "the whole event slate."
    )
    d = _decision(tweet_text=long_tweet)
    d["article"]["body_markdown"] = _body("A 178-20 wallet bet $80k tonight.")
    ok, err = articlebot.validate_article_decision(
        d, chosen_alerts=[{"id": 1, "wins": 178, "losses": 20}], transcript=[],
    )
    assert ok, err


# --- Fix #5: market-maker flag computed by picker --------------------------

def test_fetch_picker_wallet_stats_marks_likely_mm(monkeypatch):
    import articlebot
    rows = [
        # Classic market maker: 99% WR, microscopic ROI on huge volume
        {"wallet": "0xmm", "win_rate": 0.99, "closed_positions": 1066,
         "total_pnl": 23000.0, "total_invested": 14500000.0},
        # Real directional sharp: 86% WR, 23% ROI
        {"wallet": "0xsharp", "win_rate": 0.86, "closed_positions": 1991,
         "total_pnl": 1200000.0, "total_invested": 5400000.0},
    ]
    monkeypatch.setattr(articlebot, "query_postgres", lambda sql: rows)
    monkeypatch.setattr(articlebot.storybot, "_hex_in_clause",
                        lambda ws: "('" + "','".join(ws) + "')")
    out = articlebot.fetch_picker_wallet_stats(["0xmm", "0xsharp"])
    assert out["0xmm"]["likely_mm"] is True
    assert out["0xmm"]["roi_pct"] is not None and out["0xmm"]["roi_pct"] < 1
    assert out["0xsharp"]["likely_mm"] is False
    assert out["0xsharp"]["roi_pct"] > 15


def test_fetch_picker_wallet_stats_marks_low_volume_wallets_not_mm(monkeypatch):
    """A 99% wallet with only 10 closed positions isn't an MM yet."""
    import articlebot
    rows = [{
        "wallet": "0xfresh", "win_rate": 0.99, "closed_positions": 10,
        "total_pnl": 1000.0, "total_invested": 50000.0,
    }]
    monkeypatch.setattr(articlebot, "query_postgres", lambda sql: rows)
    monkeypatch.setattr(articlebot.storybot, "_hex_in_clause",
                        lambda ws: "('" + "','".join(ws) + "')")
    out = articlebot.fetch_picker_wallet_stats(["0xfresh"])
    assert out["0xfresh"]["likely_mm"] is False


# --- Fix #8: suggested cover_chart_type from signals + wallet stats --------

def test_suggested_chart_type_picks_cluster_card_for_linked_funder():
    import articlebot
    alerts = [{
        "id": 1, "cluster_headline": "3 wallets, same direction (No/BUY), "
                                     "$10,000 — 2 share funder (linked)",
        "signals": [],
    }]
    assert articlebot._suggested_chart_type(alerts) == "cluster_card"


def test_suggested_chart_type_picks_volume_bar_for_big_spike():
    import articlebot
    alerts = [{
        "id": 1, "cluster_headline": "2 wallets",
        "signals": [{"strategy": "pre_event_volume_spike",
                     "headline": "1816.4× spike vs historical avg"}],
    }]
    assert articlebot._suggested_chart_type(alerts) == "volume_bar"


def test_suggested_chart_type_picks_wallet_record_card_for_real_sharp():
    import articlebot
    alerts = [{
        "id": 1, "cluster_headline": "",
        "signals": [],
        "wallet_stats": {"roi_pct": 47.0, "closed_positions": 1991,
                         "likely_mm": False},
    }]
    assert articlebot._suggested_chart_type(alerts) == "wallet_record_card"


def test_suggested_chart_type_skips_mm_wallets_for_record_card():
    """A 99% / 0.16% ROI wallet shouldn't anchor a wallet_record_card —
    the card flatters market makers as 'sharps'."""
    import articlebot
    alerts = [{
        "id": 1, "cluster_headline": "",
        "signals": [],
        "wallet_stats": {"roi_pct": 0.16, "closed_positions": 1066,
                         "likely_mm": True},
    }]
    # Falls through to price_sparkline (the safe default)
    assert articlebot._suggested_chart_type(alerts) == "price_sparkline"


# --- Fix #9: cluster gap detection ----------------------------------------

def test_detect_cluster_gaps_flags_unbacked_funder_claim():
    import articlebot
    chosen_alerts = [{
        "id": 141744,
        "cluster_headline": "8 wallets share funder 0xbc71bbaaaaaaaaaa",
    }]
    prefetched = {
        "wallet_funders": {
            "ok": True,
            # Only 1 of the picked-event wallets has the funder in this scope
            "data": [{"wallet": "0xabc", "funder": "0xbc71bbaaaaaaaaaa"}],
        },
    }
    warnings = articlebot._detect_cluster_gaps(chosen_alerts, prefetched)
    assert len(warnings) == 1
    assert "claims 8 wallets" in warnings[0]
    assert "DIFFERENT markets" in warnings[0]


def test_detect_cluster_gaps_passes_when_funder_is_actually_shared():
    import articlebot
    chosen_alerts = [{
        "id": 1,
        "cluster_headline": "3 wallets share funder 0xfeed",
    }]
    prefetched = {
        "wallet_funders": {
            "ok": True,
            "data": [
                {"wallet": "0xa", "funder": "0xfeed"},
                {"wallet": "0xb", "funder": "0xfeed"},
                {"wallet": "0xc", "funder": "0xfeed"},
            ],
        },
    }
    warnings = articlebot._detect_cluster_gaps(chosen_alerts, prefetched)
    assert warnings == []


def test_detect_cluster_gaps_handles_missing_prefetch():
    import articlebot
    warnings = articlebot._detect_cluster_gaps(
        [{"id": 1, "cluster_headline": "8 wallets share funder 0xfeed"}],
        {},  # no wallet_funders block
    )
    assert len(warnings) == 1


# --- Fix #2: compressor backend coercion ----------------------------------

def test_coerce_backend_pins_clob_for_prices_history():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "fetch CLOB prices-history for token X over the last hour", None,
    ) == "clob"


def test_coerce_backend_pins_clob_for_book():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "current order book for token Y", None,
    ) == "clob"


def test_coerce_backend_pins_clob_for_explicit_clob_book_intent():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "CLOB /book for token Z", None,
    ) == "clob"


def test_coerce_backend_pins_data_api_for_trades():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "data api /trades for wallet 0xabc", None,
    ) == "data_api"


def test_coerce_backend_returns_none_when_ambiguous():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "wallet_profiles row for 0xabc", None,
    ) is None


def test_coerce_backend_uses_hint_field():
    import compressor
    assert compressor._coerce_backend_from_intent(
        "the price history", "CLOB",
    ) == "clob"


# --- Fix #2: empty-result warning ----------------------------------------

def test_is_empty_result_recognizes_empty_list():
    import compressor
    assert compressor._is_empty_result([]) is True


def test_is_empty_result_recognizes_empty_dict():
    import compressor
    assert compressor._is_empty_result({}) is True


def test_is_empty_result_recognizes_history_only_empty():
    """/prices-history mis-routed to gamma comes back as just {"history": []}
    without a summary block — that's the silent-fail case."""
    import compressor
    assert compressor._is_empty_result({"history": []}) is True


def test_is_empty_result_returns_false_for_summary_with_empty_history():
    """Summary present means SOME meaningful answer — not empty."""
    import compressor
    assert compressor._is_empty_result(
        {"summary": {"first_p": 0.5, "last_p": 0.5}, "history": []}
    ) is False


def test_is_empty_result_returns_false_for_populated_list():
    import compressor
    assert compressor._is_empty_result([{"x": 1}]) is False


# --- Fix #7: router short-circuit for tiny inputs --------------------------

def test_router_short_circuit_thresholds():
    """Just confirm the constants exist and are usable. Behavioral tests live
    inside the compressor.run_query path which depends on a live LLM client."""
    import compressor
    assert compressor.ROUTER_SKIP_ROWS >= 30
    assert compressor.ROUTER_SKIP_BYTES >= 20480
