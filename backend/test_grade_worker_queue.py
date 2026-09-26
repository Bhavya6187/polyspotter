"""
grade_worker must not get stuck behind markets it can never grade, and must
not grade a game that is still being played.

Production state at review time (2026-09-26): 39,109 markets waiting, 6,880
graded, 11 graded in the last 3 days. Candidates were taken in condition_id
order with no memory of failed attempts, so 50/50 voids, misspelled LLM
outcomes and team-name outcomes on Yes/No markets sat at the front of the
queue forever. Separately, a market was graded as soon as one outcome traded
at >= 0.98 -- which happens mid-game -- without checking Gamma's `closed`.
"""

from unittest.mock import MagicMock, patch

import grade_worker
from grade_worker import _grade_market, fetch_market, grade_once, MAX_GRADE_ATTEMPTS


class _FakeCursor:
    def __init__(self, candidate_rows=None, alert_rows_by_cid=None):
        self._candidate_rows = candidate_rows or []
        self._alert_rows_by_cid = alert_rows_by_cid or {}
        self.upserts = []
        self.attempts = []
        self.sql = []
        self._last = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sql.append((s, params))
        if s.startswith("SELECT a.condition_id"):
            self._last = self._candidate_rows
        elif s.startswith("SELECT id, composite_score"):
            self._last = self._alert_rows_by_cid[params[0]]
        elif s.startswith("INSERT INTO graded_calls"):
            self.upserts.append(params)
            self._last = []
        elif s.startswith("INSERT INTO grade_attempts"):
            self.attempts.append(params)
            self._last = []

    def fetchall(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


CID = "0xabc"
ALERTS = {CID: [
    {"id": 10, "composite_score": 14.0, "event_slug": "mlb-x", "market_title": "Padres vs Phillies",
     "llm_copy_action": '{"outcome": "San Diego Padres", "entry_price": 0.38}', "event_end_estimate": None},
]}


def _market(prices, closed):
    return {"outcomes": ["San Diego Padres", "Philadelphia Phillies"], "prices": prices, "closed": closed}


def test_closed_decided_market_is_graded():
    cur = _FakeCursor(alert_rows_by_cid=ALERTS)
    graded = _grade_market(_FakeConn(cur), CID, lambda cid: _market([0.99, 0.01], closed=True))
    assert graded is True
    assert len(cur.upserts) == 1
    assert cur.attempts == []


def test_in_progress_market_is_not_graded_even_at_extreme_price():
    cur = _FakeCursor(alert_rows_by_cid=ALERTS)
    graded = _grade_market(_FakeConn(cur), CID, lambda cid: _market([0.985, 0.015], closed=False))
    assert graded is False
    assert cur.upserts == []
    assert len(cur.attempts) == 1
    assert cur.attempts[0][0] == CID
    assert "closed" in cur.attempts[0][1]


def test_unresolved_market_records_an_attempt():
    cur = _FakeCursor(alert_rows_by_cid=ALERTS)
    graded = _grade_market(_FakeConn(cur), CID, lambda cid: _market([0.5, 0.5], closed=True))
    assert graded is False
    assert len(cur.attempts) == 1
    assert "unresolved" in cur.attempts[0][1]


def test_outcome_mismatch_records_an_attempt():
    alerts = {CID: [dict(ALERTS[CID][0], llm_copy_action='{"outcome": "Natus Vincente", "entry_price": 0.4}')]}
    cur = _FakeCursor(alert_rows_by_cid=alerts)
    graded = _grade_market(_FakeConn(cur), CID, lambda cid: _market([0.99, 0.01], closed=True))
    assert graded is False
    assert len(cur.attempts) == 1
    assert "outcome" in cur.attempts[0][1]


def test_fetch_failure_records_an_attempt():
    cur = _FakeCursor(alert_rows_by_cid=ALERTS)
    graded = _grade_market(_FakeConn(cur), CID, lambda cid: None)
    assert graded is False
    assert len(cur.attempts) == 1


def test_candidate_query_backs_off_and_prefers_recent_resolutions():
    cur = _FakeCursor(candidate_rows=[], alert_rows_by_cid={})
    grade_once(_FakeConn(cur), lambda cid: None)
    candidate_sql, params = next((s, p) for s, p in cur.sql if s.startswith("SELECT a.condition_id"))
    assert "grade_attempts" in candidate_sql
    assert MAX_GRADE_ATTEMPTS in params
    # newest-ended markets first so the scoreboard reflects recent calls
    assert "DESC" in candidate_sql.split("ORDER BY", 1)[1]
    assert "ORDER BY a.condition_id" not in candidate_sql


def test_fetch_market_returns_closed_flag():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]', "closed": True}]
    with patch.object(grade_worker.requests, "get", return_value=resp):
        m = fetch_market("0xabc")
    assert m["closed"] is True
    assert m["outcomes"] == ["Yes", "No"]


def test_fetch_market_defaults_closed_false_when_missing():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"outcomes": '["Yes","No"]', "outcomePrices": '["0.6","0.4"]'}]
    with patch.object(grade_worker.requests, "get", return_value=resp):
        m = fetch_market("0xabc")
    assert m["closed"] is False


def test_migration_creates_grade_attempts_table():
    from database import _migrate_add_grade_attempts

    cur = MagicMock()
    _migrate_add_grade_attempts(cur)
    executed = " ".join(" ".join(c.args[0].split()) for c in cur.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS grade_attempts" in executed
