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
