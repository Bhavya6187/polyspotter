"""
Strategy: surface large bets on markets with very low recent trading
activity.

Large confident bets on quiet markets often signal that the trader
has information others don't.  Uses the Gamma API 24h volume to
determine if a market is low-activity, then flags large bets
relative to that baseline.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

import requests

from detection_strategies import DetectionStrategy, Signal
from db import record_orderbook_snapshot
from gamma_cache import get_market_by_condition

CLOB_API = "https://clob.polymarket.com"
CLOB_DELAY = 0.1

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOW_VOLUME_24H_USD = 5000  # market is "low activity" if 24h vol < this
BET_TO_VOLUME_RATIO = 0.50  # flag if single bet >= 50% of 24h volume (raised from 20%)
BET_TO_LIQUIDITY_RATIO = 0.05  # suppress if bet < 5% of market liquidity
SHORT_LIVED_MARKET_HOURS = 6  # skip markets shorter than this
THIN_BOOK_DEPTH_USD = 5000  # orderbook with < $5k total depth is thin


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

        # Severity scales with bet/volume ratio, capped at 3.0 base
        # (up to 4.0 with orderbook boosts for thin book / wide spread)
        if vol_24h > 0:
            severity = min(3.0, (usd / vol_24h) * 0.5)
            if is_low_volume:
                severity = max(severity, 1.0)  # floor for low-volume markets
        else:
            severity = 2.0

        # Boost severity if orderbook is thin (live fetch from CLOB)
        ob = self._fetch_orderbook(trade, cid)
        if ob:
            total_depth = ob["bid_depth"] + ob["ask_depth"]
            if total_depth < THIN_BOOK_DEPTH_USD and total_depth > 0:
                severity = min(4.0, severity + 0.5)
                parts.append(f"thin book ${total_depth:,.0f}")
            if ob["spread"] > 0.05:
                severity = min(4.0, severity + 0.5)
                parts.append(f"wide spread {ob['spread']:.1%}")

        return Signal(
            strategy=self.name,
            severity=severity,
            headline="; ".join(parts),
            trade=trade,
            condition_id=cid,
        )

    def _fetch_orderbook(self, trade: dict, cid: str) -> dict | None:
        """Fetch live orderbook from CLOB and persist a snapshot."""
        token_id = trade.get("asset", "")
        if not token_id:
            return None
        time.sleep(CLOB_DELAY)
        try:
            resp = requests.get(
                f"{CLOB_API}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if not bids and not asks:
                return None
            outcome = trade.get("outcome", "")
            record_orderbook_snapshot(cid, token_id, outcome, bids, asks)
            best_bid = max((float(b["price"]) for b in bids), default=0)
            best_ask = min((float(a["price"]) for a in asks), default=0)
            spread = (best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0
            bid_depth = sum(float(b["size"]) * float(b["price"]) for b in bids)
            ask_depth = sum(float(a["size"]) * float(a["price"]) for a in asks)
            return {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "spread": spread,
            }
        except requests.RequestException as e:
            print(f"[WARN] CLOB book fetch failed for {cid}: {e}", file=sys.stderr)
            return None
