"""DB-free tests for the /api/alerts/by-market query builders.

The by-market endpoint used to run one child-alert query per market row
(~55ms each, ~5s per page of 100). The children are now fetched with one
batched, per-group-capped statement per page. SQL is checked through the pure
builder helpers and a fake cursor, never a real database.
"""

from contextlib import contextmanager

import app as app_mod
from app import _by_market_children_query, _title_search_predicate
from fastapi.testclient import TestClient

client = TestClient(app_mod.app)


def test_by_market_child_query_is_single_statement():
    sql, params = _by_market_children_query(
        "condition_id", ["c1", "c2", "c3"], "a.composite_score >= %s", [2.0],
        cap=7, order_by="latest_trade_at DESC",
    )
    assert sql.count(";") == 0  # one statement
    assert "a.condition_id = ANY(%s)" in sql
    assert "row_number() OVER (PARTITION BY c.condition_id" in sql
    assert "rn <= %s" in sql
    assert params == [["c1", "c2", "c3"], 2.0, 7]


def test_by_market_child_query_rejects_unknown_key_column():
    import pytest
    with pytest.raises(ValueError):
        _by_market_children_query("wallet; DROP", ["x"], "TRUE", [], cap=1, order_by="rn")


def test_search_predicate_uses_trigram_operator():
    pred = _title_search_predicate()
    # `%` is doubled because psycopg2 treats a bare % as a placeholder.
    assert "%s <%% a.market_title" in pred
    assert "word_similarity" not in pred


def _fake_db(executed, market_rows, children=None):
    """`children` maps a child-batch key column ("condition_id" / "event_slug")
    to the rows that batch's statement returns, already in SQL order."""
    children = children or {}

    @contextmanager
    def fake():
        class FakeCur:
            last = ""

            def execute(self, sql, params=None):
                self.last = sql
                executed.append((sql, params))

            def fetchone(self):
                return {"cnt": len(market_rows), "alert_cnt": 0}

            def fetchall(self):
                if "row_number()" in self.last:
                    for col, rows in children.items():
                        if f"PARTITION BY c.{col}" in self.last:
                            return rows
                    return []
                if "GROUP BY a.condition_id" in self.last or "GROUP BY group_key" in self.last:
                    return market_rows
                return []

        class FakeConn:
            def cursor(self):
                return FakeCur()

        yield FakeConn()
    return fake


def _market_row(cid, *, alert_count=1, **extra):
    return {"condition_id": cid, "market_title": f"M-{cid}", "market_url": None,
            "market_image": None, "event_slug": None, "end_date": None,
            "total_usd": 1.0, "alert_count": alert_count, "max_score": 1.0,
            "scanned_at": None, "seo_title": None, "seo_description": None,
            "seo_summary": None, "seo_faqs": None, **extra}


def _child(alert_id, cid, event_slug=None, rn=1):
    return {"id": alert_id, "alert_type": "whale", "composite_score": 3.0,
            "tags": "[]", "condition_id": cid, "event_slug": event_slug,
            "total_usd": 1000.0, "trade_count": 1, "llm_bullets": "[]",
            "llm_copy_action": None, "latest_trade_at": None, "rn": rn}


def test_by_market_fetches_children_in_one_query_per_page(monkeypatch):
    market_rows = [_market_row(f"c{i}") for i in range(10)]
    executed = []
    monkeypatch.setattr(app_mod, "db", _fake_db(executed, market_rows))
    r = client.get("/api/alerts/by-market?per_page=10")
    assert r.status_code == 200
    assert len(r.json()["markets"]) == 10
    child = [(s, p) for s, p in executed if "row_number()" in s]
    assert len(child) == 1
    assert child[0][1][0] == [f"c{i}" for i in range(10)]


def test_by_market_search_sets_word_similarity_threshold(monkeypatch):
    """`<%` uses pg_trgm.word_similarity_threshold (default 0.6); the old
    predicate was `> 0.2`, so the threshold is set per transaction."""
    executed = []
    monkeypatch.setattr(app_mod, "db", _fake_db(executed, []))
    r = client.get("/api/alerts/by-market?q=lakers")
    assert r.status_code == 200
    assert any("SET LOCAL pg_trgm.word_similarity_threshold = 0.2" in s for s, _ in executed)
    assert not any("word_similarity(%s, a.market_title) > 0.2" in s for s, _ in executed)


def test_by_market_attaches_each_markets_children_in_order(monkeypatch):
    """Child rows come back in one statement ordered by (condition_id, rn);
    each market row must get only its own, in that order, and alert_count
    stays the group's full count rather than the embedded (capped) list."""
    market_rows = [_market_row("cA", alert_count=42), _market_row("cB", alert_count=7)]
    children = {"condition_id": [
        _child(11, "cA", rn=1), _child(12, "cA", rn=2), _child(21, "cB", rn=1),
    ]}
    executed = []
    monkeypatch.setattr(app_mod, "db", _fake_db(executed, market_rows, children))
    r = client.get("/api/alerts/by-market?per_page=10")
    assert r.status_code == 200
    by_cid = {m["condition_id"]: m for m in r.json()["markets"]}
    assert [a["id"] for a in by_cid["cA"]["alerts"]] == [11, 12]
    assert [a["id"] for a in by_cid["cB"]["alerts"]] == [21]
    assert by_cid["cA"]["alert_count"] == 42
    assert by_cid["cB"]["alert_count"] == 7
    # The per-market cap is enforced in SQL (rn <= %s) with MARKET_ALERTS_LIMIT.
    (child_params,) = [p for s, p in executed if "row_number()" in s]
    assert child_params[-1] == app_mod.MARKET_ALERTS_LIMIT


def test_by_market_group_events_attaches_event_and_market_children(monkeypatch):
    """group_events=true: event rows take children from the event_slug batch
    (capped at EVENT_ALERTS_LIMIT), standalone market rows from the
    condition_id batch."""
    market_rows = [
        _market_row("cE1", alert_count=9, event_slug="ev-1", is_event=True,
                    event_title="Event 1", event_image=None, market_count=2),
        _market_row("cS", alert_count=3, is_event=False, event_title=None,
                    event_image=None, market_count=1),
    ]
    children = {
        "event_slug": [_child(31, "cE1", "ev-1", rn=1), _child(32, "cE2", "ev-1", rn=2)],
        "condition_id": [_child(41, "cS", rn=1)],
    }
    executed = []
    monkeypatch.setattr(app_mod, "db", _fake_db(executed, market_rows, children))
    r = client.get("/api/alerts/by-market?per_page=10&group_events=true")
    assert r.status_code == 200
    markets = r.json()["markets"]
    event = next(m for m in markets if m["is_event"])
    solo = next(m for m in markets if not m["is_event"])
    assert [a["id"] for a in event["alerts"]] == [31, 32]
    assert [a["id"] for a in solo["alerts"]] == [41]
    assert event["alert_count"] == 9 and event["market_count"] == 2
    assert solo["alert_count"] == 3
    child_stmts = [(s, p) for s, p in executed if "row_number()" in s]
    assert len(child_stmts) == 2
    caps = {("event_slug" if "PARTITION BY c.event_slug" in s else "condition_id"): p[-1]
            for s, p in child_stmts}
    assert caps == {"event_slug": app_mod.EVENT_ALERTS_LIMIT,
                    "condition_id": app_mod.MARKET_ALERTS_LIMIT}
    assert [p[0] for s, p in child_stmts if "PARTITION BY c.event_slug" in s] == [["ev-1"]]
