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
        ]
        signals = self.strategy.analyze_all(trades)
        if signals:
            # Without historical data, cap is 3.0
            self.assertLessEqual(signals[0].severity, 3.0)


if __name__ == "__main__":
    unittest.main()
