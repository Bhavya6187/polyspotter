import unittest

from polybot import _build_strategies


class TestStrategyRoster(unittest.TestCase):
    def test_timing_relative_resolution_not_active(self):
        # Deactivated 2026-06: backtest over 3.4k resolved markets showed it
        # ranked last in every view (-4.4% per-market avg return).
        _, _, all_strategies, names = _build_strategies()
        self.assertNotIn("timing_relative_resolution", names)
        self.assertNotIn(
            "timing_relative_resolution", [s.name for s in all_strategies]
        )

    def test_data_dependency_order_preserved(self):
        per_trade, batch, _, _ = _build_strategies()
        per_trade_names = [s.name for s in per_trade]
        batch_names = [s.name for s in batch]
        # win_rate_tracking writes wallet_pnl, which new_wallet_large_bet reads
        self.assertEqual(per_trade_names[0], "win_rate_tracking")
        self.assertIn("new_wallet_large_bet", per_trade_names)
        # wallet_clustering writes wallet_funders, concentrated_one_sided reads it
        self.assertLess(
            batch_names.index("wallet_clustering"),
            batch_names.index("concentrated_one_sided"),
        )
