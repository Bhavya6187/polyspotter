"""
Tests for the Railway cost-control changes:

- request-scoped DB connections come from a shared pool (with a fresh-connection
  fallback when the pool is exhausted) instead of a new TCP+auth handshake per
  request;
- /api/market/{id}/live reports Gamma's `closed` flag so the frontend can cache
  resolved markets for much longer, and the backend itself caches closed
  markets longer;
- the proxy caches are TTL-bounded so stale entries don't sit in RSS forever.

No database needed — psycopg2 is replaced with fakes.
"""

import os
import time

import pytest

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://localhost/polybot_test"

from psycopg2 import pool as pgpool

import database
import app as app_module
from models import LiveMarketData


class FakeConn:
    def __init__(self):
        self.closed = 0
        self.committed = False
        self.rolled_back = False
        self.close_calls = 0

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.close_calls += 1
        self.closed = 1


class FakePool:
    def __init__(self, conns):
        self.free = list(conns)
        self.returned = []  # (conn, close) tuples passed to putconn

    def getconn(self):
        if not self.free:
            raise pgpool.PoolError("connection pool exhausted")
        return self.free.pop()

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

def test_pooled_connection_is_returned_not_closed(monkeypatch):
    conn = FakeConn()
    pool = FakePool([conn])
    monkeypatch.setattr(database, "_POOL", pool)

    got, pooled = database.get_pooled_conn()
    assert got is conn and pooled is True

    database.release_conn(got, pooled)
    assert pool.returned == [(conn, False)]
    assert conn.close_calls == 0


def test_broken_pooled_connection_is_discarded(monkeypatch):
    conn = FakeConn()
    conn.closed = 2  # psycopg2 marks a dead socket as closed != 0
    pool = FakePool([conn])
    monkeypatch.setattr(database, "_POOL", pool)

    got, pooled = database.get_pooled_conn()
    database.release_conn(got, pooled)
    assert pool.returned == [(conn, True)]


def test_exhausted_pool_falls_back_to_fresh_connection(monkeypatch):
    pool = FakePool([])
    monkeypatch.setattr(database, "_POOL", pool)
    fresh = FakeConn()
    monkeypatch.setattr(database, "get_conn", lambda: fresh)

    got, pooled = database.get_pooled_conn()
    assert got is fresh and pooled is False

    database.release_conn(got, pooled)
    assert fresh.close_calls == 1
    assert pool.returned == []


def test_db_context_manager_commits_and_releases(monkeypatch):
    conn = FakeConn()
    pool = FakePool([conn])
    monkeypatch.setattr(database, "_POOL", pool)

    with app_module.db() as c:
        assert c is conn
    assert conn.committed is True
    assert pool.returned == [(conn, False)]


def test_db_context_manager_rolls_back_and_releases_on_error(monkeypatch):
    conn = FakeConn()
    pool = FakePool([conn])
    monkeypatch.setattr(database, "_POOL", pool)

    with pytest.raises(ValueError):
        with app_module.db():
            raise ValueError("boom")
    assert conn.rolled_back is True
    assert conn.committed is False
    assert pool.returned == [(conn, False)]


# ---------------------------------------------------------------------------
# Live market `closed` flag
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self.ok = ok

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_live_market_reports_closed_on_gamma_fallback_path(monkeypatch):
    gamma = [{
        "closed": True,
        "outcomes": "[]",
        "clobTokenIds": "[]",
        "outcomePrices": '["0", "1"]',
    }]
    monkeypatch.setattr(app_module._requests, "get", lambda *a, **k: FakeResp(gamma))

    data = app_module._fetch_live_market("0xabc")
    assert data.closed is True


def test_live_market_reports_closed_on_clob_path(monkeypatch):
    gamma = [{
        "closed": False,
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["t1", "t2"]',
        "outcomePrices": '["0.6", "0.4"]',
    }]

    def fake_get(url, **kwargs):
        if "gamma" in url:
            return FakeResp(gamma)
        return FakeResp({"spread": "0.01"})

    monkeypatch.setattr(app_module._requests, "get", fake_get)
    monkeypatch.setattr(
        app_module._requests, "post",
        lambda *a, **k: FakeResp({"t1": "0.61", "t2": "0.39"}),
    )

    data = app_module._fetch_live_market("0xabc")
    assert data.closed is False
    assert data.outcomes[0].price == pytest.approx(0.61)


def test_closed_markets_are_cached_longer_than_open_ones(monkeypatch):
    app_module._live_cache.clear()

    def fake_fetch(cid):
        return LiveMarketData(condition_id=cid, closed=cid.endswith("closed"))

    monkeypatch.setattr(app_module, "_fetch_live_market", fake_fetch)

    app_module.get_market_live("0xopen")
    app_module.get_market_live("0xclosed")

    now = time.time()
    open_expiry = app_module._live_cache["0xopen"][0]
    closed_expiry = app_module._live_cache["0xclosed"][0]
    assert open_expiry - now <= app_module._LIVE_CACHE_TTL + 1
    assert closed_expiry - now > app_module._LIVE_CACHE_TTL + 60


# ---------------------------------------------------------------------------
# Cache bounds
# ---------------------------------------------------------------------------

def test_proxy_caches_are_ttl_bounded():
    from cachetools import TTLCache

    for cache in (
        app_module._live_cache,
        app_module._price_history_cache,
        app_module._holders_cache,
        app_module._gamma_status_cache,
    ):
        assert isinstance(cache, TTLCache)
        assert cache.maxsize <= 2000
