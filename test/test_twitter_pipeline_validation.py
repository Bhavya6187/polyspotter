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
            "https://polyspotter.com/alert/1")
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
            "the lead wallet is 174-32. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_allows_dollar_lede_with_record_later():
    text = ("$27k just landed on No before kickoff. The lead account is "
            "714-126 across tracked bets. https://polyspotter.com/alert/1")
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_writer_succeeds_on_first_attempt():
    good = json.dumps({"tweet": "Sharp wallet 29-4. https://polyspotter.com/alert/1"})
    client = FakeClient([good])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    assert client.completions.calls == 1


def test_writer_retries_once_on_missing_link():
    bad = json.dumps({"tweet": "No link in this tweet at all"})
    good = json.dumps({"tweet": "Same point. https://polyspotter.com/alert/1"})
    client = FakeClient([bad, good])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 2


def test_writer_gives_up_after_two_failures():
    bad1 = json.dumps({"tweet": "no link 1"})
    bad2 = json.dumps({"tweet": "no link 2"})
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
    good = json.dumps({"tweet": "Recovered. https://polyspotter.com/alert/1"})
    client = FakeClient([bad_json, good])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
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
