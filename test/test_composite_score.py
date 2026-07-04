"""
Tests for compute_composite_score (2026-07 rescore).

Backtest-derived aggregation (see STRATEGY_USAGE_REPORT.md): per-strategy max
severity (no same-strategy stacking), backtest weights, then a diminishing sum
(1, 1/2, 1/4, ...) of per-strategy contributions, strongest first. Replaced
the raw severity sum, which was non-monotonic with graded copy returns.
"""

import unittest

from detection_strategies import STRATEGY_WEIGHTS, Signal, compute_composite_score


def _sig(strategy, severity, headline="h"):
    return Signal(strategy=strategy, severity=severity, headline=headline, trade={})


class TestComputeCompositeScore(unittest.TestCase):
    def test_empty_signals_scores_zero(self):
        self.assertEqual(compute_composite_score([]), 0.0)

    def test_single_signal_is_weighted_severity(self):
        score = compute_composite_score([_sig("concentrated_one_sided", 5.0)])
        self.assertAlmostEqual(score, 5.0)

    def test_same_strategy_signals_do_not_stack(self):
        # Two correlated_cross_market signals: only the strongest counts.
        sigs = [
            _sig("correlated_cross_market", 3.0, "108 events"),
            _sig("correlated_cross_market", 2.0, "33 events"),
        ]
        self.assertAlmostEqual(compute_composite_score(sigs), 3.0)

    def test_cross_strategy_contributions_diminish(self):
        # Equal-weight strategies at severity 4: 4 + 4/2 = 6.
        sigs = [
            _sig("concentrated_one_sided", 4.0),
            _sig("correlated_cross_market", 4.0),
        ]
        self.assertAlmostEqual(compute_composite_score(sigs), 6.0)

    def test_price_impact_weighted_up(self):
        score = compute_composite_score([_sig("price_impact", 4.0)])
        self.assertAlmostEqual(score, 4.0 * STRATEGY_WEIGHTS["price_impact"])
        self.assertGreater(score, 4.0)

    def test_negative_backtest_strategies_weighted_down(self):
        for strategy in (
            "new_wallet_large_bet",
            "pre_event_volume_spike",
            "win_rate_tracking",
            "low_activity_large_bet",
        ):
            with self.subTest(strategy=strategy):
                score = compute_composite_score([_sig(strategy, 4.0)])
                self.assertLess(score, 4.0)

    def test_unknown_strategy_defaults_to_weight_one(self):
        self.assertAlmostEqual(
            compute_composite_score([_sig("brand_new_strategy", 3.0)]), 3.0
        )

    def test_strongest_contribution_leads_the_diminishing_sum(self):
        # weighted: price_impact 5*1.3=6.5, win_rate 6*0.7=4.2, low_activity 2*0.7=1.4
        sigs = [
            _sig("price_impact", 5.0),
            _sig("win_rate_tracking", 6.0),
            _sig("low_activity_large_bet", 2.0),
        ]
        expected = 6.5 + 4.2 / 2 + 1.4 / 4
        self.assertAlmostEqual(compute_composite_score(sigs), expected)

    def test_all_strategies_have_explicit_weights(self):
        expected = {
            "price_impact", "correlated_cross_market", "concentrated_one_sided",
            "wallet_clustering", "new_wallet_large_bet", "pre_event_volume_spike",
            "win_rate_tracking", "low_activity_large_bet", "timing_relative_resolution",
        }
        self.assertEqual(set(STRATEGY_WEIGHTS), expected)


if __name__ == "__main__":
    unittest.main()
