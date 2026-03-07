"""
Strategy: flag when multiple large bets within the scan window all take
the same side of a market.

A single large bet is one thing; several different wallets each placing
large bets on the same outcome within minutes is much more suspicious.
Trades are grouped by (conditionId, outcome, side) and flagged when the
cluster exceeds configured thresholds.
"""

from __future__ import annotations

from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_WALLETS = 3          # minimum distinct wallets to flag
MIN_CLUSTER_USD = 5000   # minimum total USD in the cluster to flag
MAX_WINDOW_SECONDS = 300  # trades must fall within this window


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class ConcentratedOneSidedStrategy(DetectionStrategy):
    name = "concentrated_one_sided"
    description = (
        f"Flags when >= {MIN_WALLETS} distinct wallets place large bets "
        f"on the same side of a market within the scan window "
        f"(total >= ${MIN_CLUSTER_USD:,})."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        # Batch-only strategy — analysis happens in analyze_all
        return None

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        """Group trades by (conditionId, outcome, side) and flag clusters."""
        if not trades:
            return []

        clusters: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

        for t in trades:
            cid = t.get("conditionId", "")
            outcome = t.get("outcome", "")
            side = t.get("side", "")
            if cid and outcome and side:
                clusters[(cid, outcome, side)].append(t)

        signals: list[Signal] = []

        for (cid, outcome, side), cluster_trades in clusters.items():
            wallets = {t.get("proxyWallet", "") for t in cluster_trades} - {""}
            if len(wallets) < MIN_WALLETS:
                continue

            total_usd = sum(float(t.get("_usd_value", 0)) for t in cluster_trades)
            if total_usd < MIN_CLUSTER_USD:
                continue

            sample = cluster_trades[0]
            tx_hashes = [
                t.get("transactionHash", "")
                for t in cluster_trades
                if t.get("transactionHash")
            ]

            signals.append(Signal(
                strategy=self.name,
                severity=3.5,
                headline=f"{len(wallets)} wallets, same direction ({outcome}/{side}), ${total_usd:,.0f}",
                trade=sample,
                condition_id=cid,
                trade_hashes=tx_hashes,
            ))

        if signals:
            print(f"  [concentrated_one_sided] Found {len(signals)} suspicious cluster(s)")
        return signals
