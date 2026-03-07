"""
Strategy: weight suspicion higher when large bets land close to a
market's expected resolution time.

Fetches endDate from the Gamma API market metadata and compares it
to the trade timestamp.  Trades landing within CLOSE_MINUTES of
resolution are flagged with higher urgency.

Timing flags are persisted to the database so wallets that repeatedly
bet near resolution across many markets are detected and escalated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from detection_strategies import DetectionStrategy, Signal
from detection_strategies.db import (
    get_wallet_timing_stats,
    record_timing_flag,
)
from detection_strategies.gamma_cache import get_market_by_condition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLOSE_MINUTES = 60         # trades within this many minutes of endDate are flagged
REPEAT_TIMING_THRESHOLD = 3  # flag wallet as serial timer if >= N historical timing flags


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

        wallet = trade.get("proxyWallet", "")
        usd = float(trade.get("_usd_value", 0))

        # Record this timing flag for future pattern detection
        if wallet:
            record_timing_flag(wallet, cid, minutes_to_resolution, usd, trade_ts)

        # Continuous severity: higher as trade gets closer to resolution
        # 5.0 at 0 min, ~4.0 at 1 min, ~2.5 at 10 min, ~1.0 at 60 min
        severity = min(5.0, 5.0 / (1.0 + minutes_to_resolution * 0.25))

        headline = f"{minutes_to_resolution:.1f} min before resolution"

        # Check if this wallet is a serial "timer" — repeatedly bets near resolution
        if wallet:
            timing_stats = get_wallet_timing_stats(wallet)
            if timing_stats["total_flags"] >= REPEAT_TIMING_THRESHOLD:
                severity = min(7.0, severity + 1.5)
                headline += (
                    f" — SERIAL TIMER: {timing_stats['total_flags']} near-resolution bets "
                    f"across {timing_stats['distinct_markets']} markets, "
                    f"${timing_stats['total_usd']:,.0f} total"
                )

        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=cid,
        )
