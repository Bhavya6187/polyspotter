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


def test_get_wallet_profile_bad_projection_returns_raw_with_projection_error():
    body = {"a": 1}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": body})
    env = agent.get_wallet_profile(
        wallet="0xabc", projection="invalid(",
        http=http, api_url="https://api.example.test",
    )
    # Bad projection no longer fails the call — raw data comes back with a
    # projection_error note so the model can recover without a second call.
    assert env["data"] == body
    assert "projection_error" in env
    assert "projection" in env["projection_error"]
    assert "error" not in env


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
    cur = FakePgCursor({"jsonb_array_elements_text": rows})
    conn = FakePgConn(cur)
    env = agent.search_alerts_by_tag(tag="Iran", hours=12, limit=5, db_conn_pg=conn)
    assert env["data"][0]["id"] == 100
    # Case-insensitive matching: bare tag string, not JSON-encoded array.
    assert cur.last_params[0] == "Iran"
    assert cur.last_params[1] == 12
    assert cur.last_params[2] == 5


def test_pg_fetchall_rolls_back_on_error():
    """After a query fails, the connection must be usable again."""
    class RaisingCursor(FakePgCursor):
        def execute(self, query, params=None):
            raise RuntimeError("simulated db error")

    class RollbackTrackingConn(FakePgConn):
        def __init__(self, cur):
            super().__init__(cur)
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

    raising = RaisingCursor({})
    conn = RollbackTrackingConn(raising)

    env = agent.get_market_alerts(condition_id="0xcond", limit=10, db_conn_pg=conn)

    assert "error" in env
    assert conn.rolled_back is True


# ----------------------------------------------------------- get_theses ---

def test_get_theses_rejects_zero_filters():
    env = agent.get_theses(http=FakeHTTP({}), api_url="https://api.example.test")
    assert "error" in env
    assert "exactly one" in env["error"]


def test_get_theses_rejects_multiple_filters():
    env = agent.get_theses(
        wallet="0xa", event_slug="ev",
        http=FakeHTTP({}), api_url="https://api.example.test",
    )
    assert "error" in env


def test_get_theses_uses_market_endpoint_for_condition_id():
    body = [{"thesis_id": 1, "headline": "thesis"}]
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/theses": body})
    env = agent.get_theses(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body


def test_get_theses_filters_client_side_by_wallet():
    body = {"theses": [
        {"id": 1, "wallet": "0xa", "event_slug": "e1"},
        {"id": 2, "wallet": "0xb", "event_slug": "e1"},
        {"id": 3, "wallet": "0xa", "event_slug": "e2"},
    ]}
    http = FakeHTTP({"https://api.example.test/api/theses": body})
    env = agent.get_theses(wallet="0xa", http=http, api_url="https://api.example.test")
    assert len(env["data"]) == 2
    assert {t["id"] for t in env["data"]} == {1, 3}


def test_get_theses_filters_client_side_by_event_slug():
    body = {"theses": [
        {"id": 1, "wallet": "0xa", "event_slug": "e1"},
        {"id": 2, "wallet": "0xb", "event_slug": "e1"},
        {"id": 3, "wallet": "0xa", "event_slug": "e2"},
    ]}
    http = FakeHTTP({"https://api.example.test/api/theses": body})
    env = agent.get_theses(event_slug="e1", http=http, api_url="https://api.example.test")
    assert {t["id"] for t in env["data"]} == {1, 2}


# ------------------------------------------------------------- SQLite tools --

def _make_sqlite_conn():
    """Build an in-memory SQLite DB seeded with the tables our tools query."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE wallet_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, condition_id TEXT, asset TEXT, outcome TEXT,
            avg_price REAL, total_bought REAL, realized_pnl REAL, cur_price REAL,
            event_slug TEXT, end_date TEXT, position_type TEXT,
            recorded_at TEXT, api_timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE timing_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, condition_id TEXT, minutes_to_resolution REAL,
            usd_value REAL, trade_timestamp REAL, recorded_at TEXT,
            market_duration_hours REAL
        )
    """)
    conn.execute("""
        CREATE TABLE wallet_event_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, event_slug TEXT, condition_id TEXT, outcome TEXT,
            side TEXT, usd_value REAL, trade_timestamp REAL, recorded_at TEXT,
            price REAL, market_title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE wallet_funders (
            wallet TEXT PRIMARY KEY, funder TEXT, discovered_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT, token_id TEXT, outcome TEXT,
            best_bid REAL, best_ask REAL, spread REAL,
            bid_depth REAL, ask_depth REAL, mid_price REAL, snapshot_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE market_volume_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT, volume_24h REAL, snapshot_at TEXT
        )
    """)
    conn.commit()
    return conn


def test_get_wallet_pnl_positions_returns_rows():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_pnl (wallet, condition_id, outcome, avg_price, total_bought, "
        "realized_pnl, cur_price, position_type, end_date, recorded_at) VALUES "
        "('0xa', 'c1', 'Yes', 0.35, 10000, 500, 0.62, 'open', NULL, '2026-04-19')"
    )
    conn.commit()
    env = agent.get_wallet_pnl_positions(wallet="0xa", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 1
    assert env["data"][0]["outcome"] == "Yes"
    assert env["data"][0]["avg_price"] == 0.35


def test_get_wallet_pnl_positions_lowercases_wallet():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_pnl (wallet, condition_id, outcome, avg_price, total_bought, "
        "realized_pnl, cur_price, position_type, end_date, recorded_at) VALUES "
        "('0xabc', 'c1', 'Yes', 0.3, 5000, 0, 0.5, 'open', NULL, '2026-04-19')"
    )
    conn.commit()
    env = agent.get_wallet_pnl_positions(wallet="0xABC", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 1


def test_get_wallet_timing_pattern_returns_stats():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO timing_flags (wallet, condition_id, minutes_to_resolution, "
        "usd_value, trade_timestamp, recorded_at, market_duration_hours) VALUES "
        "('0xa', 'c1', 5.0, 10000, 1700000000, '2026-04-19', 72)"
    )
    conn.execute(
        "INSERT INTO timing_flags (wallet, condition_id, minutes_to_resolution, "
        "usd_value, trade_timestamp, recorded_at, market_duration_hours) VALUES "
        "('0xa', 'c2', 10.0, 5000, 1700000100, '2026-04-19', 48)"
    )
    conn.commit()
    env = agent.get_wallet_timing_pattern(wallet="0xa", db_conn_sqlite=conn)
    assert env["data"]["total_flags"] == 2
    assert env["data"]["distinct_markets"] == 2
    assert env["data"]["min_minutes"] == 5.0


def test_get_wallet_event_history_returns_trades():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_event_history (wallet, event_slug, condition_id, outcome, "
        "side, usd_value, trade_timestamp, recorded_at, price, market_title) VALUES "
        "('0xa', 'ev1', 'c1', 'Yes', 'BUY', 5000, 1700000000, '2026-04-19', 0.3, 'Mkt A')"
    )
    conn.execute(
        "INSERT INTO wallet_event_history (wallet, event_slug, condition_id, outcome, "
        "side, usd_value, trade_timestamp, recorded_at, price, market_title) VALUES "
        "('0xa', 'ev1', 'c2', 'No', 'BUY', 3000, 1700000100, '2026-04-19', 0.4, 'Mkt B')"
    )
    conn.commit()
    env = agent.get_wallet_event_history(wallet="0xa", event_slug="ev1", db_conn_sqlite=conn)
    assert len(env["data"]) == 2


def test_get_funder_cluster_returns_linked_wallets():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO wallet_funders (wallet, funder, discovered_at) VALUES (?, ?, ?)",
        [("0xa", "0xfund", "t1"), ("0xb", "0xfund", "t2"), ("0xc", "0xother", "t3")],
    )
    conn.commit()
    env = agent.get_funder_cluster(wallet="0xa", db_conn_sqlite=conn)
    assert env["data"]["funder"] == "0xfund"
    assert set(env["data"]["wallets"]) == {"0xa", "0xb"}


def test_get_funder_cluster_returns_empty_when_no_funder():
    conn = _make_sqlite_conn()
    env = agent.get_funder_cluster(wallet="0xnone", db_conn_sqlite=conn)
    assert env["data"] == {"funder": None, "wallets": []}


def test_get_orderbook_snapshot_returns_latest_per_token():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO orderbook_snapshots (condition_id, token_id, outcome, "
        "best_bid, best_ask, spread, bid_depth, ask_depth, mid_price, snapshot_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("c1", "tok-yes", "Yes", 0.60, 0.62, 0.02, 10000, 8000, 0.61, "2026-04-19T10:00:00"),
            ("c1", "tok-yes", "Yes", 0.58, 0.60, 0.02, 9000, 7500, 0.59, "2026-04-19T09:00:00"),
            ("c1", "tok-no", "No", 0.38, 0.40, 0.02, 5000, 4500, 0.39, "2026-04-19T10:00:00"),
        ],
    )
    conn.commit()
    env = agent.get_orderbook_snapshot(condition_id="c1", db_conn_sqlite=conn)
    assert len(env["data"]) == 2
    # Latest per token_id — check best_bid for tok-yes is 0.60 (from the 10:00 row).
    yes_row = next(r for r in env["data"] if r["token_id"] == "tok-yes")
    assert yes_row["best_bid"] == 0.60


def test_get_market_volume_history_returns_rows():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO market_volume_snapshots (condition_id, volume_24h, snapshot_at) VALUES (?, ?, ?)",
        [("c1", 5000, "2026-04-19T08:00:00"),
         ("c1", 12000, "2026-04-19T10:00:00"),
         ("c2", 9999, "2026-04-19T10:00:00")],
    )
    conn.commit()
    env = agent.get_market_volume_history(condition_id="c1", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 2
    # Sorted most recent first.
    assert env["data"][0]["volume_24h"] == 12000


# ---------------------------------------------------------- call_gamma_api ---

def test_call_gamma_api_allowed_path_makes_request():
    body = {"id": 1, "slug": "will-x", "volume": 5000}
    http = FakeHTTP({"https://gamma-api.polymarket.com/markets": body})
    env = agent.call_gamma_api(path="/markets", http=http)
    assert env["data"] == body
    assert http.calls[0]["url"] == "https://gamma-api.polymarket.com/markets"


def test_call_gamma_api_passes_query_params():
    http = FakeHTTP({"https://gamma-api.polymarket.com/events/my-event": {"id": 9}})
    env = agent.call_gamma_api(path="/events/my-event", params={"limit": 5}, http=http)
    assert env["data"]["id"] == 9
    assert http.calls[0]["params"] == {"limit": 5}


def test_call_gamma_api_rejects_disallowed_path():
    env = agent.call_gamma_api(path="/admin/secret", http=FakeHTTP({}))
    assert "error" in env
    assert "not allowed" in env["error"]


def test_call_gamma_api_rejects_missing_leading_slash():
    env = agent.call_gamma_api(path="markets", http=FakeHTTP({}))
    assert "error" in env


def test_call_gamma_api_rejects_external_path_injection():
    env = agent.call_gamma_api(path="/markets/../admin", http=FakeHTTP({}))
    assert "error" in env


# ------------------------------------------------------------- dispatcher ---

def test_tool_schemas_include_all_16_tools():
    schemas = agent.TOOL_SCHEMAS
    names = {s["function"]["name"] for s in schemas}
    expected = {
        "get_wallet_profile", "get_alert_detail", "get_market_price_history",
        "get_market_holders", "get_market_alerts", "get_event_alerts",
        "get_live_market", "get_theses", "search_alerts_by_tag",
        "get_wallet_pnl_positions", "get_wallet_timing_pattern",
        "get_wallet_event_history", "get_funder_cluster",
        "get_orderbook_snapshot", "get_market_volume_history",
        "call_gamma_api",
    }
    assert names == expected


def test_tool_schemas_every_tool_has_projection_param():
    for s in agent.TOOL_SCHEMAS:
        params = s["function"]["parameters"]["properties"]
        assert "projection" in params, f"{s['function']['name']} missing projection"


def test_dispatch_calls_tool_with_projection():
    body = {"wallet": "0xa", "bet_history": [1, 2, 3]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    deps = agent.ToolDeps(
        http=http, api_url="https://api.example.test",
        db_conn_pg=None, db_conn_sqlite=None,
    )
    env = agent.dispatch_tool(
        "get_wallet_profile",
        {"wallet": "0xa", "projection": "length(bet_history)"},
        deps=deps,
    )
    assert env["data"] == 3


def test_dispatch_unknown_tool_returns_error():
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    env = agent.dispatch_tool("made_up_tool", {}, deps=deps)
    assert "error" in env
    assert "unknown tool" in env["error"].lower()


def test_dispatch_bad_arg_types_returns_error():
    http = FakeHTTP({"https://api.example.test/api/alerts/7": {"id": 7}})
    deps = agent.ToolDeps(
        http=http, api_url="https://api.example.test",
        db_conn_pg=None, db_conn_sqlite=None,
    )
    # alert_id must be int — pass dict, triggers a coercion failure downstream.
    env = agent.dispatch_tool("get_alert_detail", {"alert_id": {"bad": "value"}}, deps=deps)
    assert "error" in env


def test_dispatch_respects_budget_marker():
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    env = agent.dispatch_tool_over_budget("get_wallet_profile", deps=deps)
    assert "error" in env
    assert "budget" in env["error"].lower()


# ----------------------------------------------------------- compose_tweet ---

class FakeLLMWithTools:
    """LLM fake that emits either tool_calls or a final content per scripted step.

    `script` is a list of either:
      - list of (tool_name, arguments_dict) — the model requests those tool calls
      - dict — final JSON decision (returned as message.content)
    """

    def __init__(self, script):
        self._script = list(script)
        self.call_log = []  # List of dicts mirroring create() kwargs (minus messages)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.call_log.append({k: v for k, v in kwargs.items() if k != "messages"})
        if not self._script:
            raise RuntimeError("FakeLLMWithTools script exhausted")
        step = self._script.pop(0)

        if isinstance(step, dict):
            # Final JSON content response, no tool calls.
            msg = SimpleNamespace(
                content=json.dumps(step),
                tool_calls=None,
                role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        if isinstance(step, str):
            # Raw string content (for malformed JSON tests).
            msg = SimpleNamespace(
                content=step,
                tool_calls=None,
                role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        # Tool-call step.
        tc = []
        for i, (name, args) in enumerate(step):
            tc.append(SimpleNamespace(
                id=f"call_{len(self.call_log)}_{i}",
                type="function",
                function=SimpleNamespace(name=name, arguments=json.dumps(args)),
            ))
        msg = SimpleNamespace(content=None, tool_calls=tc, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _alert(**overrides):
    base = {
        "id": 1,
        "composite_score": 8.0,
        "market_title": "Will X?",
        "condition_id": "0xcond",
        "event_slug": "ev",
        "wallet": "0xa",
        "total_usd": 25000,
        "trade_count": 2,
        "llm_headline": "Whale X",
        "llm_summary": "Wallet dropped $25k.",
        "win_rate": 0.82,
        "total_pnl": 340000,
        "tags": ["Politics"],
        "end_date": "2026-04-20T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_compose_tweet_zero_tool_calls_returns_decision():
    final = {
        "decision": "post", "reason": "strong alert",
        "alert_ids": [1], "tweet": "Short tweet. link in bio",
        "is_composite": False,
    }
    llm = FakeLLMWithTools([final])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "post"
    assert result["tweet"] == "Short tweet. link in bio"


def test_compose_tweet_uses_tool_result_then_composes():
    body = {"wallet": "0xa", "wins": 12}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    final = {
        "decision": "post", "reason": "ok",
        "alert_ids": [1], "tweet": "12 wins.",
        "is_composite": False,
    }
    llm = FakeLLMWithTools([
        [("get_wallet_profile", {"wallet": "0xa"})],
        final,
    ])
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "post"
    assert http.calls[0]["url"] == "https://api.example.test/api/wallets/0xa"


def test_compose_tweet_exhausts_budget_forcing_final_json():
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    # Script: MAX_TOOL_CALLS single-tool rounds + 1 more attempt that we force into JSON.
    rounds = [[("get_wallet_profile", {"wallet": "0xa"})] for _ in range(agent.MAX_TOOL_CALLS)]
    rounds.append([("get_wallet_profile", {"wallet": "0xa"})])
    final = {
        "decision": "skip", "reason": "exhausted",
        "alert_ids": None, "tweet": None, "is_composite": False,
    }
    rounds.append(final)
    llm = FakeLLMWithTools(rounds)
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "skip"
    # After budget exhaustion, the next LLM call should force tool_choice='none'.
    last_call = llm.call_log[-1]
    assert last_call.get("tool_choice") == "none"


def test_compose_tweet_single_turn_over_budget_truncates_dispatched():
    """If model asks for MAX+1 tools in one turn, we dispatch MAX and error the extras."""
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    over_budget = agent.MAX_TOOL_CALLS + 1
    calls_in_one_turn = [("get_wallet_profile", {"wallet": "0xa"}) for _ in range(over_budget)]
    final = {
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }
    llm = FakeLLMWithTools([calls_in_one_turn, final])
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "skip"
    # HTTP called exactly MAX_TOOL_CALLS times; the extras got budget-error envelopes.
    assert len(http.calls) == agent.MAX_TOOL_CALLS


def test_compose_tweet_raises_on_max_iterations_without_final_json():
    """A misbehaving model that never emits content triggers AgentOutputError."""
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    # Feed endless tool-call rounds.
    script = [[("get_wallet_profile", {"wallet": "0xa"})] for _ in range(20)]
    llm = FakeLLMWithTools(script)
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    with pytest.raises(agent.AgentOutputError):
        agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)


def test_compose_tweet_raises_on_malformed_final_json():
    bad = "{not valid json"
    llm = FakeLLMWithTools([bad])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    with pytest.raises(agent.AgentOutputError):
        agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)


def test_compose_tweet_invokes_on_tool_call_callback_per_dispatch():
    """Callback fires once per tool call with name, args, and envelope."""
    body = {"wallet": "0xa", "wins": 7}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    final = {
        "decision": "post", "reason": "ok",
        "alert_ids": [1], "tweet": "7 wins.", "is_composite": False,
    }
    llm = FakeLLMWithTools([
        [("get_wallet_profile", {"wallet": "0xa"})],
        final,
    ])
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    seen = []
    def cb(name, args, envelope):
        seen.append((name, args, envelope))

    agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps, on_tool_call=cb)

    assert len(seen) == 1
    name, args, envelope = seen[0]
    assert name == "get_wallet_profile"
    assert args == {"wallet": "0xa"}
    assert envelope.get("error") is None
    assert envelope["data"]["wins"] == 7


def test_compose_tweet_user_message_includes_condition_id_and_event_slug():
    """Without these fields, tools can't be called. Verify they're in the prompt."""
    llm = FakeLLMWithTools([{
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)

    # We don't directly inspect messages in the fake — instead, capture via a
    # subclass that records the messages list.
    captured = {}
    orig_create = llm.chat.completions.create
    def wrapped(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return orig_create(**kwargs)
    llm.chat.completions.create = wrapped

    agent.compose_tweet(
        [_alert(id=1, condition_id="0xcond", event_slug="my-ev")],
        llm_client=llm, deps=deps,
    )

    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    assert "0xcond" in user_msg["content"]
    assert "my-ev" in user_msg["content"]


# ============================================================================
# Stage 1 — validate_shortlist_decision
# ============================================================================

def test_validate_shortlist_skip_decision_succeeds_with_minimal_fields():
    raw = {"decision": "skip", "reason": "all routine"}
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3})
    assert result.decision == "skip"
    assert result.reason == "all routine"
    assert result.mode is None
    assert result.shortlist is None


def test_validate_shortlist_single_mode_with_two_items_succeeds():
    raw = {
        "decision": "shortlist", "reason": "two strong picks",
        "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "20-0 wallet sized up"},
            {"alert_id": 2, "angle": "new wallet near close"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3})
    assert result.decision == "shortlist"
    assert result.mode == "single"
    assert len(result.shortlist) == 2
    assert result.shortlist[0].alert_id == 1
    assert result.shortlist[0].angle == "20-0 wallet sized up"


def test_validate_shortlist_composite_mode_with_three_items_succeeds():
    raw = {
        "decision": "shortlist", "reason": "shared funder cluster",
        "mode": "composite",
        "shortlist": [
            {"alert_id": 1, "angle": "wallet A"},
            {"alert_id": 2, "angle": "wallet B (same funder)"},
            {"alert_id": 3, "angle": "wallet C (same funder)"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3, 4})
    assert result.mode == "composite"
    assert len(result.shortlist) == 3


def test_validate_shortlist_rejects_unknown_decision_value():
    raw = {"decision": "maybe", "reason": "x"}
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1})


def test_validate_shortlist_rejects_missing_mode_on_shortlist():
    raw = {
        "decision": "shortlist", "reason": "x",
        "shortlist": [{"alert_id": 1, "angle": "a"}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_invalid_mode_value():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "ensemble",
        "shortlist": [{"alert_id": 1, "angle": "a"}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_size_one():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": 1, "angle": "only one"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1})


def test_validate_shortlist_rejects_size_five():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": i, "angle": f"a{i}"} for i in (1, 2, 3, 4, 5)],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3, 4, 5})


def test_validate_shortlist_rejects_alert_id_not_in_input():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 99, "angle": "b"},  # 99 not in input
        ],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_empty_angle():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": ""},
            {"alert_id": 2, "angle": "b"},
        ],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_missing_angle():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": 1}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_non_dict_input():
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision("not a dict", valid_alert_ids={1})


def test_validate_shortlist_composite_with_two_items_succeeds():
    """Composite needs >= 2; size 2 is the minimum and should pass."""
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "composite",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 2, "angle": "b"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})
    assert result.mode == "composite"


# ============================================================================
# Stage 1 — select_shortlist
# ============================================================================

class FakeStage1LLM:
    """One-shot LLM fake. Returns the scripted content on first .create() call."""

    def __init__(self, response):
        # response: dict (returned as JSON content) or str (returned raw)
        self._response = response
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, dict):
            content = json.dumps(self._response)
        else:
            content = self._response
        msg = SimpleNamespace(content=content, tool_calls=None, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _stage1_alert(**overrides):
    """Slim alert dict shaped like what the bot passes into select_shortlist."""
    base = {
        "id": 1,
        "composite_score": 8.0,
        "llm_headline": "Whale loads X",
        "llm_summary": "Wallet dropped $25k.",
        "wallet": "0xa",
        "win_rate": 0.82,
        "total_usd": 25000.0,
        "market_title": "Will X happen?",
        "tags": ["Politics"],
        "condition_id": "0xcond",
        "event_slug": "ev-1",
    }
    base.update(overrides)
    return base


def test_select_shortlist_returns_skip_decision():
    llm = FakeStage1LLM({"decision": "skip", "reason": "nothing compelling"})
    result = agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)
    assert result.decision == "skip"
    assert result.reason == "nothing compelling"


def test_select_shortlist_returns_single_mode_with_angles():
    llm = FakeStage1LLM({
        "decision": "shortlist", "reason": "two clear picks", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "20-0 wallet"},
            {"alert_id": 2, "angle": "new wallet near close"},
        ],
    })
    result = agent.select_shortlist(
        [_stage1_alert(id=1), _stage1_alert(id=2), _stage1_alert(id=3)],
        llm_client=llm,
    )
    assert result.mode == "single"
    assert [s.alert_id for s in result.shortlist] == [1, 2]
    assert result.shortlist[0].angle == "20-0 wallet"


def test_select_shortlist_raises_on_invalid_json():
    llm = FakeStage1LLM("{not valid json")
    with pytest.raises(agent.ShortlistValidationError):
        agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)


def test_select_shortlist_raises_on_alert_id_not_in_input():
    llm = FakeStage1LLM({
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 999, "angle": "b"},
        ],
    })
    with pytest.raises(agent.ShortlistValidationError):
        agent.select_shortlist([_stage1_alert(id=1), _stage1_alert(id=2)], llm_client=llm)


def test_select_shortlist_makes_exactly_one_llm_call_with_json_mode():
    llm = FakeStage1LLM({"decision": "skip", "reason": "x"})
    agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["model"] == agent.MODEL
    assert call["response_format"] == {"type": "json_object"}
    assert "tools" not in call  # stage 1 has no tools


def test_select_shortlist_user_message_includes_slim_alert_fields():
    """Stage-1 payload should include enough for editorial judgment, not trade detail."""
    llm = FakeStage1LLM({"decision": "skip", "reason": "x"})
    agent.select_shortlist(
        [_stage1_alert(id=42, market_title="Tigers vs Red Sox", win_rate=0.91)],
        llm_client=llm,
    )
    user_msg = next(m for m in llm.calls[0]["messages"] if m["role"] == "user")
    # Required fields appear:
    assert "42" in user_msg["content"]
    assert "Tigers vs Red Sox" in user_msg["content"]
    # Bullets / copy_action / market_description NOT included (slim payload):
    assert "llm_bullets" not in user_msg["content"]
    assert "llm_copy_action" not in user_msg["content"]
    assert "market_description" not in user_msg["content"]


def test_select_shortlist_raises_on_empty_content():
    """When the LLM returns empty/None content, raise ShortlistValidationError."""

    class EmptyContentLLM:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            self.calls.append(kwargs)
            msg = SimpleNamespace(content=None, tool_calls=None, role="assistant")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    llm = EmptyContentLLM()
    with pytest.raises(agent.ShortlistValidationError, match="empty"):
        agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)


# ============================================================================
# build_user_message — selection arg
# ============================================================================

def test_build_user_message_without_selection_omits_selection_field():
    msg = agent.build_user_message([_alert(id=1)])
    parsed = json.loads(msg)
    assert "selection" not in parsed
    assert len(parsed["alerts"]) == 1


def test_build_user_message_with_selection_includes_mode_and_angles():
    selection = {"mode": "single", "angles": {"1": "verify 20-0 record", "2": "new wallet"}}
    msg = agent.build_user_message([_alert(id=1), _alert(id=2)], selection=selection)
    parsed = json.loads(msg)
    assert parsed["selection"]["mode"] == "single"
    assert parsed["selection"]["angles"]["1"] == "verify 20-0 record"
    assert parsed["selection"]["angles"]["2"] == "new wallet"


def test_build_user_message_with_composite_selection_passes_through():
    selection = {"mode": "composite", "angles": {"1": "wallet A"}}
    msg = agent.build_user_message([_alert(id=1)], selection=selection)
    parsed = json.loads(msg)
    assert parsed["selection"]["mode"] == "composite"
