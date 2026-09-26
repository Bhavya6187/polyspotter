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


def _fake_db(executed, market_rows):
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
                if "GROUP BY a.condition_id" in self.last:
                    return market_rows
                return []

        class FakeConn:
            def cursor(self):
                return FakeCur()

        yield FakeConn()
    return fake


def test_by_market_fetches_children_in_one_query_per_page(monkeypatch):
    market_rows = [
        {"condition_id": f"c{i}", "market_title": f"M{i}", "market_url": None,
         "market_image": None, "event_slug": None, "end_date": None,
         "total_usd": 1.0, "alert_count": 1, "max_score": 1.0,
         "scanned_at": None, "seo_title": None, "seo_description": None,
         "seo_summary": None, "seo_faqs": None}
        for i in range(10)
    ]
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
