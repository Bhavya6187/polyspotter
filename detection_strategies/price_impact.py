"""
Strategy: detect significant price (implied probability) shifts,
flagging the trades that drove the movement.

Operates in two modes:
1. Within-window: compares earliest and latest prices in the current batch
2. Cross-window: compares current prices against historical price observations
   from the database to detect gradual manipulation across multiple runs

Price observations are persisted to the database on every run.
"""

from __future__ import annotations

from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_historical_price_range,
    record_price_observation,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PRICE_SHIFT_THRESHOLD = 0.15  # flag if price moved >= 15 percentage points
HISTORICAL_SHIFT_THRESHOLD = 0.25  # flag if price moved >= 25pp from historical range
MIN_TRADES_FOR_SIGNAL = 2      # need at least this many trades to measure shift


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class PriceImpactStrategy(DetectionStrategy):
    name = "price_impact"
    description = (
        "Flags tokens whose implied probability shifted by >= "
        f"{PRICE_SHIFT_THRESHOLD:.0%} within the scan window, or >= "
        f"{HISTORICAL_SHIFT_THRESHOLD:.0%} from historical price range."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        # Batch-only strategy
        return None

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        """Track price across trades in the window per token,
        flag significant shifts. Also record prices and check against
        historical range."""
        if not trades:
            return []

        # Group trades by (conditionId, outcome) — i.e. per token side
        token_trades: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for t in trades:
            cid = t.get("conditionId", "")
            outcome = t.get("outcome", "")
            if cid and outcome:
                token_trades[(cid, outcome)].append(t)

        signals: list[Signal] = []
        tokens_with_window_signal: set[tuple[str, str]] = set()

        for (cid, outcome), t_list in token_trades.items():
            # Record all price observations for future runs
            for t in t_list:
                price = float(t.get("price", 0))
                ts = t.get("timestamp", 0)
                if price > 0 and ts > 0:
                    record_price_observation(cid, outcome, price, ts)

            # --- Within-window shift detection ---
            if len(t_list) >= MIN_TRADES_FOR_SIGNAL:
                t_sorted = sorted(t_list, key=lambda x: x.get("timestamp", 0))
                first_price = float(t_sorted[0].get("price", 0))
                last_price = float(t_sorted[-1].get("price", 0))

                shift = last_price - first_price
                abs_shift = abs(shift)

                if abs_shift >= PRICE_SHIFT_THRESHOLD:
                    tokens_with_window_signal.add((cid, outcome))
                    sample = t_sorted[0]
                    direction = "UP" if shift > 0 else "DOWN"

                    tx_hashes = [
                        t.get("transactionHash", "")
                        for t in t_list
                        if t.get("transactionHash")
                    ]

                    severity = min(3.0, abs_shift * 10.0)

                    signals.append(Signal(
                        strategy=self.name,
                        severity=severity,
                        headline=f"price {direction} {abs_shift:.2%} ({outcome})",
                        trade=sample,
                        condition_id=cid,
                        trade_hashes=tx_hashes,
                    ))

            # --- Cross-window shift detection (historical) ---
            historical_range = get_historical_price_range(cid, outcome)
            if not historical_range:
                continue

            hist_min, hist_max = historical_range
            # Get current window's latest price
            t_sorted = sorted(t_list, key=lambda x: x.get("timestamp", 0))
            current_price = float(t_sorted[-1].get("price", 0))

            if current_price <= 0:
                continue

            # Check if current price has broken out of the historical range
            if current_price > hist_max:
                breakout = current_price - hist_max
            elif current_price < hist_min:
                breakout = hist_min - current_price
            else:
                continue

            if breakout < HISTORICAL_SHIFT_THRESHOLD:
                continue

            # Don't double-signal if we already caught this in the window check
            if (cid, outcome) in tokens_with_window_signal:
                continue

            sample = t_sorted[-1]
            direction = "UP" if current_price > hist_max else "DOWN"

            tx_hashes = [
                t.get("transactionHash", "")
                for t in t_list
                if t.get("transactionHash")
            ]

            severity = min(4.0, breakout * 10.0)

            signals.append(Signal(
                strategy=self.name,
                severity=severity,
                headline=(
                    f"price {direction} {breakout:.2%} beyond historical range "
                    f"[{hist_min:.2f}-{hist_max:.2f}] ({outcome})"
                ),
                trade=sample,
                condition_id=cid,
                trade_hashes=tx_hashes,
            ))

        if signals:
            print(f"  [price_impact] Found {len(signals)} token(s) with significant price shifts")
        return signals
