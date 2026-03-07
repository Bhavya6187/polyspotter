import unittest
from unittest.mock import patch

from detection_strategies.low_activity_large_bet import LowActivityLargeBetStrategy


class TestLowActivityLargeBetStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = LowActivityLargeBetStrategy()

    def _make_trade(self, cid="cond_1", usd=3000):
        return {
            "conditionId": cid,
            "_usd_value": usd,
            "transactionHash": "0xtx_1",
        }

    def test_no_condition_id_returns_none(self):
        trade = {"_usd_value": 5000}
        self.assertIsNone(self.strategy.check_trade(trade))

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_market_not_found_returns_none(self, mock_market):
        mock_market.return_value = None
        trade = self._make_trade()
        self.assertIsNone(self.strategy.check_trade(trade))

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_low_volume_market_triggers(self, mock_market):
        # volume24hr=1000 < 5000 threshold, and bet must be >= 5% of liquidity
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "low_activity_large_bet")

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_high_volume_market_no_signal(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "100000",
            "liquidity": "500000",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_large_relative_bet_triggers(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "4000",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("of 24h vol", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_tiny_bet_relative_to_liquidity_suppressed(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "1000000",
        }
        trade = self._make_trade(usd=100)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_short_lived_market_skipped(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "100",
            "liquidity": "1000",
            "createdAt": "2024-01-01T00:00:00Z",
            "endDate": "2024-01-01T04:00:00Z",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_severity_capped_at_3(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertLessEqual(result.severity, 3.0)


if __name__ == "__main__":
    unittest.main()
