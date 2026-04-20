"""
Tests for backend/twitter_bot_agent.py.

Run: cd backend && pytest test_twitter_bot_agent.py -v
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nope")
os.environ.setdefault("POLYSPOTTER_API_URL", "https://api.example.test")

import twitter_bot_agent as agent


# -------------------------------------------------------------- envelope ----

def test_build_envelope_wraps_data():
    env = agent.build_envelope({"a": 1, "b": 2})
    assert env == {"data": {"a": 1, "b": 2}, "truncated": False}


def test_build_envelope_error_shape():
    env = agent.build_envelope(None, error="projection failed: bad syntax")
    assert env == {"error": "projection failed: bad syntax"}


def test_apply_projection_returns_projected_value():
    raw = {"bet_history": [1, 2, 3, 4]}
    result = agent.apply_projection(raw, "length(bet_history)")
    assert result == 4


def test_apply_projection_returns_raw_when_projection_is_none():
    raw = {"a": 1}
    assert agent.apply_projection(raw, None) == raw


def test_apply_projection_raises_on_bad_expression():
    with pytest.raises(agent.ProjectionError):
        agent.apply_projection({"a": 1}, "invalid(")


def test_truncate_payload_leaves_small_payloads_alone():
    small = {"x": 1}
    result, truncated = agent.truncate_payload(small, cap_bytes=8192)
    assert result == small
    assert truncated is False


def test_truncate_payload_trims_top_level_array():
    big = [{"x": "y" * 100} for _ in range(1000)]
    result, truncated = agent.truncate_payload(big, cap_bytes=512)
    assert truncated is True
    assert isinstance(result, list)
    assert len(result) < 1000
    # Serialized result must fit within the cap.
    assert len(json.dumps(result, default=str)) <= 512


def test_truncate_payload_stringifies_oversize_dict():
    big = {f"k{i}": "x" * 100 for i in range(100)}
    result, truncated = agent.truncate_payload(big, cap_bytes=512)
    assert truncated is True
    assert isinstance(result, str)
    assert len(result) <= 512
    assert result.endswith("…")
