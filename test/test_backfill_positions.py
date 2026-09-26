"""
backfill_wallet_pnl used to wipe a wallet's open positions before
re-fetching them, so a failed /positions request left the wallet with no
open rows (reads as a brand-new wallet downstream). It must fetch first and
only replace the rows when the fetch succeeds.
"""

from unittest.mock import MagicMock, patch

import pytest

import db

# backfill.py calls load_dotenv() at import time; keep the test hermetic.
with patch("dotenv.load_dotenv"):
    import backfill

WALLET = "0xabc"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "polybot.db"))
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    yield db.get_db()
    if db._conn is not None:
        db._conn.close()


def _seed_open(n):
    for i in range(n):
        db.record_wallet_pnl(WALLET, {"conditionId": f"old_{i}", "asset": f"a{i}", "timestamp": 100 + i}, "open")


def _open_cids(conn):
    rows = conn.execute(
        "SELECT condition_id FROM wallet_pnl WHERE wallet = ? AND position_type = 'open' ORDER BY condition_id",
        (WALLET,),
    ).fetchall()
    return [r[0] for r in rows]


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_failed_open_fetch_keeps_existing_rows(fresh_db):
    _seed_open(3)
    with patch("requests.get", return_value=_resp(500, None)):
        backfill.backfill_wallet_pnl([{"proxyWallet": WALLET}])
    assert _open_cids(fresh_db) == ["old_0", "old_1", "old_2"]


def test_successful_open_fetch_replaces_rows(fresh_db):
    _seed_open(3)
    new_positions = [{"conditionId": "new_0", "asset": "n0"}, {"conditionId": "new_1", "asset": "n1"}]

    def fake_get(url, *a, **k):
        if url.endswith("/positions"):
            return _resp(200, new_positions)
        return _resp(200, [])  # closed-positions

    with patch("requests.get", side_effect=fake_get):
        backfill.backfill_wallet_pnl([{"proxyWallet": WALLET}])
    assert _open_cids(fresh_db) == ["new_0", "new_1"]
