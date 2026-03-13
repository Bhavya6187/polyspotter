import unittest
from unittest.mock import patch, MagicMock
import sqlite3

from db import (
    record_tracked_bet,
    get_wallet_stats,
)


class TestWinRateTrackingHelpers(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL
            )
        """)
        self.conn.execute("CREATE INDEX idx_tracked_wallet ON tracked_bets(wallet)")
        self.conn.execute("CREATE INDEX idx_tracked_unresolved ON tracked_bets(resolved)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _make_trade(self, wallet="0xwallet1", cid="cond_1", outcome="Yes", side="BUY", usd=5000):
        return {
            "proxyWallet": wallet,
            "conditionId": cid,
            "outcome": outcome,
            "side": side,
            "_usd_value": usd,
            "timestamp": 1700000000,
        }

    @patch("db.get_db")
    def test_record_trade_inserts(self, mock_get_db):
        mock_get_db.return_value = self.conn
        trade = self._make_trade()
        record_tracked_bet(trade)
        row = self.conn.execute("SELECT COUNT(*) FROM tracked_bets").fetchone()
        self.assertEqual(row[0], 1)

    @patch("db.get_db")
    def test_record_trade_no_wallet_skips(self, mock_get_db):
        mock_get_db.return_value = self.conn
        trade = self._make_trade(wallet="")
        record_tracked_bet(trade)
        row = self.conn.execute("SELECT COUNT(*) FROM tracked_bets").fetchone()
        self.assertEqual(row[0], 0)

    @patch("db.get_db")
    def test_get_wallet_stats_empty(self, mock_get_db):
        mock_get_db.return_value = self.conn
        stats = get_wallet_stats("0xnonexistent")
        self.assertEqual(stats["total_bets"], 0)
        self.assertEqual(stats["resolved_bets"], 0)
        self.assertEqual(stats["wins"], 0)

    @patch("db.get_db")
    def test_get_wallet_stats_with_data(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self.conn.execute("""
            INSERT INTO tracked_bets
            (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
            VALUES ('0xwallet1', 'c1', 'Yes', 'BUY', 5000, 1700000000, '2024-01-01', 1, 1)
        """)
        self.conn.execute("""
            INSERT INTO tracked_bets
            (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
            VALUES ('0xwallet1', 'c2', 'No', 'BUY', 3000, 1700001000, '2024-01-01', 1, 0)
        """)
        self.conn.execute("""
            INSERT INTO tracked_bets
            (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
            VALUES ('0xwallet1', 'c3', 'Yes', 'BUY', 2000, 1700002000, '2024-01-01', 0, NULL)
        """)
        self.conn.commit()

        stats = get_wallet_stats("0xwallet1")
        self.assertEqual(stats["total_bets"], 3)
        self.assertEqual(stats["resolved_bets"], 2)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["total_usd"], 10000.0)


class TestWinRateTrackingStrategy(unittest.TestCase):
    @patch("detection_strategies.win_rate_tracking._update_resolutions", return_value=0)
    @patch("db.get_db")
    def test_high_win_rate_triggers_signal(self, mock_get_db, mock_resolutions):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_tracked_wallet ON tracked_bets(wallet)")
        conn.execute("CREATE INDEX idx_tracked_unresolved ON tracked_bets(resolved)")
        conn.execute("""
            CREATE TABLE wallet_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT, condition_id TEXT, asset TEXT, outcome TEXT,
                avg_price REAL, total_bought REAL, realized_pnl REAL,
                cur_price REAL, event_slug TEXT, end_date TEXT,
                position_type TEXT, recorded_at TEXT
            )
        """)
        # Pre-populate with winning resolved bets (>= MIN_RESOLVED_BETS)
        for i in range(6):
            conn.execute(
                """
                INSERT INTO tracked_bets
                (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
                VALUES ('0xwallet1', ?, 'Yes', 'BUY', 5000, 1700000000, '2024-01-01', 1, 1)
            """,
                (f"cond_{i}",),
            )
        conn.commit()
        mock_get_db.return_value = conn

        from detection_strategies.win_rate_tracking import WinRateTrackingStrategy

        strategy = WinRateTrackingStrategy()

        trade = {
            "proxyWallet": "0xwallet1",
            "conditionId": "cond_new",
            "outcome": "Yes",
            "side": "BUY",
            "_usd_value": 5000,
            "timestamp": 1700010000,
        }
        result = strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "win_rate_tracking")

    @patch("detection_strategies.win_rate_tracking._update_resolutions", return_value=0)
    @patch("db.get_db")
    def test_low_win_rate_no_signal(self, mock_get_db, mock_resolutions):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_tracked_wallet ON tracked_bets(wallet)")
        conn.execute("CREATE INDEX idx_tracked_unresolved ON tracked_bets(resolved)")
        conn.execute("""
            CREATE TABLE wallet_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT, condition_id TEXT, asset TEXT, outcome TEXT,
                avg_price REAL, total_bought REAL, realized_pnl REAL,
                cur_price REAL, event_slug TEXT, end_date TEXT,
                position_type TEXT, recorded_at TEXT
            )
        """)
        # 1 win, 3 losses -> 25% win rate
        conn.execute("""
            INSERT INTO tracked_bets
            (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
            VALUES ('0xwallet1', 'c1', 'Yes', 'BUY', 5000, 1700000000, '2024-01-01', 1, 1)
        """)
        for i in range(3):
            conn.execute(
                """
                INSERT INTO tracked_bets
                (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
                VALUES ('0xwallet1', ?, 'Yes', 'BUY', 5000, 1700000000, '2024-01-01', 1, 0)
            """,
                (f"cond_loss_{i}",),
            )
        conn.commit()
        mock_get_db.return_value = conn

        from detection_strategies.win_rate_tracking import WinRateTrackingStrategy

        strategy = WinRateTrackingStrategy()

        trade = {
            "proxyWallet": "0xwallet1",
            "conditionId": "cond_new",
            "outcome": "Yes",
            "side": "BUY",
            "_usd_value": 5000,
            "timestamp": 1700010000,
        }
        result = strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.win_rate_tracking._update_resolutions", return_value=0)
    @patch("db.get_db")
    def test_too_few_resolved_no_signal(self, mock_get_db, mock_resolutions):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_tracked_wallet ON tracked_bets(wallet)")
        conn.execute("CREATE INDEX idx_tracked_unresolved ON tracked_bets(resolved)")
        conn.execute("""
            CREATE TABLE wallet_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT, condition_id TEXT, asset TEXT, outcome TEXT,
                avg_price REAL, total_bought REAL, realized_pnl REAL,
                cur_price REAL, event_slug TEXT, end_date TEXT,
                position_type TEXT, recorded_at TEXT
            )
        """)
        # Only 2 resolved (below threshold of 3)
        for i in range(2):
            conn.execute(
                """
                INSERT INTO tracked_bets
                (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won)
                VALUES ('0xwallet1', ?, 'Yes', 'BUY', 5000, 1700000000, '2024-01-01', 1, 1)
            """,
                (f"cond_{i}",),
            )
        conn.commit()
        mock_get_db.return_value = conn

        from detection_strategies.win_rate_tracking import WinRateTrackingStrategy

        strategy = WinRateTrackingStrategy()

        trade = {
            "proxyWallet": "0xwallet1",
            "conditionId": "cond_new",
            "outcome": "Yes",
            "side": "BUY",
            "_usd_value": 5000,
            "timestamp": 1700010000,
        }
        result = strategy.check_trade(trade)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
