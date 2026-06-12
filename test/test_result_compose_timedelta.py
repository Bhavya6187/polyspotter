"""compose_result_tweet must thread flagged_hours_before to the LLM (Delta 1)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_pipeline as rp  # noqa: E402


class _FakeResponses:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.kwargs = kwargs
        return SimpleNamespace(output_text='{"tweet": "ok tweet. Cashed +$1k."}')


class FakeLLM:
    def __init__(self):
        self.kwargs = None
        self.responses = _FakeResponses(self)


RESULT = {"n_won": 2, "n_lost": 0, "total_invested_usd": 100.0,
          "total_payout_usd": 150.0, "net_pl_usd": 50.0, "by_market": {}}


def test_payload_includes_flagged_hours_before():
    llm = FakeLLM()
    out = rp.compose_result_tweet(llm, "orig tweet", RESULT,
                                  flagged_hours_before=14)
    assert out == "ok tweet. Cashed +$1k."
    payload = json.loads(llm.kwargs["input"].split("\n\nReply with")[0])
    assert payload["flagged_hours_before"] == 14


def test_payload_flagged_hours_none_by_default():
    llm = FakeLLM()
    rp.compose_result_tweet(llm, "orig tweet", RESULT)
    payload = json.loads(llm.kwargs["input"].split("\n\nReply with")[0])
    assert payload["flagged_hours_before"] is None


def test_prompt_mentions_quote_tweet_and_time_delta():
    p = rp.SYSTEM_PROMPT_RESULT
    assert "quote-tweet" in p
    assert "flagged_hours_before" in p
