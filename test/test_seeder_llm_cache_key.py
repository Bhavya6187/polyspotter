"""
Tests for bucketed LLM cache keys in seeder.

Backtest-derived policy (see STRATEGY_USAGE_REPORT.md addendum): the LLM
cache key buckets trade_count by doubling (floor(log2)) and composite score
by 2-point bands (on the 2026-07 compute_composite_score scale), so an alert
is only re-evaluated when it materially grows instead of on every
incremental trade.
"""

import unittest
from unittest.mock import patch

from seeder import _build_llm_cache_key, build_alerts_payload


class TestClusterCacheKeyBucketing(unittest.TestCase):
    def _key(self, trade_count, score, cid="cond1", direction="Yes:BUY"):
        return _build_llm_cache_key(
            None, cid, cluster_direction=direction,
            trade_count=trade_count, composite_score=score,
        )

    def test_same_doubling_bucket_same_key(self):
        # 5 and 7 share floor(log2) bucket 2
        self.assertEqual(self._key(5, 6.0), self._key(7, 6.0))

    def test_trade_count_doubling_changes_key(self):
        self.assertNotEqual(self._key(5, 6.0), self._key(10, 6.0))

    def test_same_score_band_same_key(self):
        # 4.0 and 5.9 are both in band 2 (score // 2)
        self.assertEqual(self._key(5, 4.0), self._key(5, 5.9))

    def test_score_band_change_changes_key(self):
        self.assertNotEqual(self._key(5, 5.9), self._key(5, 6.1))

    def test_direction_distinguishes_clusters(self):
        self.assertNotEqual(
            self._key(5, 6.0, direction="Yes:BUY"),
            self._key(5, 6.0, direction="No:BUY"),
        )


class TestIndividualCacheKeyBucketing(unittest.TestCase):
    def _key(self, trade_count, wallet="0xabc", cid="cond1"):
        return _build_llm_cache_key(wallet, cid, trade_count=trade_count)

    def test_same_doubling_bucket_same_key(self):
        # 2 and 3 share floor(log2) bucket 1
        self.assertEqual(self._key(2), self._key(3))

    def test_trade_count_doubling_changes_key(self):
        self.assertNotEqual(self._key(2), self._key(4))

    def test_wallet_and_market_distinguish_keys(self):
        self.assertNotEqual(self._key(2, wallet="0xabc"), self._key(2, wallet="0xdef"))
        self.assertNotEqual(self._key(2, cid="cond1"), self._key(2, cid="cond2"))


class TestScoreBandInCacheKey(unittest.TestCase):
    """Handoff 1.1: a per-wallet alert whose composite score moves across a
    whole point must be re-evaluated instead of reusing a verdict made on
    different content (2,511 of 10,109 reuse rows over 90 days would have
    failed the pre-LLM gate on their own content)."""

    def test_per_wallet_cache_key_includes_score_band(self):
        def key(score):
            return _build_llm_cache_key(
                "0xabc", "cond1", trade_count=3, composite_score=score,
            )

        self.assertNotEqual(key(2.9), key(5.5))
        self.assertEqual(key(5.1), key(5.9))

    def test_cluster_cache_key_unchanged(self):
        import hashlib

        key = _build_llm_cache_key(
            None, "cond1", cluster_direction="Yes:BUY",
            trade_count=5, composite_score=5.5,
        )
        expected = hashlib.sha256(b"llm:cluster:cond1:Yes:BUY:2:2").hexdigest()[:32]
        self.assertEqual(key, expected)


class FakeSignal:
    """Minimal Signal-like object for testing."""

    def __init__(self, strategy, trade, severity=5.0, trade_hashes=None):
        self.strategy = strategy
        self.trade = trade
        self.condition_id = trade.get("conditionId", "")
        self.severity = severity
        self.trade_hashes = trade_hashes or []
        self.headline = f"{strategy} headline"

    @property
    def dedup_key(self):
        return (self.strategy, self.headline)


class TestIndividualAlertsGetLLMCacheKey(unittest.TestCase):
    @patch("seeder._resolve_event_timing", return_value=(None, None))
    @patch("seeder._resolve_market_media", return_value=(None, None))
    @patch("seeder._resolve_end_date", return_value=None)
    @patch("seeder._resolve_tags", return_value=[])
    def test_individual_composite_alert_has_bucketed_llm_cache_key(self, *_):
        trade = {
            "transactionHash": "0xtx1",
            "proxyWallet": "0xwallet1",
            "conditionId": "cond1",
            "eventSlug": "test-event",
            "title": "Test Market",
            "outcome": "Yes",
            "side": "BUY",
            "_usd_value": 5000,
            "size": 10000,
            "price": 0.5,
            "timestamp": 1700000000,
        }
        sig = FakeSignal("new_wallet_large_bet", trade)
        payload = build_alerts_payload([sig], [trade])
        self.assertEqual(len(payload["alerts"]), 1)
        alert = payload["alerts"][0]
        self.assertEqual(
            alert["llm_cache_key"],
            _build_llm_cache_key(
                "0xwallet1", "cond1", trade_count=1,
                composite_score=alert["composite_score"],
            ),
        )
        # backend dedup key must stay tx-hash based (unchanged upsert identity)
        self.assertNotEqual(alert["llm_cache_key"], alert["dedup_key"])


if __name__ == "__main__":
    unittest.main()
