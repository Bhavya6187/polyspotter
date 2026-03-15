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


if __name__ == "__main__":
    unittest.main()
