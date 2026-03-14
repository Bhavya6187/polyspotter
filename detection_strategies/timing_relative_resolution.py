"""
Strategy: surface large bets that land close to a market's expected
resolution time.

Fetches endDate from the Gamma API market metadata and compares it
to the trade timestamp.  Trades landing within CLOSE_MINUTES of
resolution are flagged — late bets with conviction suggest a
real-time information edge.

Timing flags are persisted to the database so wallets that repeatedly
bet near resolution across many markets are detected and escalated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_wallet_pnl_summary,
    get_wallet_timing_stats,
    record_timing_flag,
)
from gamma_cache import get_market_by_condition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLOSE_MINUTES = 60  # trades within this many minutes of endDate are flagged
REPEAT_TIMING_THRESHOLD = 3  # flag wallet as serial timer if >= N historical timing flags
SHORT_MARKET_HOURS = 2  # markets shorter than this are "short-duration" (e.g., 5-min BTC binary options)
SHORT_MARKET_SEVERITY_CAP = 0  # fully suppress short-duration markets (near-resolution bets are expected)


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
        f"market's expected resolution time. Tracks wallets that repeatedly "
        f"bet near resolution across multiple markets."
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

        # Only flag trades that are *before* resolution and within the window
        if minutes_to_resolution < 0 or minutes_to_resolution > CLOSE_MINUTES:
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

        # Short-duration markets (e.g., 5-min BTC binary options): near-resolution
        # bets are expected behavior — suppress entirely.
        if is_short_market:
            return None

        wallet = trade.get("proxyWallet", "")
        usd = float(trade.get("_usd_value", 0))

        # Record this timing flag for future pattern detection.
        # Store market_duration_hours so serial-timer queries can exclude
        # short-duration markets from the historical count.
        if wallet:
            record_timing_flag(wallet, cid, minutes_to_resolution, usd, trade_ts,
                               market_duration_hours=market_duration_hours)

        # Continuous severity: higher as trade gets closer to resolution
        # 5.0 at 0 min, ~4.0 at 1 min, ~2.5 at 10 min, ~1.0 at 60 min
        severity = min(5.0, 5.0 / (1.0 + minutes_to_resolution * 0.25))

        headline = f"{minutes_to_resolution:.1f} min before resolution"

        # Check if this wallet is a serial "timer" — repeatedly bets near resolution.
        # Only count flags from long-duration markets (>= SHORT_MARKET_HOURS) so
        # that 5-min/15-min binary option trades don't inflate the serial-timer count.
        if wallet:
            timing_stats = get_wallet_timing_stats(
                wallet, min_market_duration_hours=SHORT_MARKET_HOURS
            )
            if timing_stats["total_flags"] >= REPEAT_TIMING_THRESHOLD:
                severity = min(7.0, severity + 1.5)
                headline += (
                    f" — SERIAL TIMER: {timing_stats['total_flags']} near-resolution bets "
                    f"across {timing_stats['distinct_markets']} markets, "
                    f"${timing_stats['total_usd']:,.0f} total"
                )

                # Cross-reference: is this serial timer also profitable?
                pnl = get_wallet_pnl_summary(wallet)
                if pnl["closed_positions"] >= 3 and pnl["total_pnl"] > 0:
                    win_pct = pnl["wins"] / pnl["closed_positions"] if pnl["closed_positions"] > 0 else 0
                    severity = min(8.0, severity + 1.0)
                    headline += f" + PROFITABLE: {win_pct:.0%} wins, ${pnl['total_pnl']:+,.0f} P&L"

        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=cid,
        )
