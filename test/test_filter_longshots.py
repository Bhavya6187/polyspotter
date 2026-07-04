"""
Tests for the longshot entry-price floor (2026-07).

Both backtests (2026-06, 2026-07) graded flagged longshot entries as an
anti-signal: BUYs below 0.30 hit below market-implied odds (-29% avg copy
return; -61% below 0.10). SELLs at low prices are equivalent to buying the
other side at a high price and must NOT be dropped.
"""

import unittest

from polybot import LONGSHOT_PRICE_FLOOR, filter_longshots


def _trade(side, price):
    return {"side": side, "price": price, "title": "t", "_usd_value": 5000}


class TestFilterLongshots(unittest.TestCase):
    def test_buy_below_floor_dropped(self):
        self.assertEqual(filter_longshots([_trade("BUY", 0.29)]), [])
        self.assertEqual(filter_longshots([_trade("BUY", 0.05)]), [])

    def test_buy_at_or_above_floor_kept(self):
        kept = filter_longshots([_trade("BUY", 0.30), _trade("BUY", 0.65)])
        self.assertEqual(len(kept), 2)

    def test_sell_at_low_price_kept(self):
        # Selling Yes at 0.20 = buying No at 0.80 — not a longshot.
        kept = filter_longshots([_trade("SELL", 0.20)])
        self.assertEqual(len(kept), 1)

    def test_side_case_insensitive(self):
        self.assertEqual(filter_longshots([_trade("buy", 0.10)]), [])

    def test_missing_price_defaults_to_kept(self):
        kept = filter_longshots([{"side": "BUY", "title": "t"}])
        self.assertEqual(len(kept), 1)

    def test_floor_value(self):
        self.assertAlmostEqual(LONGSHOT_PRICE_FLOOR, 0.30)


if __name__ == "__main__":
    unittest.main()
