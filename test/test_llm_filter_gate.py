"""
Tests for the pre-LLM gate in llm_filter.filter_alerts.

Backtest-derived policy (see STRATEGY_USAGE_REPORT.md addendum): alerts that
are cheap to identify as junk are auto-discarded locally without a GPT call —
unless a sharp wallet (>=75% win rate on 10+ resolved, positive P&L) is
involved, mirroring the LLM prompt's own sharp-wallet override.

Gate A: composite_score < 3 with no sharp wallet.
Gate B: all signals from a single weak strategy (price_impact,
        low_activity_large_bet, pre_event_volume_spike,
        correlated_cross_market, timing_relative_resolution)
        with no sharp wallet.
"""

import json
import unittest
from unittest.mock import patch

import llm_filter
from llm_filter import filter_alerts


SHARP_PNL = {
    "total_positions": 25,
    "closed_positions": 20,
    "wins": 18,
    "losses": 2,
    "total_pnl": 50_000.0,
    "total_invested": 100_000.0,
    "edge": 0.35,
    "avg_closed_price": 0.55,
    "avg_win_price": 0.55,
    "avg_loss_price": 0.60,
}

DULL_PNL = {
    "total_positions": 0,
    "closed_positions": 0,
    "wins": 0,
    "losses": 0,
    "total_pnl": 0.0,
    "total_invested": 0.0,
    "edge": 0.0,
    "avg_closed_price": 0.0,
    "avg_win_price": 0.0,
    "avg_loss_price": 0.0,
}

INTERESTING_RESULT = {
    "interesting": True,
    "summary": "test summary",
    "headline": "test headline",
    "bullets": ["b1", "b2"],
    "copy_action": {"outcome": "Yes", "side": "BUY", "entry_price": 0.5, "max_price": 0.6},
}


def _alert(score, strategies, dedup_key="dk-test", wallet="0xabc"):
    return {
        "alert_type": "composite",
        "composite_score": score,
        "market_title": "Test Market",
        "total_usd": 5000.0,
        "trade_count": 1,
        "wallet": wallet,
        "dedup_key": dedup_key,
        "trades": [
            {
                "wallet": wallet,
                "usd_value": 5000.0,
                "price": 0.5,
                "outcome": "Yes",
                "side": "BUY",
            }
        ],
        "signals": [
            {"strategy": s, "severity": 1.0, "headline": "h"} for s in strategies
        ],
    }


class TestPreLLMGate(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"),
            patch.object(llm_filter, "get_llm_evaluation", return_value=None),
        ]
        self.saves = []
        patches.append(
            patch.object(
                llm_filter,
                "save_llm_evaluation",
                side_effect=lambda key, interesting, summary: self.saves.append(
                    (key, interesting, summary)
                ),
            )
        )
        self.llm_calls = []

        def fake_evaluate(alert, alert_text=None):
            self.llm_calls.append(alert)
            return dict(INTERESTING_RESULT)

        patches.append(patch.object(llm_filter, "evaluate_alert", fake_evaluate))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _patch_pnl(self, pnl):
        p = patch.object(llm_filter, "get_wallet_pnl_summary", return_value=pnl)
        p.start()
        self.addCleanup(p.stop)

    # --- Gate A: low composite score ---

    def test_low_score_no_sharp_wallet_discarded_without_llm_call(self):
        self._patch_pnl(DULL_PNL)
        alerts = [_alert(2.5, ["win_rate_tracking", "price_impact"])]
        kept = filter_alerts(alerts)
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_low_score_with_sharp_wallet_goes_to_llm(self):
        self._patch_pnl(SHARP_PNL)
        alerts = [_alert(2.5, ["win_rate_tracking", "price_impact"])]
        kept = filter_alerts(alerts)
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_gated_discard_is_cached_as_not_interesting(self):
        self._patch_pnl(DULL_PNL)
        filter_alerts([_alert(2.5, ["price_impact"], dedup_key="dk-gated")])
        self.assertEqual(len(self.saves), 1)
        key, interesting, summary = self.saves[0]
        self.assertEqual(key, "dk-gated")
        self.assertFalse(interesting)
        self.assertIn("auto-discarded", summary)

    # --- Gate B: weak solo strategies ---

    def test_solo_correlated_no_sharp_discarded_without_llm_call(self):
        self._patch_pnl(DULL_PNL)
        alerts = [_alert(4.5, ["correlated_cross_market"])]
        kept = filter_alerts(alerts)
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_solo_weak_strategies_discarded_without_llm_call(self):
        self._patch_pnl(DULL_PNL)
        for strategy in (
            "price_impact",
            "low_activity_large_bet",
            "pre_event_volume_spike",
            "timing_relative_resolution",
        ):
            with self.subTest(strategy=strategy):
                self.llm_calls.clear()
                kept = filter_alerts([_alert(4.5, [strategy])])
                self.assertEqual(kept, [])
                self.assertEqual(self.llm_calls, [])

    def test_solo_correlated_with_sharp_wallet_goes_to_llm(self):
        self._patch_pnl(SHARP_PNL)
        kept = filter_alerts([_alert(4.5, ["correlated_cross_market"])])
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_multi_strategy_above_score_not_gated(self):
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts(
            [_alert(4.5, ["correlated_cross_market", "win_rate_tracking"])]
        )
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_solo_strong_strategy_not_gated(self):
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts([_alert(5.5, ["new_wallet_large_bet"])])
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    # --- Cache interaction ---

    def test_cached_verdict_bypasses_gate(self):
        self._patch_pnl(DULL_PNL)
        cached = {
            "interesting": True,
            "summary": json.dumps(
                {"summary": "s", "headline": "h", "bullets": [], "copy_action": {}}
            ),
        }
        with patch.object(llm_filter, "get_llm_evaluation", return_value=cached):
            kept = filter_alerts([_alert(2.5, ["price_impact"])])
        self.assertEqual(len(kept), 1)
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.saves, [])


if __name__ == "__main__":
    unittest.main()
