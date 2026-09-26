"""
Retention for the two tables that account for 22 of polybot.db's 27 GB.

* price_candles: 27.1M rows, of which 24M were older than 30 days. Readers
  only ever look at the newest 100 candles per token (price_impact) or the
  last 24h (seeder), so anything older is dead weight.
* wallet_pnl: 15.3M rows across 45k wallets; 8.2M rows belonged to wallets
  not refreshed in 90 days. Pruning a wallet wholesale is safe because
  win_rate_tracking re-backfills a wallet with no cached rows the next time
  it trades (get_wallet_pnl_latest_timestamp -> None -> full fetch).
"""

import sqlite3
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import db


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class PrunePriceCandlesTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        db._init_tables(self.conn)
        now = time.time()
        rows = [
            ("c", "tokA", "Yes", now - 40 * 86400, 0.5),  # old
            ("c", "tokA", "Yes", now - 35 * 86400, 0.5),  # old
            ("c", "tokA", "Yes", now - 5 * 86400, 0.6),   # recent
            ("c", "tokA", "Yes", now - 60, 0.7),          # recent
        ]
        self.conn.executemany(
            "INSERT INTO price_candles (condition_id, token_id, outcome, t, p, recorded_at) VALUES (?,?,?,?,?,'x')",
            rows,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @patch("db.get_db")
    def test_deletes_only_rows_older_than_retention(self, mock_get_db):
        mock_get_db.return_value = self.conn
        deleted = db.prune_price_candles(max_age_days=30)
        self.assertEqual(deleted, 2)
        remaining = self.conn.execute("SELECT COUNT(*) FROM price_candles").fetchone()[0]
        self.assertEqual(remaining, 2)

    @patch("db.get_db")
    def test_batching_deletes_everything_eventually(self, mock_get_db):
        mock_get_db.return_value = self.conn
        deleted = db.prune_price_candles(max_age_days=30, batch_size=1)
        self.assertEqual(deleted, 2)

    @patch("db.get_db")
    def test_time_budget_stops_early_and_reports_partial_count(self, mock_get_db):
        mock_get_db.return_value = self.conn
        deleted = db.prune_price_candles(max_age_days=30, batch_size=1, time_budget_s=0)
        self.assertEqual(deleted, 1)  # one batch, then the budget is spent

    @patch("db.get_db")
    def test_nothing_to_delete_returns_zero(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self.assertEqual(db.prune_price_candles(max_age_days=365), 0)


class PruneStaleWalletPnlTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        db._init_tables(self.conn)
        rows = [
            # stale wallet: every row older than 90 days
            ("0xstale", "c1", "a1", "Yes", "closed", _iso(120)),
            ("0xstale", "c2", "a2", "Yes", "closed", _iso(100)),
            # active wallet: one old row, one fresh -> keep all of it
            ("0xactive", "c1", "a1", "Yes", "closed", _iso(120)),
            ("0xactive", "c3", "a3", "No", "open", _iso(1)),
        ]
        self.conn.executemany(
            """INSERT INTO wallet_pnl (wallet, condition_id, asset, outcome, position_type, recorded_at)
               VALUES (?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @patch("db.get_db")
    def test_removes_wallets_not_refreshed_within_retention(self, mock_get_db):
        mock_get_db.return_value = self.conn
        deleted = db.prune_stale_wallet_pnl(max_age_days=90)
        self.assertEqual(deleted, 2)
        wallets = {r[0] for r in self.conn.execute("SELECT DISTINCT wallet FROM wallet_pnl")}
        self.assertEqual(wallets, {"0xactive"})
        # the active wallet keeps its older rows too (whole-wallet semantics)
        n_active = self.conn.execute("SELECT COUNT(*) FROM wallet_pnl WHERE wallet='0xactive'").fetchone()[0]
        self.assertEqual(n_active, 2)


class DailyPruneHookTests(unittest.TestCase):
    """polybot.run() calls db.prune_old_rows() once per UTC day."""

    @patch("db.prune_stale_wallet_pnl", return_value=0)
    @patch("db.prune_price_candles", return_value=0)
    def test_runs_at_most_once_per_day(self, candles, pnl):
        db._last_prune_day = None
        with patch("db._today_utc", return_value="2026-09-26"):
            self.assertTrue(db.prune_old_rows())
            self.assertFalse(db.prune_old_rows())
        with patch("db._today_utc", return_value="2026-09-27"):
            self.assertTrue(db.prune_old_rows())
        self.assertEqual(candles.call_count, 2)
        self.assertEqual(pnl.call_count, 2)


if __name__ == "__main__":
    unittest.main()
