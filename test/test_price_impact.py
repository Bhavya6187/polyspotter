import unittest
from unittest.mock import patch

from detection_strategies.price_impact import PriceImpactStrategy


@patch("detection_strategies.price_impact.get_historical_price_range", return_value=None)
@patch("detection_strategies.price_impact.record_price_observation")
class TestPriceImpactStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = PriceImpactStrategy()

    def _make_trade(self, cid="cond_1", outcome="Yes", price=0.50, ts=1000):
        return {
            "conditionId": cid,
            "outcome": outcome,
            "price": price,
            "timestamp": ts,
            "transactionHash": f"0xtx_{ts}",
        }

    def test_check_trade_always_none(self, *mocks):
        trade = self._make_trade()
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self, *mocks):
        self.assertEqual(self.strategy.analyze_all([]), [])

    def test_single_trade_no_signal(self, *mocks):
        trades = [self._make_trade(price=0.50, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_large_price_shift_up_triggers(self, *mocks):
        trades = [
            self._make_trade(price=0.30, ts=1000),
            self._make_trade(price=0.50, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("UP", signals[0].headline)

    def test_large_price_shift_down_triggers(self, *mocks):
        trades = [
            self._make_trade(price=0.60, ts=1000),
            self._make_trade(price=0.40, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("DOWN", signals[0].headline)

    def test_small_price_shift_no_signal(self, *mocks):
        trades = [
            self._make_trade(price=0.50, ts=1000),
            self._make_trade(price=0.55, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_tokens_tracked_separately(self, *mocks):
        trades = [
            self._make_trade(cid="c1", outcome="Yes", price=0.30, ts=1000),
            self._make_trade(cid="c1", outcome="Yes", price=0.50, ts=2000),
            self._make_trade(cid="c2", outcome="No", price=0.70, ts=1000),
            self._make_trade(cid="c2", outcome="No", price=0.72, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].condition_id, "c1")

    def test_severity_capped_at_3(self, *mocks):
        trades = [
            self._make_trade(price=0.10, ts=1000),
            self._make_trade(price=0.90, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertLessEqual(signals[0].severity, 3.0)

    def test_trade_hashes_collected(self, *mocks):
        trades = [
            self._make_trade(price=0.30, ts=1000),
            self._make_trade(price=0.50, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 2)


if __name__ == "__main__":
    unittest.main()
