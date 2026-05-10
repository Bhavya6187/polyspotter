"""Tests for stage 1 (event picker) of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


class FakeResponses:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        return SimpleNamespace(
            output_text=self._content,
            output=[],
            usage=SimpleNamespace(
                input_tokens=0, output_tokens=0, total_tokens=0,
                input_tokens_details=None, output_tokens_details=None,
            ),
        )


class FakeClient:
    def __init__(self, content: str):
        self.responses = FakeResponses(content)


def _seed():
    return [
        {"id": 10, "event_slug": "e1", "wallet": "0xa"},
        {"id": 11, "event_slug": "e1", "wallet": "0xb"},
        {"id": 12, "event_slug": "e2", "wallet": "0xc"},
    ]


def test_pick_event_returns_skip_when_model_says_skip():
    client = FakeClient(json.dumps({
        "decision": "skip", "reason": "all alerts small",
        "alert_ids": None, "event_summary": None,
    }))
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "skip"


def test_pick_event_parses_post_decision():
    client = FakeClient(json.dumps({
        "decision": "post", "reason": "two alerts on same event",
        "alert_ids": [10, 11],
        "event_summary": "Two accounts piled into the same outcome.",
    }))
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "post"
    assert out["alert_ids"] == [10, 11]


def test_pick_event_swallows_bad_json_into_skip():
    client = FakeClient("this is not json")
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "skip"
    assert "invalid JSON" in out["reason"]


def test_validate_accepts_valid_skip():
    ok, err = twitter_pipeline.validate_event_pick(
        {"decision": "skip", "reason": "x"}, _seed())
    assert ok, err


def test_validate_accepts_valid_post():
    pick = {"decision": "post", "alert_ids": [10, 11],
            "event_summary": "blah"}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert ok, err


def test_validate_rejects_unknown_alert_id():
    pick = {"decision": "post", "alert_ids": [10, 99],
            "event_summary": "blah"}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert not ok
    assert "99" in err


def test_validate_rejects_missing_event_summary():
    pick = {"decision": "post", "alert_ids": [10], "event_summary": ""}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert not ok
    assert "event_summary" in err
