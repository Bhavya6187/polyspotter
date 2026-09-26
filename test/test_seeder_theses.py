"""
Tests for seeder thesis-building and resolution-checking logic.
"""

import unittest
from unittest.mock import MagicMock, patch

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


class TestThesesOnlyForKeptAlerts(unittest.TestCase):
    """A correlated_cross_market group whose alert the gate/LLM discarded must
    not produce a thesis (nor a GPT headline call)."""

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_build_skips_groups_without_kept_alert(self, mock_market, mock_history):
        signals = [
            FakeSignal("correlated_cross_market", "0xKEEP", "event-1", "cond_1"),
            FakeSignal("correlated_cross_market", "0xdrop", "event-2", "cond_2"),
        ]
        theses = build_theses_payload(signals, [], kept_wallet_events={("0xkeep", "event-1")})
        assert [(t["wallet"], t["event_slug"]) for t in theses] == [("0xkeep", "event-1")]

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_theses_built_only_for_kept_alerts(self, mock_market, mock_history):
        import seeder

        signals = [
            FakeSignal("correlated_cross_market", "0xkeep", "event-1", "cond_1"),
            FakeSignal("correlated_cross_market", "0xdrop", "event-2", "cond_2"),
        ]
        kept = {"alert_type": "composite", "wallet": "0xKeep", "event_slug": "event-1",
                "condition_id": "cond_1", "dedup_key": "k",
                "trades": [{"wallet": "0xKeep", "condition_id": "cond_1"}]}
        dropped = {"alert_type": "composite", "wallet": "0xdrop", "event_slug": "event-2",
                   "condition_id": "cond_2", "dedup_key": "d",
                   "trades": [{"wallet": "0xdrop", "condition_id": "cond_2"}]}
        post = MagicMock()
        post.return_value.json.return_value = {}
        headline = MagicMock(return_value="Keep wins")
        with patch("seeder.build_alerts_payload",
                   return_value={"alerts": [kept, dropped], "wallet_profiles": []}), \
             patch("llm_filter.filter_alerts",
                   side_effect=lambda alerts: [a for a in alerts if a["dedup_key"] == "k"]), \
             patch("db.get_recent_price_candles", return_value=[]), \
             patch("seeder._generate_thesis_headline", headline), \
             patch("seeder.requests.post", post):
            seeder.push_to_backend(signals, [])

        payload = post.call_args.kwargs["json"]
        assert [(t["wallet"], t["event_slug"]) for t in payload["theses"]] == [("0xkeep", "event-1")]
        assert headline.call_count == 1

    @patch("db.get_wallet_event_history", return_value=[])
    @patch("gamma_cache.get_market_by_condition", return_value={"title": "Test"})
    def test_wallet_inside_kept_cluster_alert_keeps_its_thesis(self, mock_market, mock_history):
        from seeder import _kept_wallet_events

        cluster = {"alert_type": "cluster", "wallet": None, "event_slug": "event-1",
                   "trades": [{"wallet": "0xAbc"}, {"wallet": "0xdef"}]}
        assert _kept_wallet_events([cluster]) == {("0xabc", "event-1"), ("0xdef", "event-1")}


if __name__ == "__main__":
    unittest.main()
