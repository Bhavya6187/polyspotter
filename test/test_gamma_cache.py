import unittest
from unittest.mock import patch, MagicMock

import gamma_cache


class GetMarketByConditionTests(unittest.TestCase):
    def setUp(self):
        # Clear the module-level cache so tests don't leak between each other.
        gamma_cache._market_cache.clear()

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_active_market_returned_on_first_call(self, mock_get):
        market = {"conditionId": "0xabc", "question": "Active market"}
        resp = MagicMock()
        resp.json.return_value = [market]
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        result = gamma_cache.get_market_by_condition("0xabc")

        self.assertEqual(result, market)
        self.assertEqual(mock_get.call_count, 1)
        # First (and only) call should NOT pass closed=true — active-market path.
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"], {"condition_ids": "0xabc"})

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_closed_market_returned_via_fallback(self, mock_get):
        closed_market = {"conditionId": "0xdef", "question": "Closed market", "closed": True}
        active_resp = MagicMock()
        active_resp.json.return_value = []  # default query returns empty
        active_resp.raise_for_status.return_value = None
        closed_resp = MagicMock()
        closed_resp.json.return_value = [closed_market]
        closed_resp.raise_for_status.return_value = None
        mock_get.side_effect = [active_resp, closed_resp]

        result = gamma_cache.get_market_by_condition("0xdef")

        self.assertEqual(result, closed_market)
        self.assertEqual(mock_get.call_count, 2)
        # Second call must carry closed=true.
        second_call_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(
            second_call_kwargs["params"],
            {"condition_ids": "0xdef", "closed": "true"},
        )

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_nonexistent_market_returns_none_after_fallback(self, mock_get):
        empty_resp = MagicMock()
        empty_resp.json.return_value = []
        empty_resp.raise_for_status.return_value = None
        mock_get.side_effect = [empty_resp, empty_resp]

        result = gamma_cache.get_market_by_condition("0xghi")

        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2)

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_cached_result_skips_network(self, mock_get):
        market = {"conditionId": "0xjkl"}
        resp = MagicMock()
        resp.json.return_value = [market]
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        first = gamma_cache.get_market_by_condition("0xjkl")
        second = gamma_cache.get_market_by_condition("0xjkl")

        self.assertEqual(first, market)
        self.assertEqual(second, market)
        # Cached on first call — second should not hit the network.
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
