"""
Tests that backfill_events' SEO phase skips content-filtered events
permanently instead of crashing mid-backfill: it stamps seo_skip_reason,
continues with the remaining rows, and its candidate query excludes
already-skipped rows. Uses fake DB connections — no Postgres required.
"""

import backfill_events
from seo_generator import ContentFilterError


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.conn.fetchall_results.pop(0) if self.conn.fetchall_results else []

    def fetchone(self):
        return self.conn.fetchone_results.pop(0) if self.conn.fetchone_results else {}


class FakeConn:
    """Shared across all get_conn() calls; close()/commit() are no-ops."""

    def __init__(self, fetchall_results=None, fetchone_results=None):
        self.fetchall_results = list(fetchall_results or [])
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def close(self):
        pass


EVENT_ROW = {
    "event_slug": "test-filtered-event",
    "title": "TEST: filtered event",
    "description": None,
    "end_date": None,
    "tags": "[]",
}


def test_phase_seo_content_filter_marks_skip_and_continues(monkeypatch):
    conn = FakeConn(
        # candidates, then _load_seo_context's titles + headlines
        fetchall_results=[[EVENT_ROW], [], []],
        fetchone_results=[{"alert_count": 1, "total_usd": 100.0}],
    )
    monkeypatch.setattr(backfill_events, "get_conn", lambda: conn)

    def _raise_content_filter(**kwargs):
        raise ContentFilterError("blocked")

    monkeypatch.setattr(
        backfill_events, "generate_event_seo_content", _raise_content_filter
    )

    generated = backfill_events.phase_seo(limit=None)

    assert generated == 0
    skip_updates = [
        (sql, params) for sql, params in conn.executed
        if "UPDATE events" in sql and "seo_skip_reason" in sql
    ]
    assert len(skip_updates) == 1
    assert skip_updates[0][1][-1] == "test-filtered-event"


def test_phase_seo_candidates_exclude_skipped_rows(monkeypatch):
    conn = FakeConn(fetchall_results=[[]])
    monkeypatch.setattr(backfill_events, "get_conn", lambda: conn)

    backfill_events.phase_seo(limit=None)

    candidates_sql = conn.executed[0][0]
    assert "seo_skip_reason IS NULL" in candidates_sql
