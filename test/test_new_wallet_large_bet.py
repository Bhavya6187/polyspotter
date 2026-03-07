import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from detection_strategies.new_wallet_large_bet import (
    NewWalletLargeBetStrategy,
    is_new_wallet,
    wallet_age_str,
    _wallet_cache,
)


class TestIsNewWallet(unittest.TestCase):
    def test_none_created_at_is_new(self):
        self.assertTrue(is_new_wallet(None))

    def test_recent_wallet_is_new(self):
        created = datetime.now(timezone.utc) - timedelta(days=5)
        self.assertTrue(is_new_wallet(created))

    def test_old_wallet_is_not_new(self):
        created = datetime.now(timezone.utc) - timedelta(days=60)
        self.assertFalse(is_new_wallet(created))

    def test_boundary_exactly_30_days(self):
        # Exactly 30 days ago has some sub-second drift, so use >= check.
        # The implementation uses created_at >= cutoff, but datetime.now()
        # is called separately, so 30 days ago is slightly before cutoff.
        created = datetime.now(timezone.utc) - timedelta(days=30)
        self.assertFalse(is_new_wallet(created))

    def test_just_over_30_days(self):
        created = datetime.now(timezone.utc) - timedelta(days=31)
        self.assertFalse(is_new_wallet(created))


class TestWalletAgeStr(unittest.TestCase):
    def test_none_returns_unknown(self):
        self.assertEqual(wallet_age_str(None), "unknown (no profile)")

    def test_days_and_hours(self):
        created = datetime.now(timezone.utc) - timedelta(days=4, hours=22)
        result = wallet_age_str(created)
        self.assertIn("4d", result)

    def test_hours_only(self):
        created = datetime.now(timezone.utc) - timedelta(hours=3, minutes=15)
        result = wallet_age_str(created)
        self.assertIn("3h", result)


class TestNewWalletLargeBetStrategy(unittest.TestCase):
    def setUp(self):
        _wallet_cache.clear()
        self.strategy = NewWalletLargeBetStrategy()

    def _make_trade(self, wallet="0xabc123def456abc123def456abc123def456abcd", usd=5000):
        return {
            "proxyWallet": wallet,
            "_usd_value": usd,
            "title": "Test Market",
            "conditionId": "cond_1",
            "size": 100,
            "price": 0.5,
            "timestamp": 1700000000,
        }

    def test_no_wallet_returns_none(self):
        trade = self._make_trade(wallet="")
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.new_wallet_large_bet.record_flagged_wallet",
           return_value={"times_flagged": 1, "total_usd_flagged": 5000,
                         "first_flagged_at": "2024-01-01", "last_flagged_at": "2024-01-01"})
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_new_wallet_returns_signal(self, mock_profile, mock_record):
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {"pseudonym": "anon"})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "new_wallet_large_bet")
        self.assertEqual(result.severity, 3.5)

    @patch("detection_strategies.new_wallet_large_bet.get_flagged_wallet_stats", return_value=None)
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_old_wallet_returns_none(self, mock_profile, mock_stats):
        created = datetime.now(timezone.utc) - timedelta(days=90)
        mock_profile.return_value = (created, {"pseudonym": "veteran"})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.new_wallet_large_bet.record_flagged_wallet",
           return_value={"times_flagged": 1, "total_usd_flagged": 5000,
                         "first_flagged_at": "2024-01-01", "last_flagged_at": "2024-01-01"})
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_no_profile_returns_signal(self, mock_profile, mock_record):
        mock_profile.return_value = (None, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 3.5)

    @patch("detection_strategies.new_wallet_large_bet.record_flagged_wallet",
           return_value={"times_flagged": 1, "total_usd_flagged": 5000,
                         "first_flagged_at": "2024-01-01", "last_flagged_at": "2024-01-01"})
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_scales_with_age(self, mock_profile, mock_record):
        # 10-day old wallet -> severity 2.5
        created = datetime.now(timezone.utc) - timedelta(days=10)
        mock_profile.return_value = (created, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.5)

    @patch("detection_strategies.new_wallet_large_bet.record_flagged_wallet",
           return_value={"times_flagged": 1, "total_usd_flagged": 5000,
                         "first_flagged_at": "2024-01-01", "last_flagged_at": "2024-01-01"})
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_20_day_wallet(self, mock_profile, mock_record):
        created = datetime.now(timezone.utc) - timedelta(days=20)
        mock_profile.return_value = (created, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 1.5)


if __name__ == "__main__":
    unittest.main()
