"""
Orderbook snapshot throttle must be keyed by token, not condition: the
second token of a condition was always dropped within the 10-minute window,
while get_orderbook_stats reads by token_id. The table also needs a token_id
index (get_orderbook_stats full-scanned ~764k rows).
"""

from datetime import datetime, timedelta, timezone

import pytest

import db

BIDS = [{"price": "0.40", "size": "100"}]
ASKS = [{"price": "0.42", "size": "100"}]


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "polybot.db"))
    monkeypatch.setattr(db, "_conn", None)
    yield db.get_db()
    if db._conn is not None:
        db._conn.close()


def _tokens(conn, cid="cond_C"):
    rows = conn.execute(
        "SELECT token_id FROM orderbook_snapshots WHERE condition_id = ? ORDER BY id", (cid,)
    ).fetchall()
    return [r[0] for r in rows]


def test_second_token_snapshot_not_throttled_by_first(fresh_db):
    db.record_orderbook_snapshot("cond_C", "tok_A", "Yes", BIDS, ASKS)
    db.record_orderbook_snapshot("cond_C", "tok_B", "No", BIDS, ASKS)

    assert _tokens(fresh_db) == ["tok_A", "tok_B"]
    assert db.get_orderbook_stats("tok_B") is not None


def test_same_token_snapshot_throttled_within_window(fresh_db):
    db.record_orderbook_snapshot("cond_C", "tok_A", "Yes", BIDS, ASKS)
    db.record_orderbook_snapshot("cond_C", "tok_A", "Yes", BIDS, ASKS)

    assert _tokens(fresh_db) == ["tok_A"]


def test_same_token_snapshot_recorded_after_window(fresh_db):
    db.record_orderbook_snapshot("cond_C", "tok_A", "Yes", BIDS, ASKS)
    old = (datetime.now(timezone.utc) - timedelta(seconds=db.ORDERBOOK_SNAPSHOT_MIN_INTERVAL_SEC + 1)).isoformat()
    fresh_db.execute("UPDATE orderbook_snapshots SET snapshot_at = ?", (old,))
    fresh_db.commit()

    db.record_orderbook_snapshot("cond_C", "tok_A", "Yes", BIDS, ASKS)

    assert _tokens(fresh_db) == ["tok_A", "tok_A"]


def test_orderbook_snapshot_index_exists(fresh_db):
    indexed_cols = set()
    for (name,) in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'orderbook_snapshots'"
    ):
        cols = [r[2] for r in fresh_db.execute(f"PRAGMA index_info({name})")]
        if cols and cols[0] in ("token_id", "condition_id") and "token_id" in cols:
            indexed_cols.update(cols)
    assert "token_id" in indexed_cols

    plan = " ".join(
        str(r[3]) for r in fresh_db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM orderbook_snapshots WHERE token_id = ? "
            "ORDER BY snapshot_at DESC LIMIT 1", ("tok_A",),
        )
    )
    assert "USING INDEX" in plan and "token_id" in plan
