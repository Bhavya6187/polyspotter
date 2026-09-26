from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


def _capture_saves(monkeypatch):
    """Replace the DB write with an in-memory recorder; returns the list."""
    saved = []
    monkeypatch.setattr(app_module, "_save_subscriber", lambda email, source: saved.append((email, source)))
    return saved


def test_subscribe_valid_email_saves(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "Person@Example.COM ", "source": "hero"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # normalized: trimmed + lowercased
    assert saved == [("person@example.com", "hero")]


def test_subscribe_invalid_email_rejected(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "not-an-email", "source": "hero"})
    assert resp.status_code == 400
    assert saved == []


def test_subscribe_honeypot_silently_accepted(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "bot@example.com", "hp": "i am a bot"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert saved == []   # honeypot filled -> accepted silently, nothing saved


def test_subscribe_overlong_email_rejected(monkeypatch):
    saved = _capture_saves(monkeypatch)
    long_email = ("a" * 320) + "@example.com"  # > 320 chars total
    resp = client.post("/api/subscribe", json={"email": long_email, "source": "hero"})
    assert resp.status_code == 400
    assert saved == []


def test_subscribe_truncates_long_source(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "a@b.com", "source": "x" * 200})
    assert resp.status_code == 200
    # source stored is truncated to <= 64 chars
    assert len(saved) == 1
    assert len(saved[0][1]) <= 64


def _unsub_recorder(monkeypatch):
    """Fake db(): records executed SQL instead of touching Postgres."""
    from contextlib import contextmanager
    calls = []

    @contextmanager
    def fake():
        class Cur:
            def execute(self, sql, params=None):
                calls.append((sql, params))

        class Conn:
            def cursor(self):
                return Cur()

        yield Conn()

    monkeypatch.setattr(app_module, "db", fake)
    return calls


def test_unsubscribe_get_shows_confirm_form_without_writing(monkeypatch):
    """Link scanners prefetch GET links in emails; GET must not unsubscribe.
    It renders a form that POSTs back to the same URL."""
    import uuid
    calls = _unsub_recorder(monkeypatch)
    tok = str(uuid.uuid4())
    resp = client.get(f"/api/unsubscribe?token={tok}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert '<form method="post"' in resp.text
    assert f'action="/api/unsubscribe?token={tok}"' in resp.text
    assert calls == []


def test_unsubscribe_post_unsubscribes(monkeypatch):
    """RFC 8058 List-Unsubscribe-Post and the confirm form both POST."""
    import uuid
    calls = _unsub_recorder(monkeypatch)
    tok = str(uuid.uuid4())
    resp = client.post(f"/api/unsubscribe?token={tok}")
    assert resp.status_code == 200
    assert "unsubscribed" in resp.text.lower()
    assert len(calls) == 1
    sql, params = calls[0]
    assert "UPDATE subscribers" in sql and params == (tok,)


def test_unsubscribe_get_with_malformed_token_is_safe(monkeypatch):
    calls = _unsub_recorder(monkeypatch)
    resp = client.get('/api/unsubscribe?token="><script>x</script>')
    assert resp.status_code == 200
    assert "<script>x</script>" not in resp.text
    assert calls == []
