import unittest
from unittest.mock import patch

from detection_strategies.correlated_cross_market import CorrelatedCrossMarketStrategy


@patch(
    "detection_strategies.correlated_cross_market.get_wallet_cross_event_stats",
    return_value={"distinct_events": 0, "distinct_markets": 0, "total_usd": 0, "total_trades": 0},
)
@patch("detection_strategies.correlated_cross_market.get_wallet_event_history", return_value=[])
@patch("detection_strategies.correlated_cross_market.record_wallet_event_trade")
@patch("detection_strategies.correlated_cross_market.is_sport_market", return_value=False)
@patch("detection_strategies.correlated_cross_market.get_market_by_condition", return_value=None)
class TestCorrelatedCrossMarketStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CorrelatedCrossMarketStrategy()

    def _make_trade(self, wallet, event_slug, cid, usd=1500, side="BUY", price=0.50):
        return {
            "proxyWallet": wallet,
            "eventSlug": event_slug,
            "conditionId": cid,
            "_usd_value": usd,
            "side": side,
            "price": price,
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

    def test_two_markets_below_min_usd_no_signal(self, *mocks):
        """2 markets but combined USD below MIN_TOTAL_USD = no signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=1500, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_two_markets_above_min_usd_triggers(self, *mocks):
        """2 markets with combined USD >= MIN_TOTAL_USD triggers signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "correlated_cross_market")
        self.assertIn("2 markets", signals[0].headline)

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

    def test_three_markets_triggers(self, *mocks):
        """3 markets above threshold triggers signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond3", usd=2000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 markets", signals[0].headline)
        self.assertEqual(signals[0].severity, 1.0)

    def test_high_usd_higher_severity(self, *mocks):
        """Higher combined USD produces higher severity."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=15000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=15000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 3.0)

    def test_trade_hashes_collected(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 2)

    def test_resolved_price_trades_filtered(self, *mocks):
        """Trades at near-certain prices (>= 0.98) should be excluded."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY", price=0.99),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL", price=0.99),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_sports_event_needs_three_markets(
        self, mock_get_mkt, mock_is_sport, *mocks
    ):
        """Sports events require 3 markets, not 2."""
        mock_get_mkt.return_value = {"id": "123"}
        mock_is_sport.return_value = True
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        # 2 markets on a sport event = no signal
        self.assertEqual(len(signals), 0)

    def test_sports_event_three_markets_triggers(
        self, mock_get_mkt, mock_is_sport, *mocks
    ):
        """Sports events with 3+ markets should trigger."""
        mock_get_mkt.return_value = {"id": "123"}
        mock_is_sport.return_value = True
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond3", usd=2000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 markets", signals[0].headline)

    def test_serial_severity_scales_by_win_rate(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market severity should scale with win rate, not flat 4.0."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
        ]
        # With no win rate data (default mock), serial severity should be 1.5
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 0, "wins": 0, "total_pnl": 0, "total_invested": 0},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 1)
            self.assertEqual(serial_sigs[0].severity, 1.5)

    def test_serial_severity_high_win_rate(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market with 75% win rate should get severity 4.0."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 20, "wins": 15, "total_pnl": 5000, "total_invested": 10000},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 1)
            self.assertEqual(serial_sigs[0].severity, 4.0)

    def test_win_rate_boost_requires_ten_closed(self, *mocks):
        """Win rate boost should require 10+ closed positions, not just 5."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        # 7 closed positions with 100% win rate — should NOT get boost
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 7, "wins": 7, "total_pnl": 5000, "total_invested": 3000},
        ):
            signals = self.strategy.analyze_all(trades)
            self.assertEqual(len(signals), 1)
            # Base severity for $6k is 1.0, no boost
            self.assertEqual(signals[0].severity, 1.0)


if __name__ == "__main__":
    unittest.main()
