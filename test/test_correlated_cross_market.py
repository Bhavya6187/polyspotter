import unittest
from unittest.mock import patch

from detection_strategies.correlated_cross_market import CorrelatedCrossMarketStrategy


@patch(
    "detection_strategies.correlated_cross_market.get_wallet_cross_event_stats",
    return_value={"distinct_events": 0, "distinct_markets": 0, "total_usd": 0, "total_trades": 0},
)
@patch("detection_strategies.correlated_cross_market.get_wallet_event_history", return_value=[])
@patch("detection_strategies.correlated_cross_market.record_wallet_event_trade")
class TestCorrelatedCrossMarketStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CorrelatedCrossMarketStrategy()

    def _make_trade(self, wallet, event_slug, cid, usd=1500, side="BUY"):
        return {
            "proxyWallet": wallet,
            "eventSlug": event_slug,
            "conditionId": cid,
            "_usd_value": usd,
            "side": side,
            "transactionHash": f"0xtx_{wallet}_{cid}",
        }

    def test_check_trade_always_none(self, *mocks):
        trade = self._make_trade("w1", "event1", "cond1")
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self, *mocks):
        self.assertEqual(self.strategy.analyze_all([]), [])

    def test_single_market_no_signal(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_two_markets_consistent_no_signal(self, *mocks):
        """2 markets, same direction (both BUY) = consistent view, no signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1500, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_two_markets_mixed_triggers(self, *mocks):
        """2 markets, mixed directions (BUY + SELL) = suspicious, triggers signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1500, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "correlated_cross_market")
        self.assertIn("mixed directions", signals[0].headline)

    def test_below_min_usd_no_signal(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=500),
            self._make_trade("w1", "event1", "cond2", usd=500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_events_separate(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500),
            self._make_trade("w1", "event2", "cond2", usd=1500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_wallets_separate(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500),
            self._make_trade("w2", "event1", "cond2", usd=1500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_three_markets_consistent_lower_severity(self, *mocks):
        """3+ markets consistent direction still triggers but at lower severity."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1000, side="BUY"),
            self._make_trade("w1", "event1", "cond3", usd=1000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 markets", signals[0].headline)
        self.assertIn("consistent bullish", signals[0].headline)
        self.assertEqual(signals[0].severity, 1.5)

    def test_three_markets_mixed_higher_severity(self, *mocks):
        """3 markets with mixed directions gets higher severity."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1000, side="SELL"),
            self._make_trade("w1", "event1", "cond3", usd=1000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("mixed directions", signals[0].headline)
        self.assertEqual(signals[0].severity, 3.0)

    def test_trade_hashes_collected(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1500, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 2)


if __name__ == "__main__":
    unittest.main()
