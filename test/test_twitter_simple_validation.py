"""Validation tests for twitter_simple.py decision schema."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_simple  # noqa: E402


def _base_post_decision() -> dict:
    return {
        "decision": "post",
        "tweet": "Sample tweet https://polyspotter.com/alert/1",
        "alert_ids": [1],
        "chart_type": "wallet_record_card",
    }


def test_validate_accepts_known_chart_type():
    ok, err = twitter_simple.validate_decision(_base_post_decision())
    assert ok, err


def test_validate_treats_missing_chart_type_as_none():
    d = _base_post_decision()
    del d["chart_type"]
    ok, err = twitter_simple.validate_decision(d)
    assert ok, err  # missing -> defaults to "none"


def test_validate_accepts_chart_type_none():
    d = _base_post_decision()
    d["chart_type"] = "none"
    ok, err = twitter_simple.validate_decision(d)
    assert ok, err


def test_validate_rejects_unknown_chart_type():
    d = _base_post_decision()
    d["chart_type"] = "lol_no_chart"
    ok, err = twitter_simple.validate_decision(d)
    assert not ok
    assert "chart_type" in err
