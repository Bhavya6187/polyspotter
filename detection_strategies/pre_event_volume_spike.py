"""
Strategy: surface markets where recent trade volume spikes far above
the historical average, suggesting informed traders are positioning.

Compares the window volume (from the trades batch) against:
1. The market's rolling 24-hour volume from the Gamma API (single-run baseline)
2. Historical average volume snapshots from the database (multi-run baseline)

The better baseline (historical if available) is used for spike detection.
Volume snapshots are recorded on every run to build a richer baseline over time.
"""

from __future__ import annotations

import math
from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_average_volume,
    record_volume_snapshot,
)
from gamma_cache import get_market_by_condition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SPIKE_THRESHOLD_X = 10.0  # flag if window volume >= 10x the normalised average
MIN_SNAPSHOTS_FOR_HISTORICAL = 3  # need at least N snapshots to use historical baseline
MIN_WINDOW_VOLUME_USD = 10000  # ignore spikes below this absolute volume
MIN_TRADES_FOR_SPIKE = 3  # require multiple trades to distinguish from a single large bet


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class PreEventVolumeSpikeStrategy(DetectionStrategy):
    name = "pre_event_volume_spike"
    description = (
        "Flags markets where trade volume in the scan window is "
        f">= {SPIKE_THRESHOLD_X}x the normalised average and >= "
        f"${MIN_WINDOW_VOLUME_USD:,} (using historical baselines when available)."
    )
    window_seconds = 300

    def check_trade(self, trade: dict) -> Signal | None:
        # Batch-only strategy — analysis happens in analyze_all
        return None

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        """Group trades by conditionId, sum window volume, compare to baseline."""
        if not trades:
            return []

        # Group window volume by conditionId
        volume_by_market: dict[str, float] = defaultdict(float)
        trades_by_market: dict[str, list[dict]] = defaultdict(list)

        for t in trades:
            cid = t.get("conditionId", "")
            if not cid:
                continue
            usd = float(t.get("_usd_value", 0))
            volume_by_market[cid] += usd
            trades_by_market[cid].append(t)

        signals: list[Signal] = []

        for cid, window_vol in volume_by_market.items():
            market = get_market_by_condition(cid)
            if not market:
                continue

            vol_24h = float(market.get("volume24hr", 0) or 0)

            if vol_24h <= 0:
                continue

            window_seconds = self.window_seconds
            if trades_by_market[cid]:
                timestamps = [t.get("timestamp", 0) for t in trades_by_market[cid]]
                span = max(timestamps) - min(timestamps)
                if span > 0:
                    window_seconds = max(span, 60)
                else:
                    window_seconds = 60  # all trades at same timestamp — use minimum window

            # Choose best baseline: historical average if we have enough data,
            # otherwise fall back to current 24h volume.
            # Read average BEFORE recording this snapshot so the current
            # (potentially spike-inflated) value doesn't pollute the baseline.
            historical = get_average_volume(cid)

            # Record this snapshot for future runs — done AFTER reading
            # the historical average so the current value doesn't inflate it.
            record_volume_snapshot(cid, vol_24h)

            baseline_vol = vol_24h
            baseline_source = "24h"

            if historical is not None:
                hist_avg, hist_count = historical
                if hist_avg > 0 and hist_count >= MIN_SNAPSHOTS_FOR_HISTORICAL:
                    baseline_vol = hist_avg
                    baseline_source = "historical"

            normalised_avg = baseline_vol * (window_seconds / 86400)
            if normalised_avg <= 0:
                continue

            ratio = window_vol / normalised_avg

            n_trades = len(trades_by_market[cid])
            if ratio >= SPIKE_THRESHOLD_X and window_vol >= MIN_WINDOW_VOLUME_USD and n_trades >= MIN_TRADES_FOR_SPIKE:
                sample = trades_by_market[cid][0]

                # Severity: log-scaled, capped at 4.0 (higher cap for historical baseline)
                max_severity = 4.0 if baseline_source == "historical" else 3.0
                severity = min(max_severity, math.log10(max(ratio, 1)) * 1.0)

                # Escalate if both baselines show a spike
                if baseline_source == "historical" and vol_24h > 0:
                    ratio_24h = window_vol / (vol_24h * (window_seconds / 86400))
                    if ratio_24h >= SPIKE_THRESHOLD_X:
                        severity = min(max_severity, severity + 0.5)

                tx_hashes = [t.get("transactionHash", "") for t in trades_by_market[cid] if t.get("transactionHash")]

                headline = (
                    f"{ratio:.1f}x spike vs {baseline_source} avg ({n_trades} trade{'s' if n_trades != 1 else ''})"
                )

                signals.append(
                    Signal(
                        strategy=self.name,
                        severity=severity,
                        headline=headline,
                        trade=sample,
                        condition_id=cid,
                        trade_hashes=tx_hashes,
                    )
                )

        if signals:
            print(f"  [pre_event_volume_spike] Found {len(signals)} market(s) with volume spikes")
        return signals
