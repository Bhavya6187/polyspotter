import math
import unittest
from unittest.mock import patch

from detection_strategies.concentrated_one_sided import ConcentratedOneSidedStrategy


class TestConcentratedOneSidedStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = ConcentratedOneSidedStrategy()

    def _make_trade(self, wallet, cid="cond_1", outcome="Yes", side="BUY", usd=2000, price=0.50):
        return {
            "proxyWallet": wallet,
            "conditionId": cid,
            "outcome": outcome,
            "side": side,
            "_usd_value": usd,
            "price": price,
            "transactionHash": f"0xtx_{wallet}",
        }

    def test_check_trade_always_none(self):
        trade = self._make_trade("wallet_1")
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self):
        self.assertEqual(self.strategy.analyze_all([]), [])

    def test_below_min_wallets_no_signal(self):
        trades = [
            self._make_trade("wallet_1"),
            self._make_trade("wallet_2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_three_wallets_same_side_triggers(self):
        trades = [
            self._make_trade("wallet_1", usd=2000),
            self._make_trade("wallet_2", usd=2000),
            self._make_trade("wallet_3", usd=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "concentrated_one_sided")
        self.assertIn("3 wallets", signals[0].headline)

    def test_below_min_usd_no_signal(self):
        trades = [
            self._make_trade("wallet_1", usd=100),
            self._make_trade("wallet_2", usd=100),
            self._make_trade("wallet_3", usd=100),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_sides_not_grouped(self):
        trades = [
            self._make_trade("wallet_1", side="BUY", usd=2000),
            self._make_trade("wallet_2", side="SELL", usd=2000),
            self._make_trade("wallet_3", side="BUY", usd=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_markets_separate_clusters(self):
        trades = [
            self._make_trade("wallet_1", cid="cond_1", usd=2000),
            self._make_trade("wallet_2", cid="cond_1", usd=2000),
            self._make_trade("wallet_3", cid="cond_1", usd=2000),
            self._make_trade("wallet_4", cid="cond_2", usd=2000),
            self._make_trade("wallet_5", cid="cond_2", usd=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].condition_id, "cond_1")

    def test_same_wallet_multiple_trades_counts_once(self):
        trades = [
            self._make_trade("wallet_1", usd=2000),
            self._make_trade("wallet_1", usd=2000),
            self._make_trade("wallet_2", usd=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_trade_hashes_collected(self):
        trades = [
            self._make_trade("wallet_1", usd=2000),
            self._make_trade("wallet_2", usd=2000),
            self._make_trade("wallet_3", usd=2000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 3)


    @patch("detection_strategies.concentrated_one_sided.get_market_by_condition")
    def test_heavy_favorite_high_volume_suppressed(self, mock_market):
        """Buying a heavy favorite on a high-volume market should be suppressed."""
        mock_market.return_value = {"volume24hr": 100_000}
        trades = [
            self._make_trade("wallet_1", usd=2000, price=0.77),
            self._make_trade("wallet_2", usd=2000, price=0.78),
            self._make_trade("wallet_3", usd=2000, price=0.75),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.concentrated_one_sided.get_market_by_condition")
    def test_heavy_favorite_low_volume_not_suppressed(self, mock_market):
        """Buying a heavy favorite on a LOW-volume market is still interesting."""
        mock_market.return_value = {"volume24hr": 10_000}
        trades = [
            self._make_trade("wallet_1", usd=2000, price=0.77),
            self._make_trade("wallet_2", usd=2000, price=0.78),
            self._make_trade("wallet_3", usd=2000, price=0.75),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)

    def test_underdog_high_volume_not_suppressed(self):
        """Buying an underdog (low price) is always interesting regardless of volume."""
        trades = [
            self._make_trade("wallet_1", usd=2000, price=0.25),
            self._make_trade("wallet_2", usd=2000, price=0.27),
            self._make_trade("wallet_3", usd=2000, price=0.23),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)

    @patch("detection_strategies.concentrated_one_sided.get_market_by_condition")
    def test_sell_side_not_suppressed_by_favorite_filter(self, mock_market):
        """SELL-side clusters aren't affected by the favorite suppression."""
        mock_market.return_value = {"volume24hr": 100_000}
        trades = [
            self._make_trade("wallet_1", usd=2000, price=0.80, side="SELL"),
            self._make_trade("wallet_2", usd=2000, price=0.80, side="SELL"),
            self._make_trade("wallet_3", usd=2000, price=0.80, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)


    # ------------------------------------------------------------------
    # New tests: binary remapping, price filtering, severity, boosts
    # ------------------------------------------------------------------

    def test_binary_market_sell_remapped_to_buy(self):
        """SELL No on a binary market should be remapped to BUY Yes,
        clustering with direct BUY Yes trades."""
        trades = [
            # Two wallets directly BUY Yes
            self._make_trade("wallet_1", cid="cond_bin", outcome="Yes", side="BUY", usd=2000, price=0.60),
            self._make_trade("wallet_2", cid="cond_bin", outcome="Yes", side="BUY", usd=2000, price=0.60),
            # One wallet SELLs No at 0.20 → remapped to BUY Yes at 0.80
            self._make_trade("wallet_3", cid="cond_bin", outcome="No", side="SELL", usd=2000, price=0.20),
            # Need a trade on the "No" outcome so the market is detected as binary
            self._make_trade("wallet_4", cid="cond_bin", outcome="No", side="BUY", usd=100, price=0.40),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 wallets", signals[0].headline)

    def test_resolved_trade_price_filtered(self):
        """BUY at price >= 0.98 should be filtered out as near-certain."""
        trades = [
            self._make_trade("wallet_1", usd=2000, price=0.50),
            self._make_trade("wallet_2", usd=2000, price=0.50),
            self._make_trade("wallet_3", usd=2000, price=0.50),
            self._make_trade("wallet_4", usd=2000, price=0.99),  # filtered
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 wallets", signals[0].headline)

    def test_severity_log_scaling(self):
        """5 wallets → severity = min(6.0, 2.5 + log2(5)) ≈ 4.82."""
        trades = [
            self._make_trade(f"wallet_{i}", usd=2000, price=0.50)
            for i in range(5)
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        expected = min(6.0, 2.5 + math.log2(5))
        self.assertAlmostEqual(signals[0].severity, expected, places=2)

    def test_volume_boost_50k(self):
        """Total $60k (>= $50k) should add +0.5 severity boost."""
        trades = [
            self._make_trade(f"wallet_{i}", usd=20000, price=0.50)
            for i in range(3)
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        base = min(6.0, 2.5 + math.log2(3))
        expected = min(6.5, base + 0.5)
        self.assertAlmostEqual(signals[0].severity, expected, places=2)

    def test_volume_boost_100k(self):
        """Total $120k (>= $100k) should add +1.0 severity boost."""
        trades = [
            self._make_trade(f"wallet_{i}", usd=40000, price=0.50)
            for i in range(3)
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        base = min(6.0, 2.5 + math.log2(3))
        expected = min(7.0, base + 1.0)
        self.assertAlmostEqual(signals[0].severity, expected, places=2)

    @patch("detection_strategies.concentrated_one_sided.get_cached_funder")
    def test_shared_funder_boost(self, mock_funder):
        """Two wallets sharing a funder should add +1.5 severity and
        'share funder (linked)' to headline."""
        def funder_side_effect(wallet):
            if wallet in ("wallet_0", "wallet_1"):
                return (True, "0xsamefunder")
            return (True, None)

        mock_funder.side_effect = funder_side_effect
        trades = [
            self._make_trade(f"wallet_{i}", usd=2000, price=0.50)
            for i in range(3)
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        base = min(6.0, 2.5 + math.log2(3))
        expected = min(8.0, base + 1.5)
        self.assertAlmostEqual(signals[0].severity, expected, places=2)
        self.assertIn("share funder (linked)", signals[0].headline)

    def test_near_certain_sell_filtered(self):
        """SELL at price <= 0.02 should be filtered (near-certain)."""
        trades = [
            self._make_trade(f"wallet_{i}", usd=2000, price=0.01, side="SELL")
            for i in range(3)
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_missing_fields_skipped(self):
        """A trade with empty conditionId should be skipped without crashing."""
        trades = [
            self._make_trade("wallet_1", usd=2000),
            self._make_trade("wallet_2", usd=2000),
            self._make_trade("wallet_3", usd=2000),
            # Trade with missing conditionId
            {
                "proxyWallet": "wallet_bad",
                "conditionId": "",
                "outcome": "Yes",
                "side": "BUY",
                "_usd_value": 2000,
                "price": 0.50,
                "transactionHash": "0xtx_bad",
            },
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 wallets", signals[0].headline)


if __name__ == "__main__":
    unittest.main()
