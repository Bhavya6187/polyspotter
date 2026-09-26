"""
win_rate_tracking._update_resolutions must query Gamma with closed=true.

Gamma's /markets endpoint returns only active markets by default, so the
resolution check never saw a closed market and no tracked bet has resolved
since 2026-04 (1.29M unresolved rows). Every wallet then re-queried all of
its unresolved conditions on every scan (one wallet: ~114 Gamma calls/scan).
"""

import json
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import db
from detection_strategies import win_rate_tracking as wrt


def _gamma_side_effect(url, params=None, timeout=None):
    """Behave like Gamma: closed markets are only returned with closed=true."""
    params = params or []
    if isinstance(params, dict):
        params = list(params.items())
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    if ("closed", "true") in params:
        resp.json.return_value = [{
            "conditionId": "0xcond",
            "closed": True,
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["1", "0"]),
        }]
    else:
        resp.json.return_value = []
    return resp


class UpdateResolutionsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        db._init_tables(self.conn)
        self.conn.execute(
            """INSERT INTO tracked_bets
               (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved)
               VALUES ('0xw', '0xcond', 'Yes', 'BUY', 1500, 1000, '2026-09-01T00:00:00+00:00', 0)"""
        )
        self.conn.commit()
        wrt.reset_run_state()

    def tearDown(self):
        self.conn.close()

    @patch("detection_strategies.win_rate_tracking.time.sleep", lambda *_a, **_kw: None)
    @patch("detection_strategies.win_rate_tracking.requests.get", side_effect=_gamma_side_effect)
    @patch("db.get_db")
    def test_closed_market_resolves_the_bet(self, mock_get_db, _mock_get):
        mock_get_db.return_value = self.conn

        updated = wrt._update_resolutions("0xw")

        self.assertEqual(updated, 1)
        row = self.conn.execute(
            "SELECT resolved, won FROM tracked_bets WHERE condition_id = '0xcond'"
        ).fetchone()
        self.assertEqual(tuple(row), (1, 1))


if __name__ == "__main__":
    unittest.main()
