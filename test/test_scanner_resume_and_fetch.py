"""
Tests for the continuous-mode scan cursor and the trade fetch loop.

Regressions covered (2026-09 repo review):

* After downtime the scanner resumed from the last trade timestamp with no
  cap, so a week-long gap replayed the whole backlog (11k trades, hours of
  Gamma lookups, week-old trades pushed as fresh alerts).
* Any scan that ended with no trades (API failure, everything filtered) or
  raised wrote a NULL cursor, and the next iteration fell back to a full
  24h rescan (40 occurrences in scan_runs, 60-108 minutes each).
* The Data API paginator never stopped early, so every iteration walked all
  11 pages (offset cap 10,000) even for a 15-minute window.
* A failed push to the backend still advanced the cursor, silently losing
  every alert outside the 10-minute overlap.
"""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import db
import polybot


class ResumeSinceTsTests(unittest.TestCase):
    def test_no_history_returns_none(self):
        self.assertIsNone(polybot.resume_since_ts(None, now=1_000_000.0))

    def test_recent_cursor_applies_overlap(self):
        now = 1_000_000.0
        last_ts = now - 300  # last trade 5 minutes ago
        self.assertEqual(
            polybot.resume_since_ts(last_ts, now=now),
            last_ts - polybot.OVERLAP_SECONDS,
        )

    def test_long_downtime_is_clamped(self):
        now = 1_000_000.0
        last_ts = now - 7 * 86400  # a week of downtime
        self.assertEqual(
            polybot.resume_since_ts(last_ts, now=now),
            now - polybot.MAX_RESUME_LOOKBACK_SECONDS,
        )

    def test_clamp_is_at_least_the_overlap(self):
        # Sanity: the clamp must never be tighter than the normal overlap,
        # otherwise a healthy loop would lose trades between iterations.
        self.assertGreaterEqual(polybot.MAX_RESUME_LOOKBACK_SECONDS, polybot.OVERLAP_SECONDS)


def _page(*timestamps):
    return [
        {"timestamp": ts, "size": "10", "price": "0.5", "transactionHash": f"0x{ts}"}
        for ts in timestamps
    ]


def _resp(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class FetchRecentTradesPaginationTests(unittest.TestCase):
    @patch("polybot.time.sleep", lambda *_a, **_kw: None)
    @patch("polybot.requests.get")
    def test_stops_once_a_page_reaches_past_the_cutoff(self, mock_get):
        cutoff = 900.0
        mock_get.side_effect = [
            _resp(_page(1000, 950)),   # all newer than cutoff -> keep paging
            _resp(_page(890, 880)),    # older than cutoff -> nothing further can match
            _resp(_page(870)),         # must never be requested
        ]

        trades = polybot.fetch_recent_trades(since_ts=cutoff)

        self.assertEqual([t["timestamp"] for t in trades], [1000, 950])
        self.assertEqual(mock_get.call_count, 2)

    @patch("polybot.time.sleep", lambda *_a, **_kw: None)
    @patch("polybot.requests.get")
    def test_partial_page_keeps_the_matching_trades(self, mock_get):
        cutoff = 900.0
        mock_get.side_effect = [
            _resp(_page(1000, 950, 890)),  # straddles the cutoff
            _resp(_page(870)),
        ]

        trades = polybot.fetch_recent_trades(since_ts=cutoff)

        self.assertEqual([t["timestamp"] for t in trades], [1000, 950])
        self.assertEqual(mock_get.call_count, 1)


class LastScanCursorTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        db._init_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def _insert_run(self, finished: bool, latest_trade_ts):
        self.conn.execute(
            "INSERT INTO scan_runs (started_at, finished_at, latest_trade_ts) VALUES (?, ?, ?)",
            ("2026-09-26T00:00:00+00:00", "2026-09-26T00:05:00+00:00" if finished else None, latest_trade_ts),
        )
        self.conn.commit()

    @patch("db.get_db")
    def test_skips_finished_runs_without_a_cursor(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self._insert_run(finished=True, latest_trade_ts=100.0)
        self._insert_run(finished=True, latest_trade_ts=None)  # empty / errored scan

        self.assertEqual(db.get_last_scan_trade_ts(), 100.0)

    @patch("db.get_db")
    def test_ignores_unfinished_runs(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self._insert_run(finished=True, latest_trade_ts=100.0)
        self._insert_run(finished=False, latest_trade_ts=200.0)

        self.assertEqual(db.get_last_scan_trade_ts(), 100.0)

    @patch("db.get_db")
    def test_none_when_no_cursor_exists(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self._insert_run(finished=True, latest_trade_ts=None)

        self.assertIsNone(db.get_last_scan_trade_ts())


class ScanOncePushFailureTests(unittest.TestCase):
    """A failed backend push must not advance the cursor."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        db._init_tables(self.conn)
        self.trade = {
            "timestamp": 1_000_000,
            "conditionId": "0xcond",
            "proxyWallet": "0xwallet",
            "transactionHash": "0xtx",
            "title": "Test market",
            "outcome": "Yes",
            "side": "BUY",
            "size": "2000",
            "price": "0.5",
            "_usd_value": 1000.0,
        }

    def tearDown(self):
        self.conn.close()

    def _run_scan(self, push_result):
        identity = lambda trades: trades  # noqa: E731
        with patch("db.get_db", return_value=self.conn), \
             patch("polybot.fetch_recent_trades", return_value=[self.trade]), \
             patch("polybot.filter_short_markets", identity), \
             patch("polybot.filter_resolved_markets", identity), \
             patch("polybot.filter_extreme_odds", identity), \
             patch("polybot.filter_longshots", identity), \
             patch("polybot.push_to_backend", return_value=push_result), \
             patch("polybot._format_composite_alerts", return_value=""), \
             patch("polybot._format_summary", return_value=""):
            return polybot.scan_once([], [], [], "", since_ts=999_000.0)

    def _last_run(self):
        return self.conn.execute(
            "SELECT latest_trade_ts, error, alerts_pushed FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def test_successful_push_records_cursor(self):
        result = self._run_scan(push_result=3)
        latest_ts, error, pushed = self._last_run()
        self.assertEqual(result, 1_000_000)
        self.assertEqual(latest_ts, 1_000_000)
        self.assertIsNone(error)
        self.assertEqual(pushed, 3)

    def test_failed_push_leaves_cursor_unset(self):
        result = self._run_scan(push_result=None)
        latest_ts, error, pushed = self._last_run()
        self.assertIsNone(result)
        self.assertIsNone(latest_ts)
        self.assertIn("push", (error or "").lower())
        self.assertEqual(pushed, 0)


if __name__ == "__main__":
    unittest.main()
