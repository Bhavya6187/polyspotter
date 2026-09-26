"""
One bad alert must not poison the whole ingest batch.

The per-alert try/except in /api/ingest ran inside a single Postgres
transaction with no SAVEPOINT, so the first failing INSERT put the
connection into "current transaction is aborted"; every later statement
(remaining alerts, wallet_profiles, the price_candles cleanup) then raised
InFailedSqlTransaction, the batch rolled back and the endpoint returned 500.
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


class _RecordingCursor:
    """Fails the alerts INSERT for dedup_key == 'bad'; records every statement."""

    def __init__(self):
        self.sql: list[str] = []
        self._last = None
        self._ids = 0
        self.rowcount = 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sql.append(s)
        if s.startswith("INSERT INTO alerts"):
            dedup_key = params[-1]
            if dedup_key == "bad":
                raise RuntimeError("integer out of range")
            self._ids += 1
            self._last = {"id": self._ids, "inserted": True}
        else:
            self._last = None

    def executemany(self, sql, seq):
        self.sql.append(" ".join(sql.split()))
        self.rowcount = len(list(seq))

    def fetchone(self):
        return self._last

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _alert(dedup_key):
    return {"composite_score": 5.0, "dedup_key": dedup_key, "market_title": f"m-{dedup_key}",
            "condition_id": "0xc", "trades": [], "signals": []}


def test_failing_alert_is_isolated_with_a_savepoint(monkeypatch):
    cur = _RecordingCursor()

    @contextmanager
    def fake_db():
        yield _Conn(cur)

    monkeypatch.setattr(app_module, "db", fake_db)
    monkeypatch.setattr(app_module, "INGEST_TOKEN", "")

    resp = client.post("/api/ingest", json={"alerts": [_alert("good1"), _alert("bad"), _alert("good2")]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted_alerts"] == 2
    assert body["skipped_alerts"] == 1

    savepoints = [s for s in cur.sql if s.upper().startswith("SAVEPOINT")]
    rollbacks = [s for s in cur.sql if s.upper().startswith("ROLLBACK TO SAVEPOINT")]
    releases = [s for s in cur.sql if s.upper().startswith("RELEASE SAVEPOINT")]
    assert len(savepoints) == 3, "one savepoint per alert"
    assert len(rollbacks) == 1, "the failing alert rolls back to its savepoint"
    assert len(releases) == 3, "every alert releases its savepoint (also after a rollback)"

    # The rollback must come right after the failing INSERT (the 2nd alert),
    # before the next alert's SAVEPOINT.
    inserts = [i for i, s in enumerate(cur.sql) if s.startswith("INSERT INTO alerts")]
    assert len(inserts) == 3
    assert cur.sql[inserts[1] + 1].upper().startswith("ROLLBACK TO SAVEPOINT")
    assert cur.sql[inserts[1] + 2].upper().startswith("RELEASE SAVEPOINT")
    assert cur.sql[inserts[1] + 3].upper().startswith("SAVEPOINT")
