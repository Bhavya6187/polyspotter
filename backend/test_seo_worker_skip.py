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
        if "UPDATE alerts" in sql and "'content_filter'" in sql
    ]
    assert len(skip_updates) == 1
    assert skip_updates[0][1][-1] == "cid1"


def test_market_candidates_exclude_skipped_rows(monkeypatch):
    conn = FakeConn(fetchall_results=[[]])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_market_seo()

    candidates_sql = next(sql for sql, _ in conn.executed if sql.startswith("SELECT condition_id"))
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
        if "UPDATE events" in sql and "'content_filter'" in sql
    ]
    assert len(skip_updates) == 1
    assert skip_updates[0][1][-1] == "test-filtered-event"


def test_event_candidates_exclude_skipped_rows(monkeypatch):
    conn = FakeConn(fetchall_results=[[]])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_event_seo()

    candidates_sql = next(sql for sql, _ in conn.executed if sql.startswith("SELECT e.event_slug"))
    assert "seo_skip_reason IS NULL" in candidates_sql


def test_other_errors_do_not_mark_skip(monkeypatch):
    def _raise_transient(**kwargs):
        raise RuntimeError("connection reset")

    conn = FakeConn(fetchall_results=[[MARKET_ROW], []])
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)
    monkeypatch.setattr(seo_worker, "generate_seo_content", _raise_transient)

    generated = seo_worker.run_market_seo()

    assert generated == 0
    assert not any("'content_filter'" in sql and "UPDATE" in sql for sql, _ in conn.executed)


class CopyAwareConn(FakeConn):
    """Models the DB just enough for the copy step: market cid1 already has
    SEO on an older alert row and a new alert row with seo_generated_at NULL.
    Until the copy statement runs, the candidate SELECT still returns cid1
    (which the pre-copy worker sent to GPT); after the copy it returns none."""

    def __init__(self):
        super().__init__()
        self.copied = False

    def cursor(self):
        conn = self

        class _Cursor(FakeCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                flat = " ".join(sql.split())
                if flat.startswith("UPDATE alerts") and "src.seo_title" in flat:
                    conn.copied = True
                elif flat.startswith("SELECT condition_id"):
                    conn.fetchall_results = [[] if conn.copied else [MARKET_ROW], []]

        return _Cursor(self)


def test_worker_copies_existing_seo_instead_of_regenerating(monkeypatch):
    """A new alert row (seo_generated_at NULL) on a market that already has
    SEO gets the existing fields copied, before candidate selection, so the
    market is not re-sent to GPT."""
    conn = CopyAwareConn()
    gpt_calls = []

    def _no_gpt(**kwargs):
        gpt_calls.append(kwargs)
        raise AssertionError("GPT must not be called")

    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)
    monkeypatch.setattr(seo_worker, "generate_seo_content", _no_gpt)

    assert seo_worker.run_market_seo() == 0

    assert conn.copied, "the copy statement must run for the already-SEO'd market"
    assert gpt_calls == [], "GPT must not be called for a market that already has SEO"
    assert not any(
        sql.startswith("UPDATE alerts") and "seo_generated_at = NOW()" in sql
        for sql, _ in conn.executed
    )

    sqls = [sql for sql, _ in conn.executed]
    copy_idx = next(i for i, sql in enumerate(sqls) if sql.startswith("UPDATE alerts") and "seo_title" in sql)
    select_idx = next(i for i, sql in enumerate(sqls) if sql.startswith("SELECT condition_id"))
    assert copy_idx < select_idx
    copy_sql = sqls[copy_idx]
    for col in ("seo_title", "seo_description", "seo_summary", "seo_faqs", "seo_generated_at"):
        assert f"{col} = src.{col}" in copy_sql
    assert "seo_title IS NOT NULL" in copy_sql
    assert "a.seo_generated_at IS NULL" in copy_sql
