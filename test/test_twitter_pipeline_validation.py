"""Tests for stage 4 validation + retry path of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import tweet_utils  # noqa: E402
import twitter_pipeline  # noqa: E402


class _FakeCompletions:
    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        content = self._contents.pop(0) if self._contents else "{}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class FakeClient:
    def __init__(self, contents):
        self.completions = _FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.completions)


def test_validate_accepts_short_tweet_with_link():
    text = ("$30k just hit Yes on Fed cuts in May; the lead wallet is 29-4. "
            "Decision day is May 8. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_rejects_oversized_tweet():
    text = "A " * 200 + "https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "exceeds" in err


def test_validate_rejects_missing_link():
    text = "Look at this banger of a tweet without any link"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "deep link" in err


def test_validate_rejects_banned_phrase():
    text = "Full breakdown. https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "banned" in err.lower() or "phrase" in err.lower()


def test_validate_rejects_empty_tweet():
    ok, err = twitter_pipeline.validate_tweet("")
    assert not ok


def test_validate_rejects_record_opener_with_article():
    text = ("A 174-32 Polymarket account just put $2k on Yes. "
            "https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "record" in err.lower()


def test_validate_rejects_record_opener_no_article():
    text = ("197-15 wallet just bought Over 2.5. "
            "https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "record" in err.lower()


def test_validate_rejects_record_opener_em_dash():
    text = ("An 805–125 trader just hit No on Iran leadership. "
            "https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "record" in err.lower()


def test_validate_allows_record_in_middle():
    text = ("With 11 minutes to tip, $82k hit No on the 76ers — "
            "the lead wallet is 174-32. Three share one funder. "
            "https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_allows_dollar_lede_with_record_later():
    text = ("$27k just landed on No before kickoff. The lead account is "
            "714-126 across tracked bets. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_rejects_two_polymarket_mentions():
    text = ("Polymarket bettors just bought $28k on the Cubs on Polymarket. "
            "The lead wallet is 110-3. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "polymarket" in err.lower()


def test_validate_rejects_three_polymarket_mentions():
    text = ("Polymarket money on Polymarket from Polymarket bettors. "
            "Volume is 12x normal. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


def test_validate_allows_one_polymarket_mention():
    text = ("$28k just hit Cubs on Polymarket; the lead wallet is 110-3. "
            "First pitch in 90. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_allows_zero_polymarket_mentions():
    text = ("$28k just hit Cubs on the line; the lead wallet is 110-3. "
            "First pitch in 90. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_polymarket_count_excludes_url():
    text = ("Just one mention of Polymarket here. Volume 12x normal. "
            "https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_polymarket_count_case_insensitive():
    text = ("polymarket bettors just hit $28k on Cubs on POLYMARKET. "
            "The lead wallet is 110-3. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


# --- closer-required + banned-closer-shape -----------------------------------

def test_validate_rejects_one_sentence_body_with_url():
    """A body that's a single sentence followed by the URL has no closer
    clause — the writer prompt's closer rule is non-optional."""
    text = "$9.8k just hit Cubs to beat the Reds. https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "closer" in err.lower()


def test_validate_accepts_two_sentence_body_with_url():
    text = ("$9.8k just hit Cubs to beat the Reds. "
            "First pitch in 90 minutes. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_rejects_banned_closer_not_random():
    text = ("Three accounts dropped $20k on Avalanche-Wild. "
            "Not random. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "closer" in err.lower()


def test_validate_rejects_banned_closer_somethings_cooking():
    text = ("Avalanche $20k cluster shows up before puck drop. "
            "Something's cooking. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


def test_validate_rejects_banned_closer_worth_a_look():
    text = ("Five wallets bought Under 211.5 in Raptors-Cavs. "
            "Worth a look. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


def test_validate_rejects_banned_closer_stay_tuned():
    text = ("$28k landed on Kiwoom DRX before tipoff. "
            "Stay tuned. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


def test_validate_rejects_banned_closer_eyes_on_this():
    text = ("Cluster of three accounts went hard on Cubs. "
            "Eyes on this. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok


def test_validate_accepts_concrete_clock_closer():
    text = ("$24k just hit Cleveland to beat Toronto. "
            "Tip is in 12 minutes. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_accepts_dollar_escalation_closer():
    text = ("Three accounts piled $13k on Under 211.5. "
            "Their related exposure is $81k. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_accepts_question_closer_for_reply_bait():
    """Question closers are reply-bait and explicitly allowed — they're a
    different shape from the chest-thump closers we ban."""
    text = ("$24k of sharp money on Cavaliers to beat Toronto. "
            "Cleveland or fade? https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_banned_closer_only_triggers_on_last_sentence():
    """'Worth a look' embedded earlier in the tweet shouldn't reject as long
    as the actual closer is concrete."""
    text = ("Worth a look at how often this wallet shows up: 110-3. "
            "First pitch in 90 minutes. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


# --- chart anchor (image-text linkage) ---------------------------------------

def test_chart_anchor_wallet_record_card_requires_record_digits():
    text = ("Cubs money just dwarfed this market: $9.8k on Chicago to beat "
            "Cincinnati. First pitch in 90. https://polyspotter.com/alert/1")
    bundle = {"has_sharp_wallet": {"record": "110-3"}}
    chart = {"chart_type": "wallet_record_card", "hook_anchor": "110-3 sharp record"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert not ok
    assert "110-3" in err


def test_chart_anchor_wallet_record_card_accepts_record_in_text():
    text = ("Cubs money just dwarfed this market: $9.8k from a 110-3 wallet "
            "on Chicago. First pitch in 90. https://polyspotter.com/alert/1")
    bundle = {"has_sharp_wallet": {"record": "110-3"}}
    chart = {"chart_type": "wallet_record_card", "hook_anchor": "110-3 sharp record"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_fresh_wallet_card_accepts_age_phrase():
    text = ("A 31-day-old account just dropped $20k on Cleveland. "
            "Tip is in 12. https://polyspotter.com/alert/1")
    bundle = {"has_fresh_wallet": {"wallet_age_days": 31}}
    chart = {"chart_type": "fresh_wallet_card", "hook_anchor": "31-day-old account"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_fresh_wallet_card_accepts_brand_new_descriptor():
    text = ("A brand-new account dropped $20k on Cleveland. "
            "Tip is in 12. https://polyspotter.com/alert/1")
    bundle = {"has_fresh_wallet": {"wallet_age_days": 0}}
    chart = {"chart_type": "fresh_wallet_card", "hook_anchor": "0-day-old wallet"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_fresh_wallet_card_rejects_no_age_no_descriptor():
    text = ("$20k of money just hit Cleveland to beat Toronto. "
            "Tip is in 12. https://polyspotter.com/alert/1")
    bundle = {"has_fresh_wallet": {"wallet_age_days": 31}}
    chart = {"chart_type": "fresh_wallet_card", "hook_anchor": "31-day-old account"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert not ok
    assert "fresh" in err.lower() or "age" in err.lower() or "day" in err.lower()


def test_chart_anchor_price_sparkline_accepts_cents_callout():
    text = ("Peace-deal odds slid from 79c to 62c in an hour. "
            "$19k of No just landed. https://polyspotter.com/alert/1")
    bundle = {"biggest_price_move": {"from": 0.79, "to": 0.62}}
    chart = {"chart_type": "price_sparkline", "hook_anchor": "79c → 62c slide"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_price_sparkline_rejects_no_price_callout():
    text = ("$19k of No on the US-Iran peace-deal market. "
            "Decision day is May 31. https://polyspotter.com/alert/1")
    bundle = {"biggest_price_move": {"from": 0.79, "to": 0.62}}
    chart = {"chart_type": "price_sparkline", "hook_anchor": "79c → 62c slide"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert not ok
    assert "price" in err.lower()


def test_chart_anchor_volume_bar_accepts_multiplier_callout():
    text = ("$13k just landed on Under 211.5 — running 12x usual flow. "
            "Tip is in 73. https://polyspotter.com/alert/1")
    bundle = {"volume_multiplier_x": 12.4}
    chart = {"chart_type": "volume_bar", "hook_anchor": "12× volume spike"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_volume_bar_rejects_no_multiplier():
    text = ("$13k just landed on Under 211.5 in Raptors-Cavs. "
            "Tip is in 73. https://polyspotter.com/alert/1")
    bundle = {"volume_multiplier_x": 12.4}
    chart = {"chart_type": "volume_bar", "hook_anchor": "12× volume spike"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert not ok
    assert "volume" in err.lower() or "multiplier" in err.lower()


def test_chart_anchor_cluster_card_accepts_word_form_count():
    text = ("Three accounts sharing one funder bought $20k of Avalanche. "
            "Puck drops in 4 hours. https://polyspotter.com/alert/1")
    bundle = {"cluster_size": 3}
    chart = {"chart_type": "cluster_card", "hook_anchor": "three accounts, one funder"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_cluster_card_accepts_digit_form_count():
    text = ("8 wallets piled $50k on Yes for Eurovision. "
            "Final is months out. https://polyspotter.com/alert/1")
    bundle = {"cluster_size": 8}
    chart = {"chart_type": "cluster_card", "hook_anchor": "eight accounts, one funder"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


def test_chart_anchor_cluster_card_rejects_no_count():
    text = ("Big cluster bought $50k of Yes for Eurovision. "
            "Final is months out. https://polyspotter.com/alert/1")
    bundle = {"cluster_size": 8}
    chart = {"chart_type": "cluster_card", "hook_anchor": "eight accounts, one funder"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert not ok
    assert "cluster" in err.lower() or "wallet" in err.lower() or "count" in err.lower()


def test_chart_anchor_none_passes_without_check():
    text = "Nothing here. Just saying. https://polyspotter.com/alert/1"
    bundle = {}
    chart = {"chart_type": "none", "hook_anchor": "x"}
    ok, err = twitter_pipeline.validate_tweet_anchor(text, chart, bundle)
    assert ok, err


# --- lede shape eligibility (candidate generation) ---------------------------

def test_eligible_lede_shapes_short_clock_includes_timing():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"minutes_to_resolution": 12, "total_usd": 5000})
    assert "timing" in shapes
    assert "stakes" not in shapes


def test_eligible_lede_shapes_long_clock_includes_stakes_not_timing():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"minutes_to_resolution": 30000, "total_usd": 5000})
    assert "stakes" in shapes
    assert "timing" not in shapes


def test_eligible_lede_shapes_no_clock_includes_stakes():
    shapes = twitter_pipeline._eligible_lede_shapes({"total_usd": 5000})
    assert "stakes" in shapes


def test_eligible_lede_shapes_price_impact():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"biggest_price_move": {"from": 0.79, "to": 0.62}})
    assert "impact" in shapes


def test_eligible_lede_shapes_small_price_move_excluded():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"biggest_price_move": {"from": 0.65, "to": 0.66}})
    assert "impact" not in shapes


def test_eligible_lede_shapes_size_threshold():
    assert "size" in twitter_pipeline._eligible_lede_shapes(
        {"total_usd": 50000})
    assert "size" not in twitter_pipeline._eligible_lede_shapes(
        {"total_usd": 500})


def test_eligible_lede_shapes_includes_age_for_fresh_wallet():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"has_fresh_wallet": {"wallet_age_days": 31}})
    assert "age" in shapes


def test_eligible_lede_shapes_includes_cluster():
    shapes = twitter_pipeline._eligible_lede_shapes({"cluster_size": 5})
    assert "cluster" in shapes


def test_eligible_lede_shapes_includes_behavior_for_sharp():
    shapes = twitter_pipeline._eligible_lede_shapes(
        {"has_sharp_wallet": {"record": "110-3"}})
    assert "behavior" in shapes


def test_eligible_lede_shapes_priority_order():
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
        "has_fresh_wallet": {"wallet_age_days": 5},
        "cluster_size": 5,
        "has_sharp_wallet": {"record": "110-3"},
    }
    shapes = twitter_pipeline._eligible_lede_shapes(bundle)
    assert shapes == ["timing", "impact", "size", "age", "cluster", "behavior"]


def test_pick_candidate_shapes_caps_at_three():
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
        "has_fresh_wallet": {"wallet_age_days": 5},
        "cluster_size": 5,
    }
    shapes = twitter_pipeline._pick_candidate_shapes(bundle, n=3)
    assert shapes == ["timing", "impact", "size"]


def test_pick_candidate_shapes_falls_back_to_stakes_when_empty():
    """A bundle with nothing flag-worthy should still produce one shape so
    the writer always has something to lean into."""
    shapes = twitter_pipeline._pick_candidate_shapes({}, n=3)
    assert len(shapes) >= 1


# --- writer user message threads lede_shape_hint ------------------------------

def test_writer_user_message_threads_lede_shape_hint():
    payload_str = twitter_pipeline._writer_user_message(
        chosen_alerts=[], event_summary="x", bundle={},
        chart_pick={"chart_type": "none", "hook_anchor": "y"},
        lede_shape_hint="timing",
    )
    payload = json.loads(payload_str)
    assert payload["lede_shape_hint"] == "timing"


def test_writer_user_message_omits_lede_shape_hint_when_none():
    payload_str = twitter_pipeline._writer_user_message(
        chosen_alerts=[], event_summary="x", bundle={},
        chart_pick={"chart_type": "none", "hook_anchor": "y"},
    )
    payload = json.loads(payload_str)
    assert payload.get("lede_shape_hint") is None


# --- candidate generation + rerank -------------------------------------------

_GOOD_TWEET = ("$24k just hit Cleveland to beat Toronto. "
               "Tips off in 12 minutes. https://polyspotter.com/alert/1")


def _good_writer_response(text=_GOOD_TWEET):
    return json.dumps({"tweet": text})


def test_writer_generates_three_candidates_when_three_shapes_eligible():
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
    }
    # 3 writer calls + 1 LLM validator on winner
    client = FakeClient([_good_writer_response(), _good_writer_response(),
                         _good_writer_response(), _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", bundle,
        {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    assert client.completions.calls == 4


def test_writer_filters_invalid_candidates_before_rerank():
    """Of 3 candidates, 2 fail deterministic checks. Only valid one advances."""
    bad = json.dumps({"tweet": "no link in this candidate."})
    good = _good_writer_response()
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
    }
    client = FakeClient([bad, good, bad, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", bundle,
        {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    assert decision["tweet"] == _GOOD_TWEET


def test_writer_retries_when_all_candidates_fail_deterministic():
    """All 3 round-1 candidates fail deterministic checks; round 2 retries
    with the highest-priority shape and the prior error fed back."""
    bad = json.dumps({"tweet": "no link"})
    good = _good_writer_response()
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
    }
    client = FakeClient([bad, bad, bad, good, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", bundle,
        {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 5


def test_writer_retries_when_llm_validator_rejects_winner():
    """Multi-candidate round 1: 3 valid candidates, winner rejected by LLM
    validator. Round 2: single retry with error fed back."""
    good = _good_writer_response()
    validator_reject = json.dumps({"ok": False, "error": "rule X: y"})
    good2 = _good_writer_response(
        "$30k of Cavs money landed pre-tip. Tips off in 11 minutes. "
        "https://polyspotter.com/alert/1")
    bundle = {
        "minutes_to_resolution": 12,
        "biggest_price_move": {"from": 0.5, "to": 0.7},
        "total_usd": 50000,
    }
    # Round 1: 3 writers + 1 validator-reject. Round 2: 1 writer + 1 validator-ok.
    client = FakeClient([good, good, good, validator_reject,
                         good2, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", bundle,
        {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 6


def test_score_candidate_prefers_concrete_clock_closer():
    bundle = {"minutes_to_resolution": 12}
    chart = {"chart_type": "none"}
    weak = ("$24k just hit Cleveland. The lead wallet is 110-3. "
            "https://polyspotter.com/alert/1")
    strong = ("$24k just hit Cleveland; the lead wallet is 110-3. "
              "Tips off in 12 minutes. https://polyspotter.com/alert/1")
    assert (twitter_pipeline._score_candidate(strong, bundle, chart)
            > twitter_pipeline._score_candidate(weak, bundle, chart))


def test_score_candidate_rewards_question_closer_for_reply_bait():
    bundle = {}
    chart = {"chart_type": "none"}
    no_q = ("$24k just hit Cleveland. The lead wallet is 110-3. "
            "Tip is in 12. https://polyspotter.com/alert/1")
    with_q = ("$24k just hit Cleveland — the lead wallet is 110-3. "
              "Cleveland or fade? https://polyspotter.com/alert/1")
    assert (twitter_pipeline._score_candidate(with_q, bundle, chart)
            > twitter_pipeline._score_candidate(no_q, bundle, chart))


_VALIDATOR_OK = json.dumps({"ok": True, "error": None})


def test_writer_succeeds_on_first_attempt():
    good = json.dumps({"tweet": "Sharp wallet 29-4 just hit Yes. Tips off in 12. https://polyspotter.com/alert/1"})
    client = FakeClient([good, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    # 1 writer + 1 validator call
    assert client.completions.calls == 2


def test_writer_retries_once_on_missing_link():
    bad = json.dumps({"tweet": "No link in this tweet at all"})
    good = json.dumps({"tweet": "Same point made twice. Tips off soon. https://polyspotter.com/alert/1"})
    # bad fails deterministic check (no link) so validator is skipped on
    # attempt 1; validator only runs on the successful retry.
    client = FakeClient([bad, good, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 3


def test_writer_gives_up_after_two_failures():
    bad1 = json.dumps({"tweet": "no link 1"})
    bad2 = json.dumps({"tweet": "no link 2"})
    # Both fail deterministic checks → validator never runs.
    client = FakeClient([bad1, bad2])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is not None
    assert "deep link" in err
    assert attempts == 2
    assert client.completions.calls == 2


def test_writer_retries_once_on_parse_error_then_succeeds():
    """First attempt returns malformed JSON; retry returns valid tweet."""
    bad_json = "not even close to JSON"
    good = json.dumps({"tweet": "Recovered tweet. Tips off in 12. https://polyspotter.com/alert/1"})
    client = FakeClient([bad_json, good, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 3


def test_writer_retries_when_llm_validator_rejects():
    """Writer + deterministic checks pass, but LLM validator rejects on
    attempt 1; retry produces a tweet the validator accepts."""
    writer1 = json.dumps({"tweet": "First draft. Tips off in 12. https://polyspotter.com/alert/1"})
    validator_reject = json.dumps({"ok": False, "error": "rule 3: record mismatch"})
    writer2 = json.dumps({"tweet": "Second draft. Tips off in 12. https://polyspotter.com/alert/1"})
    client = FakeClient([writer1, validator_reject, writer2, _VALIDATOR_OK])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 4


def test_writer_gives_up_when_llm_validator_rejects_twice():
    writer = json.dumps({"tweet": "Draft tweet. Tips off in 12. https://polyspotter.com/alert/1"})
    validator_reject = json.dumps({"ok": False, "error": "rule 3: record mismatch"})
    client = FakeClient([writer, validator_reject, writer, validator_reject])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is not None
    assert "rule 3" in err
    assert attempts == 2
    assert client.completions.calls == 4


def test_llm_validator_fails_open_on_parse_error():
    """If the validator itself returns malformed JSON, treat the tweet as
    valid — better to ship a borderline draft than block on a flaky validator."""
    writer = json.dumps({"tweet": "Draft tweet. Tips off in 12. https://polyspotter.com/alert/1"})
    validator_garbage = "not json at all"
    client = FakeClient([writer, validator_garbage])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    assert client.completions.calls == 2


def test_writer_user_message_includes_recent_openers():
    """Recent openers must be threaded into the user payload so the writer
    sees what to avoid mimicking."""
    payload_str = twitter_pipeline._writer_user_message(
        chosen_alerts=[],
        event_summary="x",
        bundle={},
        chart_pick={"chart_type": "none", "hook_anchor": "y"},
        image_tiles=["CLOCK"],
        recent_openers=["With 11 minutes to tip, $82k hit No on the 76ers",
                        "$27k just landed on No before kickoff"],
    )
    payload = json.loads(payload_str)
    assert payload["recent_openers_to_avoid"] == [
        "With 11 minutes to tip, $82k hit No on the 76ers",
        "$27k just landed on No before kickoff",
    ]


def test_tweet_opener_strips_url_and_truncates_at_sentence():
    text = ("With 11 minutes to tip, five accounts bought $82k on the 76ers. "
            "Three share one funder. https://polyspotter.com/alert/1")
    assert (tweet_utils._tweet_opener(text)
            == "With 11 minutes to tip, five accounts bought $82k on the 76ers")


def test_tweet_opener_caps_long_first_sentence():
    text = ("This is an unusually long opener with many many words and "
            "no punctuation in the middle https://polyspotter.com/alert/1")
    out = tweet_utils._tweet_opener(text)
    assert out.endswith("…")
    # Stripped of trailing ellipsis, should be exactly 12 words.
    assert len(out.rstrip("…").strip().split()) == 12


def test_tweet_opener_handles_no_url():
    assert (tweet_utils._tweet_opener("$27k just landed on No before kickoff.")
            == "$27k just landed on No before kickoff")


def test_writer_user_message_handles_none_openers():
    """recent_openers=None must produce an empty list, not a missing key —
    the writer prompt always reads `recent_openers_to_avoid`."""
    payload_str = twitter_pipeline._writer_user_message(
        chosen_alerts=[],
        event_summary="x",
        bundle={},
        chart_pick={"chart_type": "none", "hook_anchor": "y"},
    )
    payload = json.loads(payload_str)
    assert payload["recent_openers_to_avoid"] == []
