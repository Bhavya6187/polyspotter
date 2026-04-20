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


# -------------------------------------------------------------- http helper --

class FakeHTTP:
    """Canned-response requests substitute, also records calls."""

    def __init__(self, responses):
        # responses: dict mapping URL -> body (dict) OR a single body dict
        self._responses = responses
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if isinstance(self._responses, dict):
            body = self._responses.get(url, {})
        else:
            body = self._responses
        resp = SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: body
        resp.raise_for_status = lambda: None
        return resp


class FailingHTTP:
    """Raises requests.exceptions.Timeout on every call."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        import requests
        self.calls.append(url)
        raise requests.exceptions.Timeout("fake timeout")


def test_http_get_json_returns_parsed_body():
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": {"wallet": "0xabc", "wins": 7}})
    result = agent._http_get_json("https://api.example.test/api/wallets/0xabc", http=http, timeout=5)
    assert result == {"wallet": "0xabc", "wins": 7}


def test_http_get_json_surfaces_timeout_as_exception():
    http = FailingHTTP()
    with pytest.raises(agent.HTTPToolError):
        agent._http_get_json("https://api.example.test/x", http=http, timeout=5)


# -------------------------------------------------------- get_wallet_profile --

def test_get_wallet_profile_returns_full_envelope():
    body = {"wallet": "0xabc", "wins": 7, "bet_history": [{"won": True}, {"won": False}]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": body})

    env = agent.get_wallet_profile(wallet="0xabc", http=http, api_url="https://api.example.test")

    assert env["data"] == body
    assert env["truncated"] is False


def test_get_wallet_profile_applies_projection():
    body = {"wallet": "0xabc", "bet_history": [1, 2, 3, 4, 5]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": body})

    env = agent.get_wallet_profile(
        wallet="0xabc", projection="length(bet_history)",
        http=http, api_url="https://api.example.test",
    )

    assert env["data"] == 5


def test_get_wallet_profile_bad_projection_returns_error():
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": {"a": 1}})
    env = agent.get_wallet_profile(
        wallet="0xabc", projection="invalid(",
        http=http, api_url="https://api.example.test",
    )
    assert "error" in env
    assert "projection" in env["error"]


def test_get_wallet_profile_http_error_returns_error():
    env = agent.get_wallet_profile(
        wallet="0xabc", http=FailingHTTP(), api_url="https://api.example.test",
    )
    assert "error" in env
    assert "http" in env["error"].lower()
