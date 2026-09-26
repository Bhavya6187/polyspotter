"""
concentrated_one_sided must not call wallets "linked" because they share a
Polymarket relayer address.

wallet_funders stores the first sender of each proxy wallet; 95% of the
non-null entries are ~50 relayer-like addresses with 20-1,070 children.
wallet_clustering already skips funders with >= MAX_FUNDER_CHILDREN known
children, but concentrated_one_sided applied its +1.5 "share funder (linked)"
boost -- and the headline that ends up in tweets and covers -- without that
guard.
"""

import unittest
from unittest.mock import patch

from detection_strategies.concentrated_one_sided import ConcentratedOneSidedStrategy
from detection_strategies.wallet_clustering import MAX_FUNDER_CHILDREN


def _trade(wallet, usd=2000, price=0.5):
    return {
        "proxyWallet": wallet,
        "conditionId": "cond_1",
        "outcome": "Yes",
        "side": "BUY",
        "_usd_value": usd,
        "price": price,
        "transactionHash": f"0xtx_{wallet}",
    }


class RelayerFunderTests(unittest.TestCase):
    def setUp(self):
        self.strategy = ConcentratedOneSidedStrategy()
        self.trades = [_trade(f"wallet_{i}") for i in range(3)]

    @patch("detection_strategies.concentrated_one_sided.get_wallets_by_funder")
    @patch("detection_strategies.concentrated_one_sided.get_cached_funder", return_value=(True, "0xrelayer"))
    def test_relayer_funder_is_not_linked(self, _mock_funder, mock_children):
        mock_children.return_value = [f"0x{i}" for i in range(MAX_FUNDER_CHILDREN)]

        signals = self.strategy.analyze_all(self.trades)

        self.assertEqual(len(signals), 1)
        self.assertNotIn("linked", signals[0].headline)

    @patch("detection_strategies.concentrated_one_sided.get_wallets_by_funder")
    @patch("detection_strategies.concentrated_one_sided.get_cached_funder", return_value=(True, "0xperson"))
    def test_small_funder_is_still_linked(self, _mock_funder, mock_children):
        mock_children.return_value = ["wallet_0", "wallet_1", "wallet_2"]

        signals = self.strategy.analyze_all(self.trades)

        self.assertEqual(len(signals), 1)
        self.assertIn("3 share funder (linked)", signals[0].headline)


if __name__ == "__main__":
    unittest.main()
