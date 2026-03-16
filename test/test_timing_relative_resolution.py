import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from detection_strategies.timing_relative_resolution import (
    TimingRelativeResolutionStrategy,
    _is_sport_by_slug,
    detect_sport,
    CLOSE_MINUTES,
    SPORT_CLOSE_MINUTES,
    NON_SPORT_SEVERITY_BOOST,
)


EMPTY_TIMING_STATS = {
    "total_flags": 0, "distinct_markets": 0,
    "avg_minutes": 0, "min_minutes": 0, "total_usd": 0,
}

EMPTY_PNL = {
    "total_positions": 0, "closed_positions": 0,
    "wins": 0, "losses": 0, "total_pnl": 0,
    "total_invested": 0, "edge": 0.0, "avg_closed_price": 0,
    "avg_win_price": 0, "avg_loss_price": 0,
}


@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_pnl_summary",
    return_value=EMPTY_PNL,
)
@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_timing_stats",
    return_value=EMPTY_TIMING_STATS,
)
@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
@patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
class TestTimingRelativeResolutionStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    def _make_trade(self, cid="cond_1", ts=1700000000, event_slug=""):
        return {
            "conditionId": cid,
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": ts,
            "eventSlug": event_slug,
        }

    def test_no_condition_id_returns_none(self, *mocks):
        trade = {"_usd_value": 5000, "timestamp": 1700000000}
        self.assertIsNone(self.strategy.check_trade(trade))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_market_not_found_returns_none(self, mock_market, *mocks):
        mock_market.return_value = None
        self.assertIsNone(self.strategy.check_trade(self._make_trade()))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_no_end_date_returns_none(self, mock_market, *mocks):
        mock_market.return_value = {"endDate": None}
        self.assertIsNone(self.strategy.check_trade(self._make_trade()))

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_close_to_resolution_triggers(self, mock_market, *mocks):
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "timing_relative_resolution")
        self.assertIn("min before resolution", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_far_from_resolution_no_signal(self, mock_market, *mocks):
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 7200, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_trade_after_resolution_no_signal(self, mock_market, *mocks):
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts - 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_severity_higher_when_closer(self, mock_market, *mocks):
        trade_ts = 1700000000
        end_1min = datetime.fromtimestamp(trade_ts + 60, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_1min.isoformat()}
        result_close = self.strategy.check_trade(self._make_trade(ts=trade_ts))

        end_50min = datetime.fromtimestamp(trade_ts + 3000, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_50min.isoformat()}
        result_far = self.strategy.check_trade(self._make_trade(ts=trade_ts))

        self.assertGreater(result_close.severity, result_far.severity)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_non_sport_base_severity_capped_at_7(self, mock_market, *mocks):
        """Non-sport: base 5.0 + 1.5 boost = 6.5, capped at 7.0."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        result = self.strategy.check_trade(self._make_trade(ts=trade_ts))
        self.assertIsNotNone(result)
        self.assertLessEqual(result.severity, 7.0)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_short_duration_market_suppressed(self, mock_market, *mocks):
        """Short-duration markets (< 2h) should return None."""
        trade_ts = 1700000000
        start_dt = datetime.fromtimestamp(trade_ts - 25 * 60, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(trade_ts + 5 * 60, tz=timezone.utc)
        mock_market.return_value = {
            "startDate": start_dt.isoformat(),
            "endDate": end_dt.isoformat(),
        }
        result = self.strategy.check_trade(self._make_trade(ts=trade_ts))
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_long_duration_market_not_suppressed(self, mock_market, *mocks):
        """Markets >= 2h should still fire normally."""
        trade_ts = 1700000000
        start_dt = datetime.fromtimestamp(trade_ts - 230 * 60, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(trade_ts + 10 * 60, tz=timezone.utc)
        mock_market.return_value = {
            "startDate": start_dt.isoformat(),
            "endDate": end_dt.isoformat(),
        }
        result = self.strategy.check_trade(self._make_trade(ts=trade_ts))
        self.assertIsNotNone(result)
        self.assertIn("min before resolution", result.headline)


class TestSlugBasedSportDetection(unittest.TestCase):
    """Tests for _is_sport_by_slug fallback detection."""

    def test_nba_slug_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "nba-den-lal-2026-03-14"}))

    def test_mls_slug_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "mls-hou-por-2026-03-14"}))

    def test_nhl_slug_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "nhl-pit-utah-2026-03-14"}))

    def test_cbb_slug_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "cbb-vir-duke-2026-03-14"}))

    def test_nfl_slug_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "nfl-kc-buf-2026-01-20"}))

    def test_vs_pattern_detected(self):
        self.assertTrue(_is_sport_by_slug({"eventSlug": "penguins-vs-utah"}))

    def test_non_sport_slug_not_detected(self):
        self.assertFalse(_is_sport_by_slug({"eventSlug": "oscars-2026-best-actor-winner"}))

    def test_politics_slug_not_detected(self):
        self.assertFalse(_is_sport_by_slug({"eventSlug": "us-presidential-election-2028"}))

    def test_crypto_slug_not_detected(self):
        self.assertFalse(_is_sport_by_slug({"eventSlug": "btc-above-100k-march-2026"}))

    def test_empty_slug_not_detected(self):
        self.assertFalse(_is_sport_by_slug({"eventSlug": ""}))

    def test_missing_slug_not_detected(self):
        self.assertFalse(_is_sport_by_slug({}))


class TestDetectSport(unittest.TestCase):
    """Tests for detect_sport: API tags primary, slug fallback."""

    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
    def test_api_tag_identifies_sport(self, mock_api):
        """API tag '1' (Sports) should identify a sport market."""
        trade = {"eventSlug": "some-obscure-slug"}
        market = {"events": [{"id": "12345"}]}
        self.assertTrue(detect_sport(trade, market))

    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
    def test_slug_fallback_when_api_says_no(self, mock_api):
        """Slug fallback should detect sport when API tags miss it."""
        trade = {"eventSlug": "nba-den-lal-2026-03-14"}
        market = {}
        self.assertTrue(detect_sport(trade, market))

    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
    def test_non_sport_when_both_miss(self, mock_api):
        """Should return False when neither API nor slug detect sport."""
        trade = {"eventSlug": "oscars-2026-best-actor-winner"}
        market = {}
        self.assertFalse(detect_sport(trade, market))


@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_pnl_summary",
    return_value=EMPTY_PNL,
)
@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_timing_stats",
    return_value=EMPTY_TIMING_STATS,
)
@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
class TestSportWindowAndSeverity(unittest.TestCase):
    """Tests for sport-specific window and non-sport severity boost."""

    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
    def test_sport_trade_outside_5min_suppressed(self, mock_is_sport, mock_market, *mocks):
        """Sport market trade 10 min before resolution should be suppressed (> 5 min window)."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "nba-den-lal-2026-03-14",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
    def test_sport_trade_within_5min_fires(self, mock_is_sport, mock_market, *mocks):
        """Sport market trade 3 min before resolution should fire."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "nba-den-lal-2026-03-14",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("live sport", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
    def test_non_sport_gets_severity_boost(self, mock_is_sport, mock_market, *mocks):
        """Non-sport timing signal should get NON_SPORT_SEVERITY_BOOST added."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 600, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "oscars-2026-best-actor-winner",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Base severity at 10 min: 5.0 / (1 + 10*0.25) = 5.0/3.5 ~ 1.43
        # With boost: ~ 1.43 + 1.5 = 2.93
        self.assertGreater(result.severity, 2.5)
        self.assertNotIn("live sport", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
    def test_sport_no_severity_boost(self, mock_is_sport, mock_market, *mocks):
        """Sport timing signal should NOT get the non-sport boost."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "nba-den-lal-2026-03-14",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        # Base severity at 3 min: 5.0 / (1 + 3*0.25) = 5.0/1.75 ~ 2.86
        # No boost, so stays under 3.5
        self.assertLess(result.severity, 3.5)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
    def test_sport_base_severity_capped_at_5(self, mock_is_sport, mock_market, *mocks):
        """Sport: base severity capped at 5.0, no boost."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "nba-den-lal-2026-03-14",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertLessEqual(result.severity, 5.0)


@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
@patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
class TestSerialTimerRatioCap(unittest.TestCase):
    """Tests for serial timer ratio cap — routine live bettors shouldn't escalate."""

    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_pnl_summary")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_timing_stats")
    def test_routine_bettor_not_escalated(self, mock_stats, mock_pnl, mock_market, *mocks):
        """Wallet with >50% timing flags relative to positions should NOT get serial timer boost."""
        mock_stats.return_value = {
            "total_flags": 800, "distinct_markets": 40,
            "avg_minutes": 15, "min_minutes": 1, "total_usd": 500000,
        }
        mock_pnl.return_value = {
            **EMPTY_PNL,
            "total_positions": 1000,  # 800/1000 = 80% > 50% cap
        }
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "oscars-2026-best-actor-winner",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertNotIn("SERIAL TIMER", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_pnl_summary")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_timing_stats")
    def test_selective_timer_escalated(self, mock_stats, mock_pnl, mock_market, *mocks):
        """Wallet with <50% timing flags relative to positions AND >=75% win rate SHOULD get serial timer boost."""
        mock_stats.return_value = {
            "total_flags": 10, "distinct_markets": 5,
            "avg_minutes": 5, "min_minutes": 1, "total_usd": 50000,
        }
        mock_pnl.return_value = {
            **EMPTY_PNL,
            "total_positions": 100,  # 10/100 = 10% < 50% cap
            "closed_positions": 20, "wins": 16, "losses": 4,  # 80% win rate
            "total_pnl": 5000, "total_invested": 10000, "edge": 0.30,
        }
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "oscars-2026-best-actor-winner",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertIn("SERIAL TIMER", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_pnl_summary")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_timing_stats")
    def test_serial_timer_no_edge_not_escalated(self, mock_stats, mock_pnl, mock_market, *mocks):
        """Wallet meets timing threshold but has closed_positions=2 and edge=0.0 — should NOT get SERIAL TIMER."""
        mock_stats.return_value = {
            "total_flags": 10, "distinct_markets": 5,
            "avg_minutes": 5, "min_minutes": 1, "total_usd": 50000,
        }
        mock_pnl.return_value = {
            **EMPTY_PNL,
            "total_positions": 100,
            "closed_positions": 2,  # below the 3 required for has_edge
            "edge": 0.0,
        }
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": trade_ts,
            "eventSlug": "oscars-2026-best-actor-winner",
        }
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertNotIn("SERIAL TIMER", result.headline)


class TestGammaCacheSportDetection(unittest.TestCase):
    """Tests for is_sport_market in gamma_cache."""

    @patch("gamma_cache._fetch_event_tags", return_value=[{"id": "1", "label": "Sports"}, {"id": "279", "label": "NFL"}, {"id": "281", "label": "Football"}])
    def test_sport_tag_detected(self, mock_fetch):
        from gamma_cache import is_sport_market
        market = {"events": [{"id": "12345"}]}
        self.assertTrue(is_sport_market(market))

    @patch("gamma_cache._fetch_event_tags", return_value=[{"id": "42", "label": "Crypto"}, {"id": "100", "label": "DeFi"}])
    def test_non_sport_tags(self, mock_fetch):
        from gamma_cache import is_sport_market
        market = {"events": [{"id": "12345"}]}
        self.assertFalse(is_sport_market(market))

    def test_no_events_returns_false(self):
        from gamma_cache import is_sport_market
        self.assertFalse(is_sport_market({}))
        self.assertFalse(is_sport_market({"events": []}))


# ---------------------------------------------------------------------------
# New tests: basic gate checks in TestTimingRelativeResolutionStrategy
# ---------------------------------------------------------------------------
# The class-level patches on TestTimingRelativeResolutionStrategy already
# provide EMPTY_PNL, EMPTY_TIMING_STATS, record_timing_flag, and
# is_sport_market=False via decorator order.  The extra tests below are
# added to that class by re-opening it with additional methods — but
# unittest doesn't support re-opening, so we define a sibling class with
# the same patches.

@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_pnl_summary",
    return_value=EMPTY_PNL,
)
@patch(
    "detection_strategies.timing_relative_resolution.get_wallet_timing_stats",
    return_value=EMPTY_TIMING_STATS,
)
@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
@patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=False)
class TestTimingRelativeResolutionGates(unittest.TestCase):
    """Additional gate / edge-case tests for the main strategy."""

    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    def _make_trade(self, usd=5000, wallet="0xwallet1", ts=1700000000):
        return {
            "conditionId": "cond_1",
            "proxyWallet": wallet,
            "_usd_value": usd,
            "timestamp": ts,
        }

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_below_min_bet_usd_returns_none(self, mock_market, *mocks):
        """Trade below MIN_BET_USD (1000) should be ignored even if within timing window."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 300, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(usd=500, ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_edge_gate_suppresses_negative_edge(self, mock_market, mock_is_sport, mock_record, mock_stats, mock_pnl):
        """Wallet with >= MIN_CLOSED_FOR_GATE positions and edge < MIN_EDGE_GATE should be suppressed."""
        mock_pnl.return_value = {**EMPTY_PNL, "closed_positions": 10, "edge": -0.15}
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 300, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(usd=3000, ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNone(result)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_edge_gate_passes_acceptable_edge(self, mock_market, mock_is_sport, mock_record, mock_stats, mock_pnl):
        """Wallet with edge above MIN_EDGE_GATE should still produce a Signal."""
        mock_pnl.return_value = {**EMPTY_PNL, "closed_positions": 10, "edge": 0.05}
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 300, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(usd=3000, ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "timing_relative_resolution")

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    def test_missing_wallet_still_signals(self, mock_market, mock_is_sport, mock_record, *mocks):
        """Trade with empty proxyWallet should still produce a Signal; record_timing_flag should NOT be called."""
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 300, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        trade = self._make_trade(usd=3000, wallet="", ts=trade_ts)
        result = self.strategy.check_trade(trade)
        self.assertIsNotNone(result)
        self.assertEqual(result.strategy, "timing_relative_resolution")
        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# New class: sport serial timer threshold tests
# ---------------------------------------------------------------------------
@patch("detection_strategies.timing_relative_resolution.record_timing_flag")
@patch("detection_strategies.timing_relative_resolution.is_sport_market", return_value=True)
class TestSportSerialTimerThreshold(unittest.TestCase):
    """Sport markets use SPORT_REPEAT_TIMING_THRESHOLD (10) instead of REPEAT_TIMING_THRESHOLD (3)."""

    def setUp(self):
        self.strategy = TimingRelativeResolutionStrategy()

    def _make_sport_trade(self, ts=1700000000):
        return {
            "conditionId": "cond_1",
            "proxyWallet": "0xwallet1",
            "_usd_value": 5000,
            "timestamp": ts,
            "eventSlug": "nba-den-lal-2026-03-14",
        }

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_pnl_summary")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_timing_stats")
    def test_sport_below_threshold_no_serial_label(self, mock_stats, mock_pnl, mock_market, *mocks):
        """Sport wallet with total_flags=7 (above REPEAT=3 but below SPORT_REPEAT=10) should NOT get SERIAL TIMER."""
        mock_stats.return_value = {
            "total_flags": 7, "distinct_markets": 4,
            "avg_minutes": 3, "min_minutes": 1, "total_usd": 30000,
        }
        mock_pnl.return_value = {
            **EMPTY_PNL,
            "total_positions": 100,
            "closed_positions": 5,
            "edge": 0.10,
        }
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        result = self.strategy.check_trade(self._make_sport_trade(ts=trade_ts))
        self.assertIsNotNone(result)
        self.assertNotIn("SERIAL TIMER", result.headline)

    @patch("detection_strategies.timing_relative_resolution.get_market_by_condition")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_pnl_summary")
    @patch("detection_strategies.timing_relative_resolution.get_wallet_timing_stats")
    def test_sport_above_threshold_gets_serial_label(self, mock_stats, mock_pnl, mock_market, *mocks):
        """Sport wallet with total_flags=12 (>= SPORT_REPEAT=10) and edge > 0 should get SERIAL TIMER."""
        mock_stats.return_value = {
            "total_flags": 12, "distinct_markets": 6,
            "avg_minutes": 2, "min_minutes": 0.5, "total_usd": 60000,
        }
        mock_pnl.return_value = {
            **EMPTY_PNL,
            "total_positions": 100,
            "closed_positions": 5,
            "edge": 0.10,
            "total_pnl": 5000,
        }
        trade_ts = 1700000000
        end_dt = datetime.fromtimestamp(trade_ts + 180, tz=timezone.utc)
        mock_market.return_value = {"endDate": end_dt.isoformat()}
        result = self.strategy.check_trade(self._make_sport_trade(ts=trade_ts))
        self.assertIsNotNone(result)
        self.assertIn("SERIAL TIMER", result.headline)


if __name__ == "__main__":
    unittest.main()
