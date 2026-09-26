"""
Markets and events that resolve within SEO_MIN_DAYS_TO_END days get no SEO
generation (2026-09-26 cost review): 47% of alerted markets end within a day
of their first alert and 70% within three, while market pages drew 63
organic-search sessions in 30 days — the page is dead before it can be
indexed. Such rows are stamped seo_skip_reason='short_lived' before the
candidate select, so they leave the pool instead of being re-examined every
pass. Uses fake DB connections — no Postgres required.
"""

import seo_worker


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
        return {}


class FakeConn:
    def __init__(self):
        self.fetchall_results = [[]]
        self.executed = []
        self.autocommit = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


def _short_lived_marks(conn, table):
    return [
        (i, sql, params) for i, (sql, params) in enumerate(conn.executed)
        if sql.startswith(f"UPDATE {table}") and "'short_lived'" in sql
    ]


def test_threshold_is_three_days():
    assert seo_worker.SEO_MIN_DAYS_TO_END == 3


def test_short_lived_markets_are_skipped_before_candidate_select(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_market_seo()

    marks = _short_lived_marks(conn, "alerts")
    assert len(marks) == 1
    idx, sql, params = marks[0]
    assert "end_date" in sql
    assert "seo_generated_at IS NULL" in sql
    assert "seo_skip_reason IS NULL" in sql
    assert params == (seo_worker.SEO_MIN_DAYS_TO_END,)
    select_idx = next(i for i, (s, _) in enumerate(conn.executed) if s.startswith("SELECT condition_id"))
    assert idx < select_idx


def test_short_lived_events_are_skipped_before_candidate_select(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(seo_worker, "get_conn", lambda: conn)

    seo_worker.run_event_seo()

    marks = _short_lived_marks(conn, "events")
    assert len(marks) == 1
    idx, sql, params = marks[0]
    assert "end_date" in sql
    assert "seo_generated_at IS NULL" in sql
    assert "seo_skip_reason IS NULL" in sql
    assert params == (seo_worker.SEO_MIN_DAYS_TO_END,)
    select_idx = next(i for i, (s, _) in enumerate(conn.executed) if s.startswith("SELECT e.event_slug"))
    assert idx < select_idx
