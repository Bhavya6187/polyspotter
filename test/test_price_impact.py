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


    # --- Historical breakout tests ---

    def test_historical_breakout_up_triggers(self, mock_record, mock_hist):
        """Price above historical max by >= 0.25 triggers historical signal."""
        mock_hist.return_value = (0.30, 0.40)
        trades = [self._make_trade(price=0.70, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("beyond historical range", signals[0].headline)
        self.assertIn("UP", signals[0].headline)
        self.assertLessEqual(signals[0].severity, 4.0)

    def test_historical_breakout_down_triggers(self, mock_record, mock_hist):
        """Price below historical min by >= 0.25 triggers historical signal."""
        mock_hist.return_value = (0.50, 0.70)
        trades = [self._make_trade(price=0.20, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("DOWN", signals[0].headline)

    def test_historical_breakout_below_threshold_no_signal(self, mock_record, mock_hist):
        """Breakout of 0.10 (< 0.25 threshold) should not trigger."""
        mock_hist.return_value = (0.40, 0.50)
        trades = [self._make_trade(price=0.60, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_historical_suppressed_when_window_signal_exists(self, mock_record, mock_hist):
        """If within-window signal fires, historical signal is suppressed."""
        mock_hist.return_value = (0.20, 0.30)
        trades = [
            self._make_trade(price=0.30, ts=1000),
            self._make_trade(price=0.70, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertNotIn("beyond historical range", signals[0].headline)

    def test_price_inside_historical_range_no_signal(self, mock_record, mock_hist):
        """Price inside historical range should not trigger."""
        mock_hist.return_value = (0.30, 0.70)
        trades = [self._make_trade(price=0.50, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    # --- Velocity detection tests ---

    @patch("detection_strategies.price_impact.get_orderbook_stats", return_value=None)
    @patch("detection_strategies.price_impact.get_price_candles", return_value=[(1000, 0.40), (1100, 0.42), (1200, 0.55)])
    @patch("detection_strategies.price_impact._fetch_orderbook")
    @patch("detection_strategies.price_impact._fetch_price_candles")
    def test_velocity_detection_triggers(self, mock_fetch_candles, mock_fetch_ob, mock_candles, mock_ob, mock_record, mock_hist):
        """Rapid price move in candles triggers velocity signal."""
        trade = self._make_trade(price=0.50, ts=1000)
        trade["asset"] = "token_1"
        signals = self.strategy.analyze_all([trade])
        self.assertEqual(len(signals), 1)
        self.assertIn("rapid price", signals[0].headline)

    @patch("detection_strategies.price_impact.get_orderbook_stats", return_value={"bid_depth": 1000, "ask_depth": 1000, "spread": 0.05})
    @patch("detection_strategies.price_impact.get_price_candles", return_value=[(1000, 0.40), (1100, 0.42), (1200, 0.55)])
    @patch("detection_strategies.price_impact._fetch_orderbook")
    @patch("detection_strategies.price_impact._fetch_price_candles")
    def test_velocity_thin_book_boost(self, mock_fetch_candles, mock_fetch_ob, mock_candles, mock_ob_stats, mock_record, mock_hist):
        """Thin orderbook boosts velocity signal severity."""
        trade = self._make_trade(price=0.50, ts=1000)
        trade["asset"] = "token_1"
        signals = self.strategy.analyze_all([trade])
        self.assertEqual(len(signals), 1)
        # Base severity for 0.13 move = 1.3, boosted by 1.0 = 2.3
        # Without boost it would be 1.3
        self.assertGreater(signals[0].severity, 1.3)


    # --- Grouping guard tests ---

    def test_missing_condition_id_skipped(self, *mocks):
        """Trade with empty conditionId should be excluded from grouping and produce no signal."""
        trades = [
            {"conditionId": "", "outcome": "Yes", "price": 0.30, "timestamp": 1000, "transactionHash": "0xtx_1"},
            {"conditionId": "", "outcome": "Yes", "price": 0.80, "timestamp": 2000, "transactionHash": "0xtx_2"},
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_missing_outcome_skipped(self, *mocks):
        """Trade with empty outcome should be excluded from grouping and produce no signal."""
        trades = [
            {"conditionId": "cond_1", "outcome": "", "price": 0.30, "timestamp": 1000, "transactionHash": "0xtx_1"},
            {"conditionId": "cond_1", "outcome": "", "price": 0.80, "timestamp": 2000, "transactionHash": "0xtx_2"},
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    # --- Price shift boundary tests ---

    def test_price_shift_exactly_at_threshold(self, *mocks):
        """Shift of exactly 0.15 (PRICE_SHIFT_THRESHOLD) should trigger a signal (boundary: >=)."""
        trades = [
            self._make_trade(price=0.50, ts=1000),
            self._make_trade(price=0.65, ts=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("UP", signals[0].headline)

    # --- Historical breakout with current_price=0 ---

    def test_current_price_zero_skipped_historical(self, mock_record, mock_hist):
        """current_price=0 should skip the historical breakout check entirely."""
        mock_hist.return_value = (0.30, 0.60)
        trades = [self._make_trade(price=0, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    # --- Historical breakout boundary test ---

    def test_historical_breakout_exactly_at_threshold(self, mock_record, mock_hist):
        """Breakout of exactly 0.25 should trigger a signal (boundary: >= HISTORICAL_SHIFT_THRESHOLD)."""
        # hist_max=0.40; current_price=0.65 → breakout=0.25 exactly
        mock_hist.return_value = (0.20, 0.40)
        trades = [self._make_trade(price=0.65, ts=1000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("beyond historical range", signals[0].headline)

    # --- transactionHash collection ---

    def test_missing_transaction_hash(self, *mocks):
        """Trades without transactionHash should not contribute to trade_hashes."""
        trades = [
            {"conditionId": "cond_1", "outcome": "Yes", "price": 0.30, "timestamp": 1000},
            {"conditionId": "cond_1", "outcome": "Yes", "price": 0.50, "timestamp": 2000, "transactionHash": "0xtx_2"},
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].trade_hashes, ["0xtx_2"])

    # --- Velocity detection: spread in headline and zero-velocity ---

    @patch("detection_strategies.price_impact.get_orderbook_stats", return_value={"bid_depth": 100, "ask_depth": 100, "spread": 0.03})
    @patch("detection_strategies.price_impact.get_price_candles", return_value=[(1000, 0.40), (1100, 0.42), (1200, 0.55)])
    @patch("detection_strategies.price_impact._fetch_orderbook")
    @patch("detection_strategies.price_impact._fetch_price_candles")
    def test_orderbook_spread_in_velocity_headline(self, mock_fetch_candles, mock_fetch_ob, mock_candles, mock_ob_stats, mock_record, mock_hist):
        """When orderbook spread > 0, the velocity signal headline should include spread info."""
        trade = self._make_trade(price=0.50, ts=1000)
        trade["asset"] = "token_1"
        signals = self.strategy.analyze_all([trade])
        self.assertEqual(len(signals), 1)
        self.assertIn("spread", signals[0].headline)

    @patch("detection_strategies.price_impact.get_orderbook_stats", return_value=None)
    @patch("detection_strategies.price_impact.get_price_candles", return_value=[(1000, 0.50), (1100, 0.50), (1200, 0.50)])
    @patch("detection_strategies.price_impact._fetch_orderbook")
    @patch("detection_strategies.price_impact._fetch_price_candles")
    def test_velocity_zero_no_signal(self, mock_fetch_candles, mock_fetch_ob, mock_candles, mock_ob_stats, mock_record, mock_hist):
        """Consecutive candles with identical prices (velocity=0) should not trigger a velocity signal."""
        trade = self._make_trade(price=0.50, ts=1000)
        trade["asset"] = "token_1"
        signals = self.strategy.analyze_all([trade])
        self.assertEqual(len(signals), 0)


if __name__ == "__main__":
    unittest.main()
