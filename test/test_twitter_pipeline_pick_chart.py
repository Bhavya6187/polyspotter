"""Tests for stage 3 (chart picker) of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


class FakeResponses:
    def __init__(self, content):
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
    def __init__(self, content):
        self.responses = FakeResponses(content)


def test_pick_chart_parses_valid_response():
    client = FakeClient(json.dumps({
        "chart_type": "wallet_record_card",
        "hook_anchor": "29-4 sharp record",
    }))
    out = twitter_pipeline.pick_chart(client, [], "x", {})
    assert out["chart_type"] == "wallet_record_card"
    assert out["hook_anchor"] == "29-4 sharp record"


def test_pick_chart_handles_bad_json():
    client = FakeClient("garbage")
    out = twitter_pipeline.pick_chart(client, [], "x", {})
    assert out["chart_type"] == "none"
    assert "_parse_error" in out


def test_validate_accepts_valid_pick():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": "12× volume"})
    assert ok, err


def test_validate_accepts_none_chart():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "none", "hook_anchor": "unique cross-market thesis"})
    assert ok, err


def test_validate_rejects_unknown_chart_type():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "lol_no", "hook_anchor": "x"})
    assert not ok
    assert "chart_type" in err


def test_validate_rejects_missing_anchor():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": ""})
    assert not ok
    assert "hook_anchor" in err


def test_validate_rejects_oversized_anchor():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": "x" * 81})
    assert not ok
    assert "hook_anchor" in err
