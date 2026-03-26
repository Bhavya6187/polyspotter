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
    def test_base_severity_capped_at_3(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertLessEqual(result.severity, 3.0)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_thin_book_boosts_severity(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        trade["asset"] = "token_1"
        # Thin book: total depth $2000 < $5000 threshold, narrow spread
        with patch.object(self.strategy, "_fetch_orderbook", return_value={
            "bid_depth": 1000, "ask_depth": 1000, "spread": 0.01,
        }):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 3.5)
        self.assertIn("thin book", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_wide_spread_boosts_severity(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        trade["asset"] = "token_1"
        # Deep book but wide spread > 5%
        with patch.object(self.strategy, "_fetch_orderbook", return_value={
            "bid_depth": 5000, "ask_depth": 5000, "spread": 0.10,
        }):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 3.5)
        self.assertIn("wide spread", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_thin_book_and_wide_spread_severity_capped_at_4(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        trade["asset"] = "token_1"
        # Both: thin book AND wide spread
        with patch.object(self.strategy, "_fetch_orderbook", return_value={
            "bid_depth": 1000, "ask_depth": 1000, "spread": 0.10,
        }):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 4.0)
        self.assertIn("thin book", result.headline)
        self.assertIn("wide spread", result.headline)


    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_zero_volume_severity_2(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "0",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.0)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_orderbook_none_no_boost(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Base severity: (3000/1000)*0.5 = 1.5, capped at 3.0 → 1.5
        self.assertEqual(result.severity, 1.5)
        self.assertNotIn("thin book", result.headline)
        self.assertNotIn("wide spread", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_zero_liquidity_not_suppressed(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "0",
        }
        trade = self._make_trade(usd=100)
        result = self.strategy.check_trade(trade)
        # liquidity <= 0 so suppression check is skipped; is_low_volume=True (1000<5000)
        self.assertIsNotNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_long_lived_market_not_skipped(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "10000",
            "createdAt": "2024-01-01T00:00:00Z",
            "endDate": "2024-01-01T07:00:00Z",  # 7 hours >= SHORT_LIVED_MARKET_HOURS (6)
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_missing_volume_and_liquidity_keys(self, mock_market):
        # Market dict with no volume24hr or liquidity keys
        mock_market.return_value = {"question": "Some market?"}
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        # vol_24h defaults to 0 → is_low_volume=True, severity=2.0
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.0)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_malformed_dates_not_skipped(self, mock_market):
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "10000",
            "createdAt": "not-a-date",
            "endDate": "also-not-a-date",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        # ValueError is caught, trade proceeds normally
        self.assertIsNotNone(result)


    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_volume_exactly_5000_not_low(self, mock_market):
        # vol_24h == 5000 is NOT < 5000, so is_low_volume=False
        # usd=3000, vol=5000 → ratio=0.60 >= 0.50 → is_large_relative=True
        # liquidity=10000, usd=3000 → 3000/10000=0.30 >= 0.05, not suppressed
        mock_market.return_value = {
            "volume24hr": "5000",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # is_low_volume must be False — the low-volume part ("24h vol $N") should not be present
        self.assertNotIn("24h vol $", result.headline)
        # is_large_relative is True, so "of 24h vol" should appear
        self.assertIn("of 24h vol", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_ratio_exactly_50_pct_triggers(self, mock_market):
        # usd/vol_24h == 0.50 exactly → is_large_relative=True (>= 0.50)
        mock_market.return_value = {
            "volume24hr": "6000",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)  # 3000/6000 = 0.50
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("of 24h vol", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_liquidity_ratio_exactly_5_pct_not_suppressed(self, mock_market):
        # usd/liquidity == 0.05 exactly → NOT suppressed (suppression is strict < 0.05)
        # vol_24h=1000 < 5000 → is_low_volume=True
        mock_market.return_value = {
            "volume24hr": "1000",
            "liquidity": "60000",
        }
        trade = self._make_trade(usd=3000)  # 3000/60000 = 0.05
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_thin_book_exactly_5000_no_boost(self, mock_market):
        # total_depth == 5000 is NOT < 5000, so no thin book boost
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        trade["asset"] = "token_1"
        with patch.object(self.strategy, "_fetch_orderbook", return_value={
            "bid_depth": 2500, "ask_depth": 2500, "spread": 0.01,
        }):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Severity should be capped at 3.0 (no thin book boost applied)
        self.assertEqual(result.severity, 3.0)
        self.assertNotIn("thin book", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_spread_exactly_5_pct_no_boost(self, mock_market):
        # spread == 0.05 is NOT > 0.05, so no wide spread boost
        mock_market.return_value = {
            "volume24hr": "10",
            "liquidity": "100",
        }
        trade = self._make_trade(usd=50000)
        trade["asset"] = "token_1"
        with patch.object(self.strategy, "_fetch_orderbook", return_value={
            "bid_depth": 5000, "ask_depth": 5000, "spread": 0.05,
        }):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 3.0)
        self.assertNotIn("wide spread", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_severity_floor_with_low_volume(self, mock_market):
        # is_low_volume=True (vol=4999 < 5000), base calc: (500/4999)*0.5 ≈ 0.05 < 1.0
        # floor should bring severity up to 1.0.
        # liquidity=10000, usd=500 → 500/10000=0.05, which is NOT < 0.05, so not suppressed.
        mock_market.return_value = {
            "volume24hr": "4999",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=500)
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 1.0)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_start_date_fallback(self, mock_market):
        # Market has no createdAt but has startDate — should use startDate for lifespan calc
        # Market lifespan: 3 hours < SHORT_LIVED_MARKET_HOURS(6) → should be skipped
        mock_market.return_value = {
            "volume24hr": "100",
            "liquidity": "10000",
            "startDate": "2024-01-01T00:00:00Z",
            "endDate": "2024-01-01T03:00:00Z",
        }
        trade = self._make_trade(usd=3000)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_both_low_volume_and_large_relative(self, mock_market):
        # is_low_volume=True (vol=500 < 5000) AND is_large_relative=True (3000/500=6.0 >= 0.50)
        # Both indicators should appear in the headline
        mock_market.return_value = {
            "volume24hr": "500",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("24h vol", result.headline)
        self.assertIn("of 24h vol", result.headline)

    @patch("detection_strategies.low_activity_large_bet.get_market_by_condition")
    def test_infinity_headline_zero_volume(self, mock_market):
        # vol_24h=0 → ratio_str="∞", is_low_volume=True, is_large_relative=False
        # The infinity symbol should appear in the headline via the large_relative path,
        # but since is_large_relative requires vol_24h > 0, only is_low_volume fires.
        # With vol_24h=0 and is_low_volume=True, "∞" is computed but only included
        # if is_large_relative is also True — verify the "∞" string itself via ratio_str logic.
        # Actually: is_large_relative = vol_24h > 0 and ... = False when vol=0.
        # So headline only has "24h vol $0". Verify severity=2.0 (zero-volume path).
        mock_market.return_value = {
            "volume24hr": "0",
            "liquidity": "10000",
        }
        trade = self._make_trade(usd=3000)
        with patch.object(self.strategy, "_fetch_orderbook", return_value=None):
            result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.0)
        # ratio_str is computed as "∞" when vol=0; it appears in headline only if
        # is_large_relative is True, which requires vol>0 — so "∞" is NOT in headline.
        # The test verifies the zero-vol code path produces a valid signal with severity 2.0.
        self.assertIn("24h vol", result.headline)


if __name__ == "__main__":
    unittest.main()
