import unittest
from unittest.mock import patch

from detection_strategies.correlated_cross_market import CorrelatedCrossMarketStrategy


@patch(
    "detection_strategies.correlated_cross_market.get_wallet_cross_event_stats",
    return_value={"distinct_events": 0, "distinct_markets": 0, "total_usd": 0, "total_trades": 0},
)
@patch("detection_strategies.correlated_cross_market.get_wallet_event_history", return_value=[])
@patch("detection_strategies.correlated_cross_market.record_wallet_event_trade")
@patch("detection_strategies.correlated_cross_market.is_sport_market", return_value=False)
@patch("detection_strategies.correlated_cross_market.get_market_by_condition", return_value=None)
class TestCorrelatedCrossMarketStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = CorrelatedCrossMarketStrategy()

    def _make_trade(self, wallet, event_slug, cid, usd=1500, side="BUY", price=0.50):
        return {
            "proxyWallet": wallet,
            "eventSlug": event_slug,
            "conditionId": cid,
            "_usd_value": usd,
            "side": side,
            "price": price,
            "transactionHash": f"0xtx_{wallet}_{cid}",
        }

    def test_check_trade_always_none(self, *mocks):
        trade = self._make_trade("w1", "event1", "cond1")
        self.assertIsNone(self.strategy.check_trade(trade))

    def test_empty_trades_returns_empty(self, *mocks):
        self.assertEqual(self.strategy.analyze_all([]), [])

    def test_single_market_no_signal(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_two_markets_below_min_usd_no_signal(self, *mocks):
        """2 markets but combined USD below MIN_TOTAL_USD = no signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=900, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=900, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_two_markets_above_min_usd_triggers(self, *mocks):
        """2 markets with combined USD >= MIN_TOTAL_USD triggers signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].strategy, "correlated_cross_market")
        self.assertIn("2 markets", signals[0].headline)

    def test_below_min_usd_no_signal(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=500),
            self._make_trade("w1", "event1", "cond2", usd=500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_events_separate(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500),
            self._make_trade("w1", "event2", "cond2", usd=1500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_different_wallets_separate(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=1500),
            self._make_trade("w2", "event1", "cond2", usd=1500),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_three_markets_triggers(self, *mocks):
        """3 markets above threshold triggers signal."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond3", usd=2000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 markets", signals[0].headline)
        self.assertEqual(signals[0].severity, 1.0)

    def test_high_usd_higher_severity(self, *mocks):
        """Higher combined USD produces higher severity."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=15000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=15000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 3.0)

    def test_trade_hashes_collected(self, *mocks):
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals[0].trade_hashes), 2)

    def test_resolved_price_trades_filtered(self, *mocks):
        """Trades at near-certain prices (>= 0.98) should be excluded."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY", price=0.99),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL", price=0.99),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_sports_event_needs_three_markets(
        self, mock_get_mkt, mock_is_sport, *mocks
    ):
        """Sports events require 3 markets, not 2."""
        mock_get_mkt.return_value = {"id": "123"}
        mock_is_sport.return_value = True
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        signals = self.strategy.analyze_all(trades)
        # 2 markets on a sport event = no signal
        self.assertEqual(len(signals), 0)

    def test_sports_event_three_markets_triggers(
        self, mock_get_mkt, mock_is_sport, *mocks
    ):
        """Sports events with 3+ markets should trigger."""
        mock_get_mkt.return_value = {"id": "123"}
        mock_is_sport.return_value = True
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=2000, side="BUY"),
            self._make_trade("w1", "event1", "cond3", usd=2000, side="BUY"),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 markets", signals[0].headline)

    def test_serial_severity_skipped_for_weak_win_rate(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market with no/weak win rate should be skipped entirely."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
        ]
        # With no win rate data, serial signal should not be emitted
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 0, "wins": 0, "total_pnl": 0, "total_invested": 0},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 0)

    def test_serial_severity_high_win_rate(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market with 75% win rate should get severity 4.0."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 20, "wins": 15, "total_pnl": 5000, "total_invested": 10000},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 1)
            self.assertEqual(serial_sigs[0].severity, 4.0)

    def test_win_rate_boost_requires_ten_closed(self, *mocks):
        """Win rate boost should require 10+ closed positions, not just 5."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY"),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL"),
        ]
        # 7 closed positions with 100% win rate — should NOT get boost
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 7, "wins": 7, "total_pnl": 5000, "total_invested": 3000},
        ):
            signals = self.strategy.analyze_all(trades)
            self.assertEqual(len(signals), 1)
            # Base severity for $6k is 1.0, no boost
            self.assertEqual(signals[0].severity, 1.0)


    def test_historical_trades_push_market_count(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Historical trades from prior runs push market count to meet MIN_MARKETS."""
        mock_hist.return_value = [
            {"condition_id": "cond_hist", "usd_value": 3000},
        ]
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertIn("from prior runs", signals[0].headline)

    def test_historical_usd_contributes_to_threshold(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Historical USD from prior runs contributes to MIN_TOTAL_USD threshold."""
        mock_hist.return_value = [
            {"condition_id": "cond3", "usd_value": 2000},
        ]
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=2000),
            self._make_trade("w1", "event1", "cond2", usd=1500),
        ]
        signals = self.strategy.analyze_all(trades)
        # current=$3500 < 5000, but combined with historical $2000 = $5500 >= 5000
        self.assertEqual(len(signals), 1)

    def test_win_rate_boost_positive_path(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Win rate boost of +2.0 when closed_positions >= 10 and win_pct >= 65%."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
            self._make_trade("w1", "event1", "cond2", usd=3000),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 15, "wins": 11, "total_pnl": 5000, "total_invested": 10000},
        ):
            signals = self.strategy.analyze_all(trades)
            self.assertEqual(len(signals), 1)
            # Base severity for $6k = 1.0, boost +2.0 = 3.0
            self.assertEqual(signals[0].severity, 3.0)
            self.assertIn("win rate", signals[0].headline)

    def test_severity_10k_tier(self, *mocks):
        """Combined USD >= $10k should give severity 2.0."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=6000),
            self._make_trade("w1", "event1", "cond2", usd=6000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 2.0)

    def test_severity_50k_tier(self, *mocks):
        """Combined USD >= $50k should give severity 4.0."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=30000),
            self._make_trade("w1", "event1", "cond2", usd=30000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 4.0)

    def test_serial_severity_mid_win_rate_60pct(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market with 65% win rate (>= 60%) should get severity 3.0."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 20, "wins": 13, "total_pnl": 5000, "total_invested": 10000},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 1)
            self.assertEqual(serial_sigs[0].severity, 3.0)

    def test_serial_severity_low_win_rate_55pct(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial cross-market with 55% win rate (>= 55%) should get severity 2.0."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 20, "wins": 11, "total_pnl": 3000, "total_invested": 10000},
        ):
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            self.assertEqual(len(serial_sigs), 1)
            self.assertEqual(serial_sigs[0].severity, 2.0)

    def test_record_wallet_event_trade_skips_resolved(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """record_wallet_event_trade should only be called for active trades, not near-resolved ones."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, price=0.50),
            self._make_trade("w1", "event1", "cond2", usd=3000, price=0.99),
        ]
        self.strategy.analyze_all(trades)
        self.assertEqual(mock_record.call_count, 1)


    def test_sell_at_0_02_filtered(self, *mocks):
        """SELL trade at price 0.02 should be filtered (complement of BUY >= 0.98)."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="SELL", price=0.02),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL", price=0.02),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_sell_at_0_03_not_filtered(self, *mocks):
        """SELL trade at price 0.03 should NOT be filtered (above the 0.02 complement threshold)."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="SELL", price=0.03),
            self._make_trade("w1", "event1", "cond2", usd=3000, side="SELL", price=0.03),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)

    def test_empty_wallet_skipped(self, *mocks):
        """Trade with empty proxyWallet should be skipped in wallet grouping."""
        trades = [
            {
                "proxyWallet": "",
                "eventSlug": "event1",
                "conditionId": "cond1",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                "transactionHash": "0xtx_empty_cond1",
            },
            {
                "proxyWallet": "",
                "eventSlug": "event1",
                "conditionId": "cond2",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                "transactionHash": "0xtx_empty_cond2",
            },
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_empty_event_slug_skipped(self, *mocks):
        """Trade with empty eventSlug should be skipped in wallet grouping."""
        trades = [
            {
                "proxyWallet": "w1",
                "eventSlug": "",
                "conditionId": "cond1",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                "transactionHash": "0xtx_w1_cond1",
            },
            {
                "proxyWallet": "w1",
                "eventSlug": "",
                "conditionId": "cond2",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                "transactionHash": "0xtx_w1_cond2",
            },
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 0)

    def test_severity_boundary_exactly_10k(self, *mocks):
        """Combined USD exactly $10,000 should get severity 2.0 (>= $10k tier)."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=5000),
            self._make_trade("w1", "event1", "cond2", usd=5000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 2.0)

    def test_severity_boundary_exactly_20k(self, *mocks):
        """Combined USD exactly $20,000 should get severity 3.0 (>= $20k tier)."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=10000),
            self._make_trade("w1", "event1", "cond2", usd=10000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 3.0)

    def test_severity_boundary_exactly_50k(self, *mocks):
        """Combined USD exactly $50,000 should get severity 4.0 (>= $50k tier)."""
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=25000),
            self._make_trade("w1", "event1", "cond2", usd=25000),
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].severity, 4.0)

    def test_missing_transaction_hash(self, *mocks):
        """Trades without transactionHash should still produce a signal, just with fewer hashes."""
        trades = [
            {
                "proxyWallet": "w1",
                "eventSlug": "event1",
                "conditionId": "cond1",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                # no transactionHash key
            },
            {
                "proxyWallet": "w1",
                "eventSlug": "event1",
                "conditionId": "cond2",
                "_usd_value": 3000,
                "side": "BUY",
                "price": 0.50,
                # no transactionHash key
            },
        ]
        signals = self.strategy.analyze_all(trades)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].trade_hashes, [])

    def test_serial_no_active_trades(
        self, mock_get_mkt, mock_is_sport, mock_record, mock_hist, mock_stats
    ):
        """Serial trader with historical events but no current-window trades should not crash."""
        mock_stats.return_value = {
            "distinct_events": 30,
            "distinct_markets": 50,
            "total_usd": 100_000,
            "total_trades": 60,
        }
        # All trades are near-resolved (filtered out), so active_trades is empty for this wallet
        trades = [
            self._make_trade("w1", "event1", "cond1", usd=3000, side="BUY", price=0.99),
        ]
        with patch(
            "detection_strategies.correlated_cross_market.get_wallet_pnl_summary",
            return_value={"closed_positions": 20, "wins": 15, "total_pnl": 5000, "total_invested": 10000},
        ):
            # Should not raise any exception
            signals = self.strategy.analyze_all(trades)
            serial_sigs = [s for s in signals if "Serial" in s.headline]
            # rep_trade will be None since no active trades match wallet, so serial signal is skipped
            self.assertEqual(len(serial_sigs), 0)


if __name__ == "__main__":
    unittest.main()
