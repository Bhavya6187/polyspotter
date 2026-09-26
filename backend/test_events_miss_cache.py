"""Unknown event slugs: a clean Gamma miss is cached so repeat hits don't
refetch, but a Gamma transport failure (timeout / 5xx / 429) is not — a blip
must not make a real event "not found" for MISS_TTL_S."""

import pytest
import requests

import events


class _FakeCur:
    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return None  # slug not in the events table

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def cursor(self):
        return _FakeCur()


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def gamma(monkeypatch):
    """Route events' Gamma GETs to a scripted response; record each call."""
    calls = []
    state = {"respond": lambda: _Resp(200, [])}

    def fake_get(url, params=None, timeout=None):
        calls.append(params["slug"])
        return state["respond"]()

    monkeypatch.setattr(events, "get_pooled_conn", lambda: (_FakeConn(), False))
    monkeypatch.setattr(events, "release_conn", lambda conn, pooled: None)
    monkeypatch.setattr(events._requests, "get", fake_get)
    events._event_miss_cache.clear()
    yield calls, state
    events._event_miss_cache.clear()


def test_clean_empty_200_miss_is_cached(gamma):
    calls, _ = gamma
    assert events.get_event_or_fetch("no-such-event-2026") is None
    assert events.get_event_or_fetch("no-such-event-2026") is None
    assert calls == ["no-such-event-2026"]


def test_request_exception_is_not_cached(gamma):
    calls, state = gamma

    def boom():
        raise requests.Timeout("gamma timed out")

    state["respond"] = boom
    assert events.get_event_or_fetch("real-event-2026") is None
    assert events.get_event_or_fetch("real-event-2026") is None
    assert calls == ["real-event-2026", "real-event-2026"]


@pytest.mark.parametrize("status", [503, 429])
def test_gamma_error_status_is_not_cached(gamma, status):
    calls, state = gamma
    state["respond"] = lambda: _Resp(status)
    assert events.get_event_or_fetch("real-event-2026") is None
    assert events.get_event_or_fetch("real-event-2026") is None
    assert calls == ["real-event-2026", "real-event-2026"]


def test_fetch_event_from_gamma_still_returns_none_on_transport_error(monkeypatch):
    """Batch callers (backfill_events, seo_worker) rely on None, not a raise."""
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(events._requests, "get", boom)
    assert events.fetch_event_from_gamma("x") is None
    monkeypatch.setattr(events._requests, "get", lambda *a, **k: _Resp(503))
    assert events.fetch_event_from_gamma("x") is None


def test_gamma_timeout_is_5s():
    assert events.GAMMA_TIMEOUT == 5
