import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from detection_strategies.timing_relative_resolution import TimingRelativeResolutionStrategy


@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_timing_stats",
    return_value={"total_flags": 0, "distinct_markets": 0, "avg_minutes": 0, "min_minutes": 0, "total_usd": 0},
)
@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
class TestTimingRelativeResolutionStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    def _make_trade(self, cid="cond_1", ts=1700000000):
        return {
            "conditionId": cid,
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": ts,
        }

    def test_no_condition_id_returns_none(self, *mocks):
        trade = {"_usd_value": 5000, "timestamp": 1700000000}
        self.assertIsNone(self.strategy.check_trade(trade))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_market_not_found_returns_none(self, mock_market, *mocks):
        mock_market.return_value = None
        self.assertIsNone(self.strategy.check_trade(self._make_trade()))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_no_end_date_returns_none(self, mock_market, *mocks):
        mock_market.return_value = {"endDate": None}
        self.assertIsNone(self.strategy.check_trade(self._make_trade()))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_close_to_resolution_triggers(self, mock_market, *mocks):
        trade_ts = 1700000000
        # End date 10 minutes after trade
        end_dt = datetime.fromtimestamp(trade_ts + 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "timing_relative_resolution")
        self.assertIn("min before resolution", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_far_from_resolution_no_signal(self, mock_market, *mocks):
        trade_ts = 1700000000
        # End date 2 hours after trade
        end_dt = datetime.fromtimestamp(trade_ts + 7200, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_after_resolution_no_signal(self, mock_market, *mocks):
        trade_ts = 1700000000
        # End date before trade
        end_dt = datetime.fromtimestamp(trade_ts - 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_severity_higher_when_closer(self, mock_market, *mocks):
        trade_ts = 1700000000
        # 1 minute before resolution
        end_1min = datetime.fromtimestamp(trade_ts + 60, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_1min.isoformat()}
        result_close = self.strategy.check_trade(self._make_trade(ts=trade_ts))

        # 50 minutes before resolution
        end_50min = datetime.fromtimestamp(trade_ts + 3000, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_50min.isoformat()}
        result_far = self.strategy.check_trade(self._make_trade(ts=trade_ts))

        self.assertGreater(result_close.severity, result_far.severity)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_severity_capped_at_5(self, mock_market, *mocks):
        trade_ts = 1700000000
        # 0 minutes before resolution
        end_dt = datetime.fromtimestamp(trade_ts, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        result = self.strategy.check_trade(self._make_trade(ts=trade_ts))
        self.assertIsNotNone(result)
        self.assertLessEqual(result.severity, 5.0)


if __name__ == "__main__":
    unittest.main()
