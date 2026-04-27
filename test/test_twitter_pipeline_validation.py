"""Tests for stage 4 validation + retry path of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
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
    text = "A 29-4 wallet just bought Yes on Fed May. https://polyspotter.com/alert/1"
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
