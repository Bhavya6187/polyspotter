import unittest
from unittest.mock import patch

import db
from detection_strategies import wallet_clustering as wc_module
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
    def test_lone_wallet_with_historical_funder_lower_severity(self, mock_funder, mock_get_wallets, mock_sybils):
        """Loop 2: a lone window wallet whose funder was linked before this
        window (and was not caught by loop 1) fires at
        HISTORICAL_LINK_SEVERITY (4.0), below a two-wallet in-window
        cluster (5.0)."""
        # Each wallet gets a unique funder so first pass finds no clusters
        mock_funder.side_effect = lambda addr: f"funder_of_{addr}"
        # Override known sybil funders to include 0xfunder_a with wallet1 in historical
        mock_sybils.return_value = {
            "0xfunder_a": ["0xwallet1", "0xwallet_old"],
        }
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 4.0)
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


    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_known_sybil_boost_first_pass(self, mock_funder, mock_get_wallets, mock_sybils):
        """First-pass cluster where funder is a known sybil gets +1.0 severity boost."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        mock_sybils.return_value = {"0xfunder_common": ["0xwallet1", "0xwallet2"]}
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
        ]
        signals = self.strategy.analyze_all(trades)
        # 2 wallets: base = 4.0 + log2(2) = 5.0, plus +1.0 sybil boost = 6.0
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 6.0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_severity_cap_at_8(self, mock_funder, mock_get_wallets, mock_sybils):
        """Cluster with 16 wallets capped at severity 8.0 even with sybil boost."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        # Make funder a known sybil so boost would push beyond 8.0
        mock_sybils.return_value = {"0xfunder_common": [f"0xwallet{i}" for i in range(16)]}
        trades = [self._make_trade(f"0xwallet{i}") for i in range(16)]
        signals = self.strategy.analyze_all(trades)
        # base = 4.0 + log2(16) = 8.0, +1.0 boost would be 9.0 -> capped at 8.0
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 8.0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_case_insensitive_wallet_grouping(self, mock_funder, *mocks):
        """Wallets differing only in case should be treated as the same wallet."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            self._make_trade("0xABC"),
            self._make_trade("0xabc"),
        ]
        signals = self.strategy.analyze_all(trades)
        # Both lowercase to "0xabc" — only 1 unique wallet, should produce no signal
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_multiple_clusters_separate_signals(self, mock_funder, *mocks):
        """Two distinct funders each with 2+ wallets produce 2 separate signals."""
        def funder_for(addr):
            if addr in ("0xwallet1", "0xwallet2"):
                return "0xfunder_a"
            return "0xfunder_b"

        mock_funder.side_effect = funder_for
        trades = [
            self._make_trade("0xwallet1"),
            self._make_trade("0xwallet2"),
            self._make_trade("0xwallet3"),
            self._make_trade("0xwallet4"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 2)
        strategies = {s.strategy for s in signals}
        self.assertEqual(strategies, {"wallet_clustering"})

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_second_pass_skips_large_funder(self, mock_funder, mock_get_wallets, mock_sybils):
        """Second pass skips known sybil funders with >= MAX_FUNDER_CHILDREN historical wallets."""
        # Unique funders so first pass finds no clusters
        mock_funder.side_effect = lambda addr: f"funder_of_{addr}"
        # Known sybil funder with >= MAX_FUNDER_CHILDREN (20) historical wallets
        large_historical = [f"0xwalletX{i}" for i in range(20)]
        mock_sybils.return_value = {"0xsybil_funder": large_historical}
        # wallet1's funder maps to sybil_funder, but it has too many children
        trades = [self._make_trade("0xwallet1")]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_multiple_trades_per_wallet(self, mock_funder, *mocks):
        """A wallet with multiple trades should have all trades aggregated in the cluster."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            {"proxyWallet": "0xwallet1", "conditionId": "cond_1", "_usd_value": 1000, "transactionHash": "0xtx_a"},
            {"proxyWallet": "0xwallet1", "conditionId": "cond_2", "_usd_value": 2000, "transactionHash": "0xtx_b"},
            {"proxyWallet": "0xwallet2", "conditionId": "cond_1", "_usd_value": 500, "transactionHash": "0xtx_c"},
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # All 3 trades aggregated: total usd = 3500
        self.assertIn("3,500", signals[0].headline)
        self.assertEqual(len(signals[0].trade_hashes), 3)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_missing_usd_value_defaults_zero(self, mock_funder, *mocks):
        """Trade with no _usd_value should default to 0 in total USD aggregation."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            {"proxyWallet": "0xwallet1", "conditionId": "cond_1", "transactionHash": "0xtx_a"},
            {"proxyWallet": "0xwallet2", "conditionId": "cond_1", "transactionHash": "0xtx_b"},
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # Total USD should be 0 since neither trade has _usd_value
        self.assertIn("$0", signals[0].headline)

    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test_key")
    @patch("detection_strategies.wallet_clustering._get_first_funder")
    def test_missing_transaction_hash_excluded(self, mock_funder, *mocks):
        """Trade without transactionHash should not appear in trade_hashes list."""
        mock_funder.side_effect = lambda addr: "0xfunder_common"
        trades = [
            {"proxyWallet": "0xwallet1", "conditionId": "cond_1", "_usd_value": 3000, "transactionHash": "0xtx_a"},
            {"proxyWallet": "0xwallet2", "conditionId": "cond_1", "_usd_value": 3000},  # no transactionHash
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        # Only the trade with a transactionHash should be in trade_hashes
        self.assertEqual(len(signals[0].trade_hashes), 1)
        self.assertIn("0xtx_a", signals[0].trade_hashes)


class TestFunderNegativeCache(unittest.TestCase):
    """An in-memory None funder used to override the DB's 7-day NULL retry
    (get_cached_funder treats stale NULL rows as uncached) until restart."""

    WALLET = "0x" + "a" * 40
    FUNDER = "0x" + "f" * 40

    def setUp(self):
        from detection_strategies import wallet_clustering as wc

        wc._funder_cache.clear()
        self.wc = wc

    def tearDown(self):
        self.wc._funder_cache.clear()

    @patch("detection_strategies.wallet_clustering.FUNDER_LOOKUP_DELAY", 0)
    @patch("detection_strategies.wallet_clustering.ETHERSCAN_API_KEY", "test-key")
    @patch("detection_strategies.wallet_clustering.save_funder")
    @patch("detection_strategies.wallet_clustering._query_etherscan")
    @patch("detection_strategies.wallet_clustering.get_cached_funder")
    def test_funder_none_cache_respects_db_retry(self, mock_cached, mock_query, mock_save):
        inbound = [{"to": self.WALLET, "from": self.FUNDER, "blockNumber": "100"}]
        # 1st: not in DB, Etherscan finds nothing -> NULL row saved.
        # 2nd: DB NULL row still fresh -> None, no Etherscan call.
        # 3rd: DB NULL row older than the retry window -> uncached -> re-query.
        mock_cached.side_effect = [(False, None), (True, None), (False, None)]
        mock_query.side_effect = [[], [], inbound, []]

        self.assertIsNone(self.wc._get_first_funder(self.WALLET))
        mock_save.assert_called_once_with(self.WALLET, None)
        self.assertIsNone(self.wc._get_first_funder(self.WALLET))
        self.assertEqual(mock_query.call_count, 2)

        self.assertEqual(self.wc._get_first_funder(self.WALLET), self.FUNDER)
        self.assertEqual(mock_query.call_count, 4)


class TestKnownFunderBoostUsesPriorState(unittest.TestCase):
    """Handoff 1.3: the +1.0 known-funder boost read get_known_sybil_funders
    AFTER _get_first_funder had saved this window's funders, so every
    in-window cluster was 'known' (100% of 1,552 signals over 90 days carried
    the boost). The class above patches get_known_sybil_funders to {} and
    _get_first_funder, which hid that; these tests run the real lookup path
    (Etherscan stubbed) against a scratch database."""

    FUNDER = "0x" + "f" * 40

    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patches = [
            patch.object(db, "DB_PATH", f"{tmp.name}/polybot.db"),
            patch.object(db, "_conn", None),
            patch.dict(wc_module._funder_cache, {}, clear=True),
            patch.object(wc_module, "ETHERSCAN_API_KEY", "test_key"),
            patch.object(wc_module, "FUNDER_LOOKUP_DELAY", 0),
            patch.object(wc_module, "_query_etherscan", self._fake_etherscan),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._close)
        self.strategy = WalletClusteringStrategy()

    def _close(self):
        if db._conn is not None:
            db._conn.close()
            db._conn = None

    def _fake_etherscan(self, address, action, offset=10):
        if action == "txlist":
            return [{"to": address, "from": self.FUNDER, "blockNumber": "1"}]
        return []

    @staticmethod
    def _wallet(i):
        return "0x" + f"{i:040x}"

    def _trade(self, wallet):
        return {
            "proxyWallet": wallet,
            "conditionId": "cond_1",
            "_usd_value": 5000,
            "transactionHash": f"0xtx_{wallet}",
        }

    def test_two_wallet_cluster_without_prior_funder_scores_5(self):
        trades = [self._trade(self._wallet(1)), self._trade(self._wallet(2))]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("2 wallets", signals[0].headline)
        self.assertEqual(signals[0].severity, 5.0)

    def test_cluster_with_previously_known_funder_scores_6(self):
        # an earlier run already linked two wallets to this funder
        db.save_funder(self._wallet(1), self.FUNDER)
        db.save_funder(self._wallet(2), self.FUNDER)
        trades = [self._trade(self._wallet(3)), self._trade(self._wallet(4))]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 6.0)

    def test_lone_wallet_joining_single_historical_wallet_not_boosted(self):
        # the funder had one wallet before this window; this window's lookup
        # makes it two. Loop 1's cross-window branch reports the pair, but
        # the funder was not a known linked funder before this window.
        db.save_funder(self._wallet(1), self.FUNDER)
        signals = self.strategy.analyze_all([self._trade(self._wallet(2))])
        self.assertEqual(len(signals), 1)
        self.assertIn("from prior runs", signals[0].headline)
        self.assertEqual(signals[0].severity, 5.0)

    def _hot_wallet_boundary_trades(self, n_historical):
        # the funder already has n_historical children; this window holds one
        # of them plus one brand-new wallet, whose lookup adds one more
        for i in range(1, n_historical + 1):
            db.save_funder(self._wallet(i), self.FUNDER)
        return [self._trade(self._wallet(1)), self._trade(self._wallet(99))]

    def test_funder_reaching_hot_wallet_cap_in_window_not_flagged(self):
        # 19 known children + 1 new = 20 >= MAX_FUNDER_CHILDREN: loop 1 skips
        # the funder as an exchange hot wallet, and loop 2 (which reads the
        # pre-window snapshot of 19) must not flag it either.
        self.assertEqual(wc_module.MAX_FUNDER_CHILDREN, 20)
        trades = self._hot_wallet_boundary_trades(19)
        self.assertEqual(self.strategy.analyze_all(trades), [])

    def test_funder_below_hot_wallet_cap_flagged_by_loop_1(self):
        # control: 18 known + 1 new = 19 < 20, loop 1 reports the cluster
        trades = self._hot_wallet_boundary_trades(18)
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("share funder", signals[0].headline)
        self.assertNotIn("Known linked funder", signals[0].headline)


if __name__ == "__main__":
    unittest.main()
