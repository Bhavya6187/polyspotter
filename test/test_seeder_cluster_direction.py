"""
Tests that cluster alert identity (backend dedup_key / llm_cache_key) is
derived from the cluster's effective direction, not from whichever member
trade happens to be first in the batch.

Regression test for a real production bug (verified 2026-07-09 on a live
14-wallet cluster): when a direction-remapped SELL trade was the sample,
the dedup key flipped between e.g. "No:SELL" and "Yes:BUY" across scans,
producing duplicate cluster alerts and redundant LLM evaluations.
"""

import unittest
from unittest.mock import patch

from detection_strategies.concentrated_one_sided import ConcentratedOneSidedStrategy
from seeder import build_alerts_payload


def _make_trade(wallet, outcome, side, price, tx):
    return {
        "proxyWallet": wallet,
        "conditionId": "cond_bin",
        "outcome": outcome,
        "side": side,
        "price": price,
        "_usd_value": 2000,
        "size": 4000,
        "transactionHash": tx,
        "title": "Test Market",
        "eventSlug": "test-event",
        "timestamp": 1700000000,
    }


@patch("seeder._resolve_event_timing", return_value=(None, None))
@patch("seeder._resolve_market_media", return_value=(None, None))
@patch("seeder._resolve_end_date", return_value=None)
@patch("seeder._resolve_tags", return_value=[])
@patch(
    "detection_strategies.concentrated_one_sided.get_cached_funder",
    return_value=(True, None),
)
class TestClusterDedupKeyStable(unittest.TestCase):
    def _payload_for(self, trades):
        strategy = ConcentratedOneSidedStrategy()
        signals = strategy.analyze_all(trades)
        assert len(signals) == 1, f"expected 1 cluster signal, got {len(signals)}"
        return build_alerts_payload(signals, trades)

    def test_cluster_dedup_key_ignores_trade_order(self, *_):
        sell = _make_trade("wallet_1", "No", "SELL", 0.40, "0xtx_sell")
        buys = [
            _make_trade("wallet_2", "Yes", "BUY", 0.60, "0xtx_buy_2"),
            _make_trade("wallet_3", "Yes", "BUY", 0.61, "0xtx_buy_3"),
        ]

        payload_sell_first = self._payload_for([sell] + buys)
        payload_buy_first = self._payload_for(buys + [sell])

        alert_a = payload_sell_first["alerts"][0]
        alert_b = payload_buy_first["alerts"][0]
        self.assertEqual(alert_a["alert_type"], "cluster")
        self.assertEqual(alert_a["dedup_key"], alert_b["dedup_key"])
        self.assertEqual(alert_a["llm_cache_key"], alert_b["llm_cache_key"])


if __name__ == "__main__":
    unittest.main()
