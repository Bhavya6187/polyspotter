"""
Strategy: surface large bets that land close to a market's expected
resolution time.

Fetches endDate from the Gamma API market metadata and compares it
to the trade timestamp.  Trades landing within CLOSE_MINUTES of
resolution are flagged — late bets with conviction suggest a
real-time information edge.

Live sports markets (NBA, NFL, MLS, NHL, etc.) use a much tighter
window since near-resolution bets on live events are routine — the
bettor can see the scoreboard.  Sports detection uses the Gamma API's
event tags (tag ID '1' = Sports) with a slug-based fallback.

Timing flags are persisted to the database so wallets that repeatedly
bet near resolution across many markets are detected and escalated.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_wallet_pnl_summary,
    get_wallet_timing_stats,
    record_timing_flag,
)
from gamma_cache import get_market_by_condition, is_sport_market

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLOSE_MINUTES = 60  # default window for non-sport markets
SPORT_CLOSE_MINUTES = 5  # tighter window for live sports markets
SHORT_MARKET_HOURS = 2  # markets shorter than this are suppressed entirely
REPEAT_TIMING_THRESHOLD = 3  # flag wallet as serial timer if >= N historical timing flags
SPORT_REPEAT_TIMING_THRESHOLD = 10  # higher threshold for sports bettors
SERIAL_TIMER_RATIO_CAP = 0.5  # if >50% of a wallet's flags are timing flags, it's a routine live bettor
NON_SPORT_SEVERITY_BOOST = 1.5  # bonus severity for non-sport/non-live timing signals

# ---------------------------------------------------------------------------
# Slug-based sport fallback (used when event tags aren't available)
# ---------------------------------------------------------------------------
_SPORT_SLUG_PREFIXES = (
    "nba-", "nfl-", "nhl-", "mlb-", "mls-",
    "cbb-",  # college basketball
    "cfb-",  # college football
    "nascar-", "ufc-", "boxing-",
    "epl-", "ucl-", "liga-", "bundesliga-", "serie-a-", "ligue-1-",
    "afl-", "nrl-", "ipl-", "psl-",
    "wnba-", "pga-", "lpga-", "atp-", "wta-",
)

_SPORT_SLUG_REGEX = re.compile(
    r"(vs\.?[-\s])|(-vs-)"
    r"|(spread[-:])"
    r"|(o-u[-\s]|\bo/?u\b)"
    r"|(-moneyline)"
    r"|(-total-points)",
    re.IGNORECASE,
)


def _is_sport_by_slug(trade: dict) -> bool:
    """Slug-based fallback for sport detection when API tags unavailable."""
    slug = trade.get("eventSlug", "").lower()
    for prefix in _SPORT_SLUG_PREFIXES:
        if slug.startswith(prefix):
            return True
    return bool(_SPORT_SLUG_REGEX.search(slug))


def detect_sport(trade: dict, market: dict) -> bool:
    """Detect whether a trade is on a live sports market.

    Primary: uses Gamma API event tags (tag ID '1' = Sports).
    Fallback: slug-based heuristics if event tags aren't available.
    """
    # Primary: API-based tag check (cached per event ID)
    if is_sport_market(market):
        return True

    # Fallback: slug-based heuristics
    return _is_sport_by_slug(trade)


def _parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class TimingRelativeResolutionStrategy(DetectionStrategy):
    name = "timing_relative_resolution"
    description = (
        f"Flags large bets placed within {CLOSE_MINUTES} minutes of a "
        f"market's expected resolution time (or {SPORT_CLOSE_MINUTES} min "
        f"for live sports). Tracks wallets that repeatedly bet near "
        f"resolution across multiple markets."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        cid = trade.get("conditionId", "")
        if not cid:
            return None

        market = get_market_by_condition(cid)
        if not market:
            return None

        end_date = _parse_datetime(market.get("endDate"))
        if not end_date:
            return None

        trade_ts = trade.get("timestamp", 0)
        trade_dt = datetime.fromtimestamp(trade_ts, tz=timezone.utc)
        delta = end_date - trade_dt
        minutes_to_resolution = delta.total_seconds() / 60

        # Only flag trades that are *before* resolution
        if minutes_to_resolution < 0:
            return None

        # Determine if this is a live sports market
        is_sport = detect_sport(trade, market)
        close_window = SPORT_CLOSE_MINUTES if is_sport else CLOSE_MINUTES

        # Outside the window for this market type
        if minutes_to_resolution > close_window:
            return None

        # Determine if this is a short-duration market (e.g., 5-min BTC binary
        # options).  Betting near resolution on these is *expected behavior*,
        # not notable — the entire market lifespan is minutes.
        start_date = _parse_datetime(market.get("startDate"))
        market_duration_hours = None
        if start_date and end_date:
            market_duration_hours = (end_date - start_date).total_seconds() / 3600
        is_short_market = (
            market_duration_hours is not None
            and market_duration_hours < SHORT_MARKET_HOURS
        )

        # Short-duration markets: near-resolution bets are expected — suppress.
        if is_short_market:
            return None

        wallet = trade.get("proxyWallet", "")
        usd = float(trade.get("_usd_value", 0))

        # Record this timing flag for future pattern detection.
        if wallet:
            record_timing_flag(wallet, cid, minutes_to_resolution, usd, trade_ts,
                               market_duration_hours=market_duration_hours)

        # Continuous severity: higher as trade gets closer to resolution
        # 5.0 at 0 min, ~4.0 at 1 min, ~2.5 at 10 min, ~1.0 at 60 min
        severity = min(5.0, 5.0 / (1.0 + minutes_to_resolution * 0.25))

        # Boost non-sport signals — timing on events like awards, politics,
        # or regulatory decisions implies genuine information asymmetry.
        if not is_sport:
            severity = min(7.0, severity + NON_SPORT_SEVERITY_BOOST)

        headline = f"{minutes_to_resolution:.1f} min before resolution"
        if is_sport:
            headline += " (live sport)"

        # Check if this wallet is a serial "timer" — repeatedly bets near resolution.
        # Only count flags from long-duration markets (>= SHORT_MARKET_HOURS) so
        # that 5-min/15-min binary option trades don't inflate the serial-timer count.
        if wallet:
            timing_stats = get_wallet_timing_stats(
                wallet, min_market_duration_hours=SHORT_MARKET_HOURS
            )

            # Use higher threshold for sport bettors since near-resolution
            # sport bets are routine behavior.
            threshold = SPORT_REPEAT_TIMING_THRESHOLD if is_sport else REPEAT_TIMING_THRESHOLD

            # Check ratio: if most of a wallet's timing flags are relative to
            # their total positions, they're a routine live bettor, not a
            # selective timer. Only escalate if the ratio is below the cap.
            pnl = get_wallet_pnl_summary(wallet)
            total_positions = pnl["total_positions"]
            timing_ratio = (
                timing_stats["total_flags"] / total_positions
                if total_positions > 0
                else 0.0
            )
            is_routine_bettor = timing_ratio > SERIAL_TIMER_RATIO_CAP

            if timing_stats["total_flags"] >= threshold and not is_routine_bettor:
                # Only escalate serial timers who are actually winning.
                # A serial timer with a sub-75% win rate is just a live bettor,
                # not someone with a real-time information edge.
                win_pct = (
                    pnl["wins"] / pnl["closed_positions"]
                    if pnl["closed_positions"] > 0
                    else 0.0
                )
                has_edge = pnl["closed_positions"] >= 3 and win_pct >= 0.65

                if has_edge:
                    severity = min(7.0, severity + 1.5)
                    headline += (
                        f" — SERIAL TIMER: {timing_stats['total_flags']} near-resolution bets "
                        f"across {timing_stats['distinct_markets']} markets, "
                        f"${timing_stats['total_usd']:,.0f} total"
                    )

                    # Extra boost for profitable serial timers
                    if pnl["total_pnl"] > 0:
                        severity = min(8.0, severity + 1.0)
                        headline += f" + PROFITABLE: {win_pct:.0%} wins, ${pnl['total_pnl']:+,.0f} P&L"

        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=cid,
        )
