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


    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_exchange_hot_wallet_filtered(self, mock_funder, mock_get_wallets, mock_sybils):
        """Funder with >= MAX_FUNDER_CHILDREN is skipped as likely exchange hot wallet."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        # Return 20+ addresses for this funder (>= MAX_FUNDER_CHILDREN)
        mock_get_wallets.return_value = [f"0xchild_{i}" for i in range(25)]
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_historical_wallet_escalation(self, mock_funder, mock_get_wallets, mock_sybils):
        """Single wallet in window, but historical wallets push cluster to >= MIN_SHARED_WALLETS."""
        mock_funder.return_value = "0xfunder"
        # Both calls to get_wallets_by_funder return the same 2-element list:
        # first call: MAX_FUNDER_CHILDREN check (len < 20, passes)
        # second call: historical augmentation (adds 0xhistorical_wallet)
        mock_get_wallets.return_value = ["0xwallet1", "0xhistorical_wallet"]
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("from prior runs", signals[0].headline)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_known_sybil_funder_triggers(self, mock_funder, mock_get_wallets, mock_sybils):
        """Known sybil funder triggers signal with severity 6.0 even without first-pass cluster."""
        # Each wallet gets a unique funder so first pass finds no clusters
        mock_funder.side_effect = lambda addr: f"funder_of_{addr}"
        # Override known sybil funders to include 0xfunder_a with wallet1 in historical
        mock_sybils.return_value = {
            "0xfunder_a": ["0xwallet1", "0xwallet_old"],
        }
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 6.0)
        self.assertIn("Known linked funder", signals[0].headline)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_known_sybil_skipped_if_seen_in_first_pass(self, mock_funder, mock_get_wallets, mock_sybils):
        """Funder already seen in first pass is not duplicated by known-sybil second pass."""
        mock_funder.side_effect = lambda addr: "0xfunder_a"
        mock_sybils.return_value = {
            "0xfunder_a": ["0xwallet1", "0xwallet2"],
        }
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        # Only 1 signal from first pass; second pass skips 0xfunder_a via seen_funders
        self.assertEqual(len(signals), 1)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_severity_scales_with_cluster_size(self, mock_funder, *mocks):
        """4 wallets sharing a funder -> severity = 4.0 + log2(4) = 6.0."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
            self._make_trade("0xwallet3"),
            self._make_trade("0xwallet4"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 6.0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_empty_wallet_trades_excluded(self, mock_funder, *mocks):
        """Trades with empty proxyWallet are excluded from clustering."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade(""),  # empty wallet
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # Only 2 valid wallets contributed, not 3
        self.assertIn("2 wallets", signals[0].headline)


if __name__ == "__main__":
    unittest.main()
