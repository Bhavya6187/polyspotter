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


# ---------------------------------------------------- get_alert_detail --

def test_get_alert_detail_calls_correct_endpoint():
    body = {"id": 42, "trades": [], "signals": [{"strategy": "new_wallet_large_bet", "severity": 4.0}]}
    http = FakeHTTP({"https://api.example.test/api/alerts/42": body})
    env = agent.get_alert_detail(alert_id=42, http=http, api_url="https://api.example.test")
    assert env["data"]["id"] == 42
    assert http.calls[0]["url"] == "https://api.example.test/api/alerts/42"


# ------------------------------------------ get_market_price_history --

def test_get_market_price_history_passes_hours_param():
    body = {"candles": [{"t": 1, "p": 0.5}]}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/price-history": body})
    env = agent.get_market_price_history(
        condition_id="0xcond", hours=12,
        http=http, api_url="https://api.example.test",
    )
    assert env["data"] == body
    assert http.calls[0]["params"] == {"hours": 12}


def test_get_market_price_history_defaults_to_24_hours():
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/price-history": {"candles": []}})
    agent.get_market_price_history(
        condition_id="0xcond", http=http, api_url="https://api.example.test",
    )
    assert http.calls[0]["params"] == {"hours": 24}


# ------------------------------------------------- get_market_holders --

def test_get_market_holders_returns_holder_data():
    body = {"holders": {"Yes": [{"wallet": "0x1", "shares": 100}]}}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/holders": body})
    env = agent.get_market_holders(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body


# ----------------------------------------------------- get_live_market --

def test_get_live_market_returns_live_data():
    body = {"state": "live", "score": "2-1"}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/live": body})
    env = agent.get_live_market(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body


# --------------------------------------------------------- Postgres fakes ---

class FakePgCursor:
    """Minimal psycopg2 cursor substitute with canned rows per query pattern."""

    def __init__(self, rows_by_marker):
        # rows_by_marker: dict mapping a substring marker -> list of RealDict-like rows
        self._rows_by_marker = rows_by_marker
        self._rows = []
        self.last_query = None
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params
        self._rows = []
        for marker, rows in self._rows_by_marker.items():
            if marker in query:
                self._rows = rows
                return
        # No marker matched — return empty.

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakePgConn:
    def __init__(self, cursor):
        self._cur = cursor

    def cursor(self, cursor_factory=None):
        return self._cur

    def commit(self):
        pass


# ------------------------------------------------------- get_market_alerts ---

def test_get_market_alerts_returns_rows():
    rows = [
        {"id": 1, "composite_score": 12.0, "wallet": "0xa", "total_usd": 10000,
         "llm_headline": "hd1", "created_at": "2026-04-19T12:00:00Z"},
        {"id": 2, "composite_score": 11.0, "wallet": "0xb", "total_usd": 8000,
         "llm_headline": "hd2", "created_at": "2026-04-19T11:00:00Z"},
    ]
    cur = FakePgCursor({"FROM alerts WHERE condition_id": rows})
    conn = FakePgConn(cur)
    env = agent.get_market_alerts(condition_id="0xcond", limit=10, db_conn_pg=conn)
    assert len(env["data"]) == 2
    assert env["data"][0]["id"] == 1
    assert cur.last_params == ("0xcond", 10)


# ------------------------------------------------------- get_event_alerts ---

def test_get_event_alerts_queries_event_slug():
    rows = [{"id": 7, "composite_score": 15.0, "wallet": "0xz", "total_usd": 20000,
             "llm_headline": "h", "market_title": "mt", "created_at": "2026-04-19T10:00:00Z"}]
    cur = FakePgCursor({"FROM alerts WHERE event_slug": rows})
    conn = FakePgConn(cur)
    env = agent.get_event_alerts(event_slug="my-event", limit=20, db_conn_pg=conn)
    assert env["data"][0]["id"] == 7
    assert cur.last_params == ("my-event", 20)


# ---------------------------------------------------- search_alerts_by_tag ---

def test_search_alerts_by_tag_filters_by_tag_and_window():
    rows = [{"id": 100, "composite_score": 9.0, "wallet": "0x1", "market_title": "x",
             "total_usd": 5000, "llm_headline": "hh", "created_at": "2026-04-19T08:00:00Z"}]
    cur = FakePgCursor({"tags::jsonb @>": rows})
    conn = FakePgConn(cur)
    env = agent.search_alerts_by_tag(tag="Iran", hours=12, limit=5, db_conn_pg=conn)
    assert env["data"][0]["id"] == 100
    # First param is the JSON-encoded tag array.
    assert cur.last_params[0] == '["Iran"]'
    assert cur.last_params[1] == 12
    assert cur.last_params[2] == 5
