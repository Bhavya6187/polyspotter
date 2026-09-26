"""Unknown event slugs: the Gamma miss is cached so repeat hits don't refetch."""


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


def test_unknown_event_slug_miss_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "get_pooled_conn", lambda: (_FakeConn(), False))
    monkeypatch.setattr(events, "release_conn", lambda conn, pooled: None)
    monkeypatch.setattr(events, "fetch_event_from_gamma", lambda slug: calls.append(slug))
    events._event_miss_cache.clear()

    assert events.get_event_or_fetch("no-such-event-2026") is None
    assert events.get_event_or_fetch("no-such-event-2026") is None
    assert calls == ["no-such-event-2026"]


def test_gamma_timeout_is_5s():
    assert events.GAMMA_TIMEOUT == 5


