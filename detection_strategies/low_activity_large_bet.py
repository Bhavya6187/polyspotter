"""
Strategy: flag when a large bet lands on a market that has had very
low trading activity recently.

Thinly-traded markets are easier targets for insiders since fewer
people are watching.  Uses the Gamma API 24h volume to determine
if a market is low-activity, then flags large bets relative to that
baseline.
"""

from __future__ import annotations

from datetime import datetime

from detection_strategies import DetectionStrategy, Signal
from gamma_cache import get_market_by_condition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOW_VOLUME_24H_USD = 5000     # market is "low activity" if 24h vol < this
BET_TO_VOLUME_RATIO = 0.50    # flag if single bet >= 50% of 24h volume (raised from 20%)
BET_TO_LIQUIDITY_RATIO = 0.05 # suppress if bet < 5% of market liquidity
SHORT_LIVED_MARKET_HOURS = 6  # skip markets shorter than this


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class LowActivityLargeBetStrategy(DetectionStrategy):
    name = "low_activity_large_bet"
    description = (
        f"Flags large bets on markets with < ${LOW_VOLUME_24H_USD:,} "
        f"24h volume, or where the bet is >= {BET_TO_VOLUME_RATIO:.0%} "
        f"of the 24h volume."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        cid = trade.get("conditionId", "")
        if not cid:
            return None

        market = get_market_by_condition(cid)
        if not market:
            return None

        # Skip short-lived markets (e.g. hourly binary options) — low 24h
        # volume is expected when the market only exists for a few hours.
        created_str = market.get("createdAt") or market.get("startDate")
        end_str = market.get("endDate")
        if created_str and end_str:
            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                lifespan_hours = (end_dt - created_dt).total_seconds() / 3600
                if lifespan_hours < SHORT_LIVED_MARKET_HOURS:
                    return None
            except ValueError:
                pass

        vol_24h = float(market.get("volume24hr", 0) or 0)
        usd = float(trade.get("_usd_value", 0))
        liquidity = float(market.get("liquidity", 0) or 0)

        # Suppress if bet is tiny relative to market liquidity — not moving the market
        if liquidity > 0 and (usd / liquidity) < BET_TO_LIQUIDITY_RATIO:
            return None

        # Check if market is low-activity
        is_low_volume = vol_24h < LOW_VOLUME_24H_USD
        is_large_relative = vol_24h > 0 and (usd / vol_24h) >= BET_TO_VOLUME_RATIO

        if not (is_low_volume or is_large_relative):
            return None

        ratio_str = f"{(usd / vol_24h):.1%}" if vol_24h > 0 else "∞"

        # Build headline
        parts = []
        if is_low_volume:
            parts.append(f"24h vol ${vol_24h:,.0f}")
        if is_large_relative:
            parts.append(f"{ratio_str} of 24h vol")

        # Severity scales with bet/volume ratio, capped at 3.0
        if vol_24h > 0:
            severity = min(3.0, (usd / vol_24h) * 0.5)
        else:
            severity = 2.0

        return Signal(
            strategy=self.name,
            severity=severity,
            headline="; ".join(parts),
            trade=trade,
            condition_id=cid,
        )
