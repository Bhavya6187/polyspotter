"""
Tests for the per-market-day LLM evaluation counters in db.py.

Backs the market-day evaluation cap (2026-07 backtest: LLM keep rate is flat
~82% regardless of how many times a market was already evaluated that day —
the marginal call adds nothing; a cap of 5/market/day cuts ~41% of GPT calls).
"""

import sqlite3
import unittest
from unittest.mock import patch

from db import get_market_eval_count, increment_market_eval_count


class TestMarketEvalCounters(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE llm_market_evals (
                condition_id TEXT NOT NULL,
                day TEXT NOT NULL,
                evals INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (condition_id, day)
            )
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @patch("db.get_db")
    def test_unknown_market_counts_zero(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self.assertEqual(get_market_eval_count("cond1", "2026-07-03"), 0)

    @patch("db.get_db")
    def test_increment_accumulates(self, mock_get_db):
        mock_get_db.return_value = self.conn
        increment_market_eval_count("cond1", "2026-07-03")
        self.assertEqual(get_market_eval_count("cond1", "2026-07-03"), 1)
        increment_market_eval_count("cond1", "2026-07-03")
        increment_market_eval_count("cond1", "2026-07-03")
        self.assertEqual(get_market_eval_count("cond1", "2026-07-03"), 3)

    @patch("db.get_db")
    def test_days_are_isolated(self, mock_get_db):
        mock_get_db.return_value = self.conn
        increment_market_eval_count("cond1", "2026-07-03")
        self.assertEqual(get_market_eval_count("cond1", "2026-07-04"), 0)

    @patch("db.get_db")
    def test_markets_are_isolated(self, mock_get_db):
        mock_get_db.return_value = self.conn
        increment_market_eval_count("cond1", "2026-07-03")
        self.assertEqual(get_market_eval_count("cond2", "2026-07-03"), 0)


if __name__ == "__main__":
    unittest.main()
