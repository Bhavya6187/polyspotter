"""
POST /api/ingest must require the shared secret when one is configured.

Before this, anyone could POST alerts to api.polyspotter.com/api/ingest:
they would render on the homepage, get tweeted, emailed in the digest and
graded onto the public scoreboard, and ON CONFLICT DO UPDATE let a caller
overwrite an existing alert's LLM headline / summary / copy action.

Rollout is fail-open: with POLYBOT_INGEST_TOKEN unset on the server the
endpoint behaves as before (and logs a warning at startup), so the backend
can deploy before the Railway variable and the scanner's .env are updated.
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


class _NoopCursor:
    rowcount = 0

    def execute(self, *_a, **_kw):
        pass

    def executemany(self, *_a, **_kw):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _NoopConn:
    def cursor(self):
        return _NoopCursor()


@contextmanager
def _fake_db():
    yield _NoopConn()


def _use_fake_db(monkeypatch):
    monkeypatch.setattr(app_module, "db", _fake_db)


def test_missing_token_rejected_when_configured(monkeypatch):
    _use_fake_db(monkeypatch)
    monkeypatch.setattr(app_module, "INGEST_TOKEN", "s3cret")
    resp = client.post("/api/ingest", json={})
    assert resp.status_code == 401


def test_wrong_token_rejected_when_configured(monkeypatch):
    _use_fake_db(monkeypatch)
    monkeypatch.setattr(app_module, "INGEST_TOKEN", "s3cret")
    resp = client.post("/api/ingest", json={}, headers={"X-Ingest-Token": "nope"})
    assert resp.status_code == 401


def test_correct_token_accepted(monkeypatch):
    _use_fake_db(monkeypatch)
    monkeypatch.setattr(app_module, "INGEST_TOKEN", "s3cret")
    resp = client.post("/api/ingest", json={}, headers={"X-Ingest-Token": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_unconfigured_token_is_fail_open(monkeypatch):
    _use_fake_db(monkeypatch)
    monkeypatch.setattr(app_module, "INGEST_TOKEN", "")
    resp = client.post("/api/ingest", json={})
    assert resp.status_code == 200
