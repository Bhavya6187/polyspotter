"""
Tests that the SEO worker permanently skips content-filtered rows.

When a generator raises ContentFilterError, the worker must stamp
seo_skip_reason on the row so the candidate queries stop re-selecting it
every pass (previously blocked markets were retried every 10 minutes,
forever). Uses fake DB connections — no Postgres required.
"""

import seo_worker
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
    def __init__(self, fetchall_results=None, fetchone_results=None):
        self.fetchall_results = list(fetchall_results or [])
        self.fetchone_results = list(fetchone_results or [])
        self.executed = []
        self.autocommit = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


MARKET_ROW = {
    "condition_id": "cid1",
    "market_title": "TEST: filtered market",
    "market_description": None,
    "tags": "[]",
    "end_date": None,
    "total_usd": 100.0,
    "alert_count": 1,
    "latest_scanned_at": None,
}

EVENT_ROW = {
    "event_slug": "test-filtered-event",
    "title": "TEST: filtered event",
    "description": None,
    "end_date": None,
    "tags": "[]",
}


def _raise_content_filter(**kwargs):
    raise ContentFilterError("blocked")


def test_market_content_filter_marks_row_skipped(monkeypatch):
    conn = FakeConn(fetchall_results=[[MARKET_ROW], []])  # candidates, headlines
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)
    monkeypatch.setattr(seo_worker, "generate_seo_content", _raise_content_filter)

    generated = seo_worker.run_market_seo()

    assert generated == 0
    skip_updates = [
        (sql, params) for sql, params in conn.executed
        if "UPDATE alerts" in sql and "seo_skip_reason" in sql
    ]
    assert len(skip_updates) == 1
    assert skip_updates[0][1][-1] == "cid1"


def test_market_candidates_exclude_skipped_rows(monkeypatch):
    conn = FakeConn(fetchall_results=[[]])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_market_seo()

    candidates_sql = conn.executed[0][0]
    assert "seo_skip_reason IS NULL" in candidates_sql


def test_event_content_filter_marks_row_skipped(monkeypatch):
    conn = FakeConn(
        fetchall_results=[[EVENT_ROW], [], []],  # candidates, titles, headlines
        fetchone_results=[{"alert_count": 1, "total_usd": 100.0}],
    )
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)
    monkeypatch.setattr(seo_worker, "generate_event_seo_content", _raise_content_filter)

    generated = seo_worker.run_event_seo()

    assert generated == 0
    skip_updates = [
        (sql, params) for sql, params in conn.executed
        if "UPDATE events" in sql and "seo_skip_reason" in sql
    ]
    assert len(skip_updates) == 1
    assert skip_updates[0][1][-1] == "test-filtered-event"


def test_event_candidates_exclude_skipped_rows(monkeypatch):
    conn = FakeConn(fetchall_results=[[]])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_event_seo()

    candidates_sql = conn.executed[0][0]
    assert "seo_skip_reason IS NULL" in candidates_sql


def test_other_errors_do_not_mark_skip(monkeypatch):
    def _raise_transient(**kwargs):
        raise RuntimeError("connection reset")

    conn = FakeConn(fetchall_results=[[MARKET_ROW], []])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)
    monkeypatch.setattr(seo_worker, "generate_seo_content", _raise_transient)

    generated = seo_worker.run_market_seo()

    assert generated == 0
    assert not any("seo_skip_reason" in sql and "UPDATE" in sql for sql, _ in conn.executed)
