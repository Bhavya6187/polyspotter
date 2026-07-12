"""
Tests for the pre-LLM gate in llm_filter.filter_alerts.

Backtest-derived policy (see STRATEGY_USAGE_REPORT.md addenda): alerts that
are cheap to identify as junk are auto-discarded locally without a GPT call.
The 2026-07 backtest removed the sharp-wallet exemption (the sharp cohort
underperforms non-sharp under every definition tested) and tightened the
tiers.

Gate A: composite_score < GATE_MIN_SCORE (3.0 on the 2026-07
        compute_composite_score scale, ≈ old severity-sum 4.0; that tier's
        LLM keep rate was 21%).
Gate B: all signals from a single weak strategy (price_impact,
        low_activity_large_bet, pre_event_volume_spike,
        correlated_cross_market, timing_relative_resolution,
        new_wallet_large_bet, concentrated_one_sided).
Gate J: recurring-crypto junk tags (same JUNK_TAGS set the public
        scoreboard excludes in backend/grading.py).
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

NEGATIVE_PNL = {
    "total_positions": 60,
    "closed_positions": 50,
    "wins": 25,
    "losses": 25,
    "total_pnl": -80_000.0,
    "total_invested": 900_000.0,
    "edge": -0.05,
    "avg_closed_price": 0.55,
    "avg_win_price": 0.55,
    "avg_loss_price": 0.60,
}

INTERESTING_RESULT = {
    "interesting": True,
    "summary": "test summary",
    "headline": "test headline",
    "bullets": ["b1", "b2"],
    "copy_action": {"outcome": "Yes", "side": "BUY", "entry_price": 0.5, "max_price": 0.6},
}


def _alert(score, strategies, dedup_key="dk-test", wallet="0xabc", tags=None):
    return {
        "alert_type": "composite",
        "composite_score": score,
        "market_title": "Test Market",
        "condition_id": "cond-test",
        "tags": tags or ["Sports"],
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


class _GateTestBase(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"),
            patch.object(llm_filter, "get_llm_evaluation", return_value=None),
            # keep the market-day cap out of the way (and off the real db)
            patch.object(llm_filter, "get_market_eval_count", return_value=0),
            patch.object(llm_filter, "increment_market_eval_count"),
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


class TestPreLLMGate(_GateTestBase):
    # --- Gate A: low composite score ---

    def test_low_score_discarded_without_llm_call(self):
        self._patch_pnl(DULL_PNL)
        alerts = [_alert(2.5, ["win_rate_tracking", "price_impact"])]
        kept = filter_alerts(alerts)
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_sharp_wallet_no_longer_exempts_low_score(self):
        # 2026-07 backtest: the sharp cohort underperforms non-sharp under
        # every definition tested; exemption survivors kept at 93% and added
        # no copy value. Sharp wallets no longer bypass the gate.
        self._patch_pnl(SHARP_PNL)
        alerts = [_alert(2.5, ["win_rate_tracking", "price_impact"])]
        kept = filter_alerts(alerts)
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_gated_discard_is_cached_as_not_interesting(self):
        self._patch_pnl(DULL_PNL)
        filter_alerts([_alert(1.5, ["price_impact"], dedup_key="dk-gated")])
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
            "new_wallet_large_bet",     # 44.6% keep, solo graded -4.9% (2026-07)
            "concentrated_one_sided",   # 42.5% keep, solo graded -13.3% (2026-07)
        ):
            with self.subTest(strategy=strategy):
                self.llm_calls.clear()
                kept = filter_alerts([_alert(4.5, [strategy])])
                self.assertEqual(kept, [])
                self.assertEqual(self.llm_calls, [])

    def test_solo_correlated_with_sharp_wallet_still_gated(self):
        self._patch_pnl(SHARP_PNL)
        kept = filter_alerts([_alert(4.5, ["correlated_cross_market"])])
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_multi_strategy_above_score_not_gated(self):
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts(
            [_alert(4.5, ["correlated_cross_market", "win_rate_tracking"])]
        )
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_solo_win_rate_tracking_not_gated(self):
        # Solo win_rate_tracking keeps at 95% and graded +3.4% — stays evaluable.
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts([_alert(5.5, ["win_rate_tracking"])])
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    # --- Gate J: recurring-crypto junk tags ---

    def test_junk_tagged_alert_discarded_without_llm_call(self):
        self._patch_pnl(DULL_PNL)
        for tag in ("Up or Down", "Bitcoin", "Recurring", "Hide From New"):
            with self.subTest(tag=tag):
                self.llm_calls.clear()
                kept = filter_alerts(
                    [_alert(6.5, ["win_rate_tracking", "price_impact"],
                            tags=["Crypto Prices", tag])]
                )
                self.assertEqual(kept, [])
                self.assertEqual(self.llm_calls, [])

    def test_junk_discard_is_cached(self):
        self._patch_pnl(DULL_PNL)
        filter_alerts([_alert(6.5, ["win_rate_tracking", "price_impact"],
                              dedup_key="dk-junk", tags=["Bitcoin"])])
        key, interesting, summary = self.saves[0]
        self.assertEqual(key, "dk-junk")
        self.assertFalse(interesting)
        self.assertIn("auto-discarded", summary)

    def test_non_junk_tags_not_gated(self):
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts(
            [_alert(6.5, ["win_rate_tracking", "price_impact"],
                    tags=["Sports", "NBA"])]
        )
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_missing_tags_tolerated(self):
        self._patch_pnl(DULL_PNL)
        alert = _alert(6.5, ["win_rate_tracking", "price_impact"])
        del alert["tags"]
        kept = filter_alerts([alert])
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


class TestNegativePnlGate(_GateTestBase):
    """Gate N (2026-07-11 backtest): alerts where every wallet with resolved
    history has negative lifetime P&L, with no win_rate_tracking signal and
    below whale size, keep at 7.9% (n=443 over Jul 5-11; 5-13% by day) —
    the LLM already rejects ~92% of them. Auto-discard locally instead."""

    # a weak pair passes Gates A/B/J so only the new gate can fire
    STRATS = ["correlated_cross_market", "pre_event_volume_spike"]

    def test_all_negative_pnl_discarded_without_llm_call(self):
        self._patch_pnl(NEGATIVE_PNL)
        kept = filter_alerts([_alert(5.0, self.STRATS)])
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])

    def test_negative_pnl_discard_is_cached_as_not_interesting(self):
        self._patch_pnl(NEGATIVE_PNL)
        filter_alerts([_alert(5.0, self.STRATS, dedup_key="dk-neg")])
        self.assertEqual(len(self.saves), 1)
        key, interesting, _ = self.saves[0]
        self.assertEqual(key, "dk-neg")
        self.assertFalse(interesting)

    def test_win_rate_signal_exempts_negative_pnl(self):
        self._patch_pnl(NEGATIVE_PNL)
        kept = filter_alerts([_alert(5.0, self.STRATS + ["win_rate_tracking"])])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(self.llm_calls), 1)

    def test_whale_alert_exempts_negative_pnl(self):
        self._patch_pnl(NEGATIVE_PNL)
        alert = _alert(5.0, self.STRATS)
        alert["total_usd"] = llm_filter.NEG_PNL_EXEMPT_USD
        kept = filter_alerts([alert])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(self.llm_calls), 1)

    def test_positive_pnl_wallet_not_gated(self):
        self._patch_pnl(SHARP_PNL)
        kept = filter_alerts([_alert(5.0, self.STRATS)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(self.llm_calls), 1)

    def test_no_history_wallets_not_gated(self):
        # unknown is not negative — a wallet with no resolved positions
        # must not trip the gate
        self._patch_pnl(DULL_PNL)
        kept = filter_alerts([_alert(5.0, self.STRATS)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(self.llm_calls), 1)

    def test_mixed_history_gates_on_wallets_with_history_only(self):
        # one wallet with negative history + one with none -> gated (the
        # no-history wallet carries no information either way)
        alert = _alert(5.0, self.STRATS, wallet="0xneg")
        alert["trades"].append(
            {"wallet": "0xfresh", "usd_value": 100.0, "price": 0.5,
             "outcome": "Yes", "side": "BUY"}
        )
        by_wallet = {"0xneg": NEGATIVE_PNL, "0xfresh": DULL_PNL}
        p = patch.object(
            llm_filter, "get_wallet_pnl_summary",
            side_effect=lambda w: by_wallet.get(w.lower(), DULL_PNL),
        )
        p.start()
        self.addCleanup(p.stop)
        kept = filter_alerts([alert])
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])


class TestMarketDayCap(unittest.TestCase):
    """Per-market-day evaluation cap (2026-07): a market that already burned
    MARKET_DAY_EVAL_CAP GPT calls today gets no more until tomorrow — the
    backtest showed keep rate is flat (~82%) by nth same-day call, so the
    marginal evaluation adds nothing. Deferred alerts are NOT cached (they
    stay eligible after midnight UTC or once the cluster grows). Alerts with
    total_usd >= MARKET_DAY_CAP_EXEMPT_USD bypass the cap so a genuine new
    whale on a hot market still gets evaluated."""

    def setUp(self):
        self.counts = {}
        patches = [
            patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"),
            patch.object(llm_filter, "get_llm_evaluation", return_value=None),
            patch.object(llm_filter, "get_wallet_pnl_summary", return_value=DULL_PNL),
            patch.object(
                llm_filter, "get_market_eval_count",
                side_effect=lambda cid, day: self.counts.get(cid, 0),
            ),
            patch.object(
                llm_filter, "increment_market_eval_count",
                side_effect=lambda cid, day: self.counts.__setitem__(
                    cid, self.counts.get(cid, 0) + 1
                ),
            ),
        ]
        self.saves = []
        patches.append(
            patch.object(
                llm_filter, "save_llm_evaluation",
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

    def _ok_alert(self, dedup_key, usd=5000.0):
        a = _alert(6.5, ["win_rate_tracking", "price_impact"], dedup_key=dedup_key)
        a["total_usd"] = usd
        return a

    def test_capped_market_deferred_without_llm_call_and_not_cached(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP
        kept = filter_alerts([self._ok_alert("dk-capped")])
        self.assertEqual(kept, [])
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.saves, [])  # deferred, not cached as a verdict

    def test_under_cap_evaluated_and_counted(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP - 1
        kept = filter_alerts([self._ok_alert("dk-under")])
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(self.counts["cond-test"], llm_filter.MARKET_DAY_EVAL_CAP)

    def test_whale_alert_bypasses_cap(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP
        kept = filter_alerts(
            [self._ok_alert("dk-whale", usd=llm_filter.MARKET_DAY_CAP_EXEMPT_USD)]
        )
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)

    def test_in_batch_calls_count_toward_cap(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP - 2
        alerts = [self._ok_alert(f"dk-batch-{n}") for n in range(4)]
        kept = filter_alerts(alerts)
        self.assertEqual(len(self.llm_calls), 2)
        self.assertEqual(len(kept), 2)

    def test_cached_verdicts_not_affected_by_cap(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP
        cached = {
            "interesting": True,
            "summary": json.dumps(
                {"summary": "s", "headline": "h", "bullets": [], "copy_action": {}}
            ),
        }
        p = patch.object(llm_filter, "get_llm_evaluation", return_value=cached)
        p.start()
        self.addCleanup(p.stop)
        kept = filter_alerts([self._ok_alert("dk-cached")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(self.llm_calls, [])

    def test_missing_condition_id_not_capped(self):
        self.counts["cond-test"] = llm_filter.MARKET_DAY_EVAL_CAP
        alert = self._ok_alert("dk-nocid")
        del alert["condition_id"]
        kept = filter_alerts([alert])
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
