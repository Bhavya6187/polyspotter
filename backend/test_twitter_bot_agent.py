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
