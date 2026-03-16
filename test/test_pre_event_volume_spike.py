import unittest
from unittest.mock import patch

from detection_strategies.pre_event_volume_spike import PreEventVolumeSpikeStrategy


@patch("detection_strategies.pre_event_volume_spike.get_average_volume", return_value=None)
@patch("detection_strategies.pre_event_volume_spike.record_volume_snapshot")
class TestPreEventVolumeSpikeStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = PreEventVolumeSpikeStrategy()

    def _make_trade(self, cid="cond_1", usd=1000, ts=1000):
        return {
            "conditionId": cid,
            "_usd_value": usd,
            "timestamp": ts,
            "transactionHash": f"0xtx_{ts}",
        }

    def test_check_trade_always_none(self, *mocks):
        trade = self._make_trade()
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self, *mocks):
        self.assertEqual(self.strategy.analyze_all([]), [])

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_spike_triggers_signal(self, mock_market, *mocks):
        mock_market.return_value = {"volume24hr": "100"}
        trades = [
            self._make_trade(usd=10000, ts=1000),
            self._make_trade(usd=10000, ts=1060),
            self._make_trade(usd=10000, ts=1120),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "pre_event_volume_spike")
        self.assertIn("spike", signals[0].headline.lower())

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_no_spike_no_signal(self, mock_market, *mocks):
        mock_market.return_value = {"volume24hr": "1000000"}
        trades = [
            self._make_trade(usd=100, ts=1000),
            self._make_trade(usd=100, ts=1060),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_zero_24h_volume_no_signal(self, mock_market, *mocks):
        mock_market.return_value = {"volume24hr": "0"}
        trades = [self._make_trade(usd=5000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_market_not_found_no_signal(self, mock_market, *mocks):
        mock_market.return_value = None
        trades = [self._make_trade(usd=5000)]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_severity_capped_at_3_without_historical(self, mock_market, *mocks):
        mock_market.return_value = {"volume24hr": "1"}
        trades = [
            self._make_trade(usd=100000, ts=1000),
            self._make_trade(usd=100000, ts=1060),
            self._make_trade(usd=100000, ts=1120),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # Without historical data, cap is 3.0
        self.assertEqual(signals[0].severity, 3.0)


    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_historical_baseline_requires_min_snapshots(self, mock_market, mock_record, mock_avg):
        """Historical baseline should only be used when snapshot count >= MIN_SNAPSHOTS_FOR_HISTORICAL."""
        mock_market.return_value = {"volume24hr": "100"}
        trades = [
            self._make_trade(usd=10000, ts=1000),
            self._make_trade(usd=10000, ts=1060),
            self._make_trade(usd=10000, ts=1120),
        ]

        # With only 1 snapshot, should fall back to 24h baseline
        mock_avg.return_value = (100.0, 1)
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("24h", signals[0].headline)

        # With only 2 snapshots, still fall back to 24h baseline
        mock_avg.return_value = (100.0, 2)
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("24h", signals[0].headline)

        # With 3+ snapshots, should use historical baseline
        mock_avg.return_value = (100.0, 3)
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("historical", signals[0].headline)


    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_historical_severity_capped_at_4(self, mock_market, mock_record, mock_avg):
        """When historical baseline is used, severity cap is 4.0 (not 3.0)."""
        mock_market.return_value = {"volume24hr": "100"}
        mock_avg.return_value = (1.0, 5)  # very low avg, enough snapshots
        trades = [
            self._make_trade(usd=10000, ts=1000),
            self._make_trade(usd=10000, ts=1060),
            self._make_trade(usd=10000, ts=1120),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # Historical baseline allows up to 4.0 severity
        self.assertLessEqual(signals[0].severity, 4.0)
        # The ratio is so large it would exceed 3.0 cap without historical
        self.assertGreater(signals[0].severity, 3.0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_double_spike_escalation(self, mock_market, mock_record, mock_avg):
        """When both historical and 24h baselines show a spike, severity gets +0.5 escalation."""
        mock_market.return_value = {"volume24hr": "50"}
        mock_avg.return_value = (50.0, 5)  # both baselines are low enough to trigger spike
        trades = [
            self._make_trade(usd=10000, ts=1000),
            self._make_trade(usd=10000, ts=1060),
            self._make_trade(usd=10000, ts=1120),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("historical", signals[0].headline)

        # Compute expected severity without escalation to verify bonus was applied
        # Window is 120s, normalised_avg = 50 * (120/86400), ratio = 30000 / normalised_avg
        # severity_base = log10(ratio), severity_with_bonus = severity_base + 0.5, capped at 4.0
        window_seconds = 120
        normalised_avg = 50.0 * (window_seconds / 86400)
        ratio = 30000 / normalised_avg
        import math
        base_severity = math.log10(ratio)
        # With escalation it should be base + 0.5 (capped at 4.0)
        expected = min(4.0, base_severity + 0.5)
        self.assertAlmostEqual(signals[0].severity, expected, places=2)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_min_trades_below_threshold_no_signal(self, mock_market, *mocks):
        """Fewer than MIN_TRADES_FOR_SPIKE trades should not produce a signal."""
        mock_market.return_value = {"volume24hr": "1"}
        # Only 2 trades (below MIN_TRADES_FOR_SPIKE=3)
        trades = [
            self._make_trade(usd=50000, ts=1000),
            self._make_trade(usd=50000, ts=1060),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_below_min_window_volume_no_signal(self, mock_market, *mocks):
        """Total window volume below MIN_WINDOW_VOLUME_USD should not produce a signal."""
        mock_market.return_value = {"volume24hr": "1"}  # massive ratio but low absolute volume
        trades = [
            self._make_trade(usd=8000, ts=1000),
            self._make_trade(usd=8000, ts=1060),
            self._make_trade(usd=8000, ts=1120),
        ]
        # Total = $24,000 which is below $25,000 threshold
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.pre_event_volume_spike.get_market_by_condition")
    def test_multiple_markets_separate_signals(self, mock_market, *mocks):
        """Trades from different conditionIds are evaluated independently."""
        def market_lookup(cid):
            if cid == "cond_spike":
                return {"volume24hr": "100"}  # low baseline -> spike
            elif cid == "cond_normal":
                return {"volume24hr": "100000000"}  # huge baseline -> no spike
            return None

        mock_market.side_effect = market_lookup

        trades = [
            # Market that should spike
            self._make_trade(cid="cond_spike", usd=10000, ts=1000),
            self._make_trade(cid="cond_spike", usd=10000, ts=1060),
            self._make_trade(cid="cond_spike", usd=10000, ts=1120),
            # Market that should NOT spike (volume24hr is enormous)
            self._make_trade(cid="cond_normal", usd=10000, ts=1000),
            self._make_trade(cid="cond_normal", usd=10000, ts=1060),
            self._make_trade(cid="cond_normal", usd=10000, ts=1120),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].condition_id, "cond_spike")


if __name__ == "__main__":
    unittest.main()
