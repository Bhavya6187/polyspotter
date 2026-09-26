"""
gamma_cache entries must expire.

The scanner runs for weeks; before this fix a market's Gamma metadata
(volume24hr, liquidity, outcomePrices, endDate, closed) was cached for the
life of the process. low_activity_large_bet kept flagging "quiet" markets
that had become busy, pre_event_volume_spike snapshotted the same frozen
volume every 30 minutes (one market: 32 identical snapshots over 27 days),
and the seeder pushed stale end dates / start times.
"""

import unittest
from unittest.mock import MagicMock, patch

import gamma_cache


def _resp(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class MarketCacheTtlTests(unittest.TestCase):
    def setUp(self):
        gamma_cache._market_cache.clear()
        gamma_cache._market_fetched_at.clear()

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_entry_is_reused_inside_ttl(self, mock_get):
        mock_get.return_value = _resp([{"conditionId": "0xabc", "volume24hr": 1}])
        with patch("gamma_cache.time.time", return_value=1000.0):
            gamma_cache.get_market_by_condition("0xabc")
        with patch("gamma_cache.time.time", return_value=1000.0 + gamma_cache.MARKET_CACHE_TTL_SECONDS - 1):
            gamma_cache.get_market_by_condition("0xabc")
        self.assertEqual(mock_get.call_count, 1)

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_entry_is_refetched_after_ttl(self, mock_get):
        mock_get.side_effect = [
            _resp([{"conditionId": "0xabc", "volume24hr": 1}]),
            _resp([{"conditionId": "0xabc", "volume24hr": 500_000}]),
        ]
        with patch("gamma_cache.time.time", return_value=1000.0):
            first = gamma_cache.get_market_by_condition("0xabc")
        with patch("gamma_cache.time.time", return_value=1000.0 + gamma_cache.MARKET_CACHE_TTL_SECONDS + 1):
            second = gamma_cache.get_market_by_condition("0xabc")

        self.assertEqual(first["volume24hr"], 1)
        self.assertEqual(second["volume24hr"], 500_000)
        self.assertEqual(mock_get.call_count, 2)

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_failed_refetch_keeps_serving_the_stale_entry(self, mock_get):
        """Gamma hiccups must not turn a known market into None mid-scan."""
        import requests
        mock_get.side_effect = [
            _resp([{"conditionId": "0xabc", "volume24hr": 1}]),
            requests.ConnectionError("boom"),
            requests.ConnectionError("boom"),
        ]
        with patch("gamma_cache.time.time", return_value=1000.0):
            gamma_cache.get_market_by_condition("0xabc")
        with patch("gamma_cache.time.time", return_value=1000.0 + gamma_cache.MARKET_CACHE_TTL_SECONDS + 1):
            stale = gamma_cache.get_market_by_condition("0xabc")
        self.assertEqual(stale["volume24hr"], 1)

    def test_invalidate_clears_both_maps(self):
        gamma_cache._market_cache["0xabc"] = {"conditionId": "0xabc"}
        gamma_cache._market_fetched_at["0xabc"] = 1.0
        gamma_cache.invalidate_market("0xabc")
        self.assertNotIn("0xabc", gamma_cache._market_cache)
        self.assertNotIn("0xabc", gamma_cache._market_fetched_at)

    def test_ttl_is_shorter_than_the_volume_snapshot_interval(self):
        # pre_event_volume_spike snapshots volume every 30 minutes; the cache
        # must refresh at least that often or snapshots repeat stale values.
        self.assertLessEqual(gamma_cache.MARKET_CACHE_TTL_SECONDS, 30 * 60)


if __name__ == "__main__":
    unittest.main()
