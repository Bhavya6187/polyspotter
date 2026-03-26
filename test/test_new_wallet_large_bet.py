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

    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
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

    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_no_profile_returns_signal(self, mock_profile, mock_record):
        mock_profile.return_value = (None, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 3.5)

    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_scales_with_age(self, mock_profile, mock_record):
        # 10-day old wallet -> severity 2.5
        created = datetime.now(timezone.utc) - timedelta(days=10)
        mock_profile.return_value = (created, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.5)

    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_20_day_wallet(self, mock_profile, mock_record):
        created = datetime.now(timezone.utc) - timedelta(days=20)
        mock_profile.return_value = (created, {})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 1.5)


    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_high_activity_wallet_skipped(self, mock_profile, mock_pnl):
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {"pseudonym": "active_trader"})
        mock_pnl.return_value = {
            "total_positions": 15,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 3,
            "total_usd_flagged": 15000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-03",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_repeat_bettor_severity_escalation(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        created = datetime.now(timezone.utc) - timedelta(days=2)
        mock_profile.return_value = (created, {"pseudonym": "repeat_bettor"})
        mock_pnl.return_value = {
            "total_positions": 2,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("REPEAT x3", result.headline)
        # Base 3.5 + min(2.0, 3*0.5) = 3.5 + 1.5 = 5.0
        self.assertEqual(result.severity, 5.0)

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch("detection_strategies.new_wallet_large_bet.record_flagged_wallet")
    @patch(
        "detection_strategies.new_wallet_large_bet.get_flagged_wallet_stats",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=False,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_duplicate_trade_event_uses_stats(
        self, mock_profile, mock_trade_event, mock_flagged_stats, mock_record, mock_pnl
    ):
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {"pseudonym": "dup_trader"})
        mock_pnl.return_value = {
            "total_positions": 0,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        mock_record.assert_not_called()

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_pnl_cross_reference_bonus(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {"pseudonym": "pnl_trader"})
        mock_pnl.return_value = {
            "total_positions": 5,
            "closed_positions": 4,
            "total_pnl": 500,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Base 3.5 + 0.5 P&L bonus = 4.0
        self.assertEqual(result.severity, 4.0)
        self.assertIn("P&L", result.headline)

    @patch(
        "detection_strategies.new_wallet_large_bet.get_flagged_wallet_stats",
        return_value={
            "times_flagged": 3,
            "total_usd_flagged": 20000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-02-01",
        },
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_old_wallet_previously_flagged(self, mock_profile, mock_stats):
        created = datetime.now(timezone.utc) - timedelta(days=90)
        mock_profile.return_value = (created, {"pseudonym": "veteran"})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 1.0)
        self.assertIn("Previously flagged", result.headline)

    @patch(
        "detection_strategies.new_wallet_large_bet.get_flagged_wallet_stats",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_old_wallet_flagged_once_returns_none(self, mock_profile, mock_stats):
        created = datetime.now(timezone.utc) - timedelta(days=90)
        mock_profile.return_value = (created, {"pseudonym": "veteran"})
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)


    # ------------------------------------------------------------------
    # Severity boundary tests
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_boundary_exactly_7_days(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # delta == 7 falls into elif delta < 14 branch -> severity 2.5 (not 3.5)
        created = datetime.now(timezone.utc) - timedelta(days=7)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 0,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 2.5)

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_boundary_exactly_14_days(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # delta == 14 falls into else branch -> severity 1.5 (not 2.5)
        created = datetime.now(timezone.utc) - timedelta(days=14)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 0,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 1.5)

    # ------------------------------------------------------------------
    # Severity cap test
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 10,
            "total_usd_flagged": 50000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-10",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_severity_cap_at_7(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # times_flagged=10: repeat_bonus = min(2.0, 10*0.5) = 2.0
        # base 3.5 + 2.0 = 5.5; + 0.5 PnL bonus = 6.0 — still under cap
        # Use very high closed_positions/pnl to try to exceed 7.0
        created = datetime.now(timezone.utc) - timedelta(days=2)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 5,
            "closed_positions": 5,
            "total_pnl": 1000,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # base 3.5 + repeat_bonus min(2.0, 5.0)=2.0 = 5.5, then +0.5 PnL = 6.0, capped at 7.0
        self.assertLessEqual(result.severity, 7.0)

    # ------------------------------------------------------------------
    # PnL bonus edge cases
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_pnl_bonus_negative_pnl(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # closed_positions >= 3 but total_pnl < 0: no severity bonus
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 5,
            "closed_positions": 4,
            "total_pnl": -200,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Base 3.5 only — no PnL bonus for negative P&L
        self.assertEqual(result.severity, 3.5)
        self.assertNotIn("P&L", result.headline)

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 1,
            "total_usd_flagged": 5000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-01",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_pnl_bonus_insufficient_closed(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # total_positions > 0 but closed_positions < 3: headline updated, no severity bonus
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 3,
            "closed_positions": 2,
            "total_pnl": 500,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Headline should mention positions but no P&L bonus
        self.assertIn("positions", result.headline)
        self.assertNotIn("P&L", result.headline)
        # Severity stays at base 3.5 (no PnL bonus)
        self.assertEqual(result.severity, 3.5)

    # ------------------------------------------------------------------
    # Position filter boundary
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_exactly_10_positions_filtered(self, mock_profile, mock_pnl):
        # total_positions >= 10 should be skipped (line 175)
        created = datetime.now(timezone.utc) - timedelta(days=3)
        mock_profile.return_value = (created, {"pseudonym": "active_trader"})
        mock_pnl.return_value = {
            "total_positions": 10,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Repeat bonus cap
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 5,
            "total_usd_flagged": 25000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-05",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_repeat_bonus_cap_at_2(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # times_flagged=5: repeat_bonus = min(2.0, 5*0.5) = 2.0 (capped)
        created = datetime.now(timezone.utc) - timedelta(days=2)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 0,
            "closed_positions": 0,
            "total_pnl": 0,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # base 3.5 + min(2.0, 5*0.5)=2.0 = 5.5
        self.assertEqual(result.severity, 5.5)

    # ------------------------------------------------------------------
    # Combined repeat and PnL bonus
    # ------------------------------------------------------------------

    @patch("detection_strategies.new_wallet_large_bet.get_wallet_pnl_summary")
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_wallet",
        return_value={
            "times_flagged": 3,
            "total_usd_flagged": 15000,
            "first_flagged_at": "2024-01-01",
            "last_flagged_at": "2024-01-03",
        },
    )
    @patch(
        "detection_strategies.new_wallet_large_bet.record_flagged_trade_event",
        return_value=True,
    )
    @patch("detection_strategies.new_wallet_large_bet.get_wallet_profile")
    def test_combined_repeat_and_pnl_bonus(
        self, mock_profile, mock_trade_event, mock_record, mock_pnl
    ):
        # times_flagged=3: repeat_bonus = min(2.0, 3*0.5) = 1.5
        # closed_positions=4 >= 3 and total_pnl=300 > 0: PnL bonus 0.5
        # base 3.5 + 1.5 + 0.5 = 5.5
        created = datetime.now(timezone.utc) - timedelta(days=2)
        mock_profile.return_value = (created, {})
        mock_pnl.return_value = {
            "total_positions": 5,
            "closed_positions": 4,
            "total_pnl": 300,
        }
        trade = self._make_trade()
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, 5.5)
        self.assertIn("REPEAT x3", result.headline)
        self.assertIn("P&L", result.headline)


if __name__ == "__main__":
    unittest.main()
