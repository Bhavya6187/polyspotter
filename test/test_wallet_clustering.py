import unittest
from unittest.mock import patch

from detection_strategies.wallet_clustering import WalletClusteringStrategy


@patch("detection_strategies.wallet_clustering.get_known_sybil_funders", return_value={})
@patch("detection_strategies.wallet_clustering.get_wallets_by_funder", return_value=[])
class TestWalletClusteringStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = WalletClusteringStrategy()

    def _make_trade(self, wallet, cid="cond_1", usd=5000):
        return {
            "proxyWallet": wallet,
            "conditionId": cid,
            "_usd_value": usd,
            "transactionHash": f"0xtx_{wallet}",
        }

    def test_check_trade_always_none(self, *mocks):
        trade = self._make_trade("0xwallet1")
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self, *mocks):
        self.assertEqual(self.strategy.analyze_all([]), [])

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "")
    def test_no_api_key_returns_empty(self, *mocks):
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_shared_funder_triggers_signal(self, mock_funder, *mocks):
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            self._make_trade("0xWallet1", usd=3000),
            self._make_trade("0xWallet2", usd=3000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "wallet_clustering")
        self.assertIn("2 wallets", signals[0].headline)
        self.assertEqual(signals[0].severity, 5.0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_different_funders_no_signal(self, mock_funder, *mocks):
        mock_funder.side_effect = lambda addr: f"funder_of_{addr}"
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_single_wallet_no_signal(self, mock_funder, *mocks):
        mock_funder.return_value = "0xfunder_common"
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_trade_hashes_collected(self, mock_funder, *mocks):
        mock_funder.return_value = "0xfunder_common"
        trades = [
            self._make_trade("0xWallet1"),
            self._make_trade("0xWallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 2)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_funder_none_excluded(self, mock_funder, *mocks):
        mock_funder.return_value = None
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)


if __name__ == "__main__":
    unittest.main()
