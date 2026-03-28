"""
Tests for seeder thesis-building and resolution-checking logic.
"""

import unittest
from unittest.mock import patch, MagicMock
from collections import namedtuple

from seeder import build_theses_payload


class FakeSignal:
    """Minimal Signal-like object for testing."""
    def __init__(self, strategy, wallet, event_slug, condition_id, trade=None):
        self.strategy = strategy
        self.condition_id = condition_id
        self.trade = trade or {
            "proxyWallet": wallet,
            "eventSlug": event_slug,
            "conditionId": condition_id,
            "title": "Test Market",
            "outcome": "Yes",
            "side": "BUY",
            "_usd_value": 1000,
            "price": 0.6,
        }
        self.severity = 5.0
        self.trade_hashes = []
        self.headline = "test"

    @property
    def dedup_key(self):
        return (self.strategy, self.headline)


class TestBuildThesesPayload(unittest.TestCase):
    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test Market"})
    def test_groups_by_wallet_event(self, mock_market, mock_history):
        signals = [
            FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1"),
            FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_2"),
        ]
        theses = build_theses_payload(signals, [])
        assert len(theses) == 1
        assert theses[0]["wallet"] == "0xabc"
        assert theses[0]["event_slug"] == "event-1"
        assert len(theses[0]["markets"]) == 2

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_different_wallets_separate_theses(self, mock_market, mock_history):
        signals = [
            FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1"),
            FakeSignal("correlated_cross_market", "0xdef", "event-1", "cond_2"),
        ]
        theses = build_theses_payload(signals, [])
        assert len(theses) == 2

    def test_ignores_non_cross_market_signals(self):
        signals = [
            FakeSignal("win_rate_tracking", "0xabc", "event-1", "cond_1"),
        ]
        theses = build_theses_payload(signals, [])
        assert len(theses) == 0

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_deduplicates_condition_ids(self, mock_market, mock_history):
        sig1 = FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1")
        sig2 = FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1")
        theses = build_theses_payload([sig1, sig2], [])
        assert len(theses) == 1
        assert len(theses[0]["markets"]) == 1  # deduped

    @patch("db.get_wallet_event_history")
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Historical"})
    def test_includes_wallet_history(self, mock_market, mock_history):
        mock_history.return_value = [
            {"condition_id": "cond_hist", "outcome": "No", "side": "SELL", "usd_value": 500},
        ]
        signals = [
            FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1"),
        ]
        theses = build_theses_payload(signals, [])
        assert len(theses) == 1
        assert len(theses[0]["markets"]) == 2  # 1 from signal + 1 from history

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_total_usd_summed(self, mock_market, mock_history):
        sig1 = FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_1")
        sig1.trade["_usd_value"] = 2000
        sig2 = FakeSignal("correlated_cross_market", "0xabc", "event-1", "cond_2")
        sig2.trade["_usd_value"] = 3000
        theses = build_theses_payload([sig1, sig2], [])
        assert theses[0]["total_usd"] == 5000.0


if __name__ == "__main__":
    unittest.main()
