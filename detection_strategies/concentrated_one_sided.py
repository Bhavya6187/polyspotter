"""
Strategy: surface coordinated one-sided flow — multiple wallets all
betting the same direction on a market.

A single large bet is one thing; several different wallets each placing
large bets on the same outcome within minutes is a strong directional
signal.  Trades are grouped by effective direction and flagged when the
cluster exceeds configured thresholds.

For binary markets (exactly 2 outcomes per conditionId), opposing trades
are collapsed into the same directional cluster:
  SELL outcome_A  ≡  BUY outcome_B   (both are pro-B / anti-A)
This prevents double-counting the same directional flow as separate
signals and inflating composite scores.
"""

from __future__ import annotations

import math
from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal
from db import get_cached_funder
from gamma_cache import get_market_by_condition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_WALLETS = 3  # minimum distinct wallets to flag
MIN_CLUSTER_USD = 5000  # minimum total USD in the cluster to flag
FAVORITE_PRICE_THRESHOLD = 0.70  # suppress clusters buying above this price...
FAVORITE_VOLUME_24H = 50_000  # ...on markets with 24h volume above this
RESOLVED_TRADE_PRICE = 0.98  # skip individual trades at near-certain prices


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
        """Group trades by effective direction and flag clusters.

        For binary markets, SELL on outcome A is merged with BUY on
        outcome B since they express the same directional view."""
        if not trades:
            return []

        # Detect binary markets: conditionIds with exactly 2 outcomes
        cid_outcomes: dict[str, set[str]] = defaultdict(set)
        for t in trades:
            cid = t.get("conditionId", "")
            outcome = t.get("outcome", "")
            if cid and outcome:
                cid_outcomes[cid].add(outcome)

        binary_cids: dict[str, tuple[str, str]] = {}
        for cid, outcomes in cid_outcomes.items():
            if len(outcomes) == 2:
                binary_cids[cid] = tuple(sorted(outcomes))

        clusters: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

        for t in trades:
            cid = t.get("conditionId", "")
            outcome = t.get("outcome", "")
            side = t.get("side", "")
            if not (cid and outcome and side):
                continue

            # Skip trades at near-certain prices — these are post-resolution
            # crowd trades, not informed positioning.  BUY at 0.99 = paying
            # 99c to win 1c; SELL at 0.01 = collecting 1c on a known loser.
            price = float(t.get("price", 0.5))
            if (side == "BUY" and price >= RESOLVED_TRADE_PRICE) or (
                side == "SELL" and price <= (1 - RESOLVED_TRADE_PRICE)
            ):
                continue

            if cid in binary_cids and side == "SELL":
                # Selling outcome A = buying outcome B in a binary market
                o1, o2 = binary_cids[cid]
                effective_outcome = o2 if outcome == o1 else o1
                remapped = dict(t, price=1 - price)
                clusters[(cid, effective_outcome, "BUY")].append(remapped)
            else:
                clusters[(cid, outcome, side)].append(t)

        signals: list[Signal] = []

        for (cid, outcome, side), cluster_trades in clusters.items():
            wallets = {t.get("proxyWallet", "").lower() for t in cluster_trades} - {""}
            if len(wallets) < MIN_WALLETS:
                continue

            total_usd = sum(float(t.get("_usd_value", 0)) for t in cluster_trades)
            if total_usd < MIN_CLUSTER_USD:
                continue

            # Suppress clusters buying heavy favorites on high-volume markets —
            # lots of people backing the consensus pick isn't a signal.
            if side == "BUY":
                avg_price = (
                    sum(float(t.get("price", 0)) for t in cluster_trades)
                    / len(cluster_trades)
                )
                if avg_price > FAVORITE_PRICE_THRESHOLD:
                    market = get_market_by_condition(cid)
                    vol_24h = float(market.get("volume24hr", 0) or 0) if market else 0
                    if vol_24h >= FAVORITE_VOLUME_24H:
                        continue

            sample = cluster_trades[0]
            tx_hashes = [t.get("transactionHash", "") for t in cluster_trades if t.get("transactionHash")]

            # Base severity scales with cluster size and volume:
            #   3 wallets -> 3.5, 5 -> 4.2, 10 -> 5.0, 20 -> 5.8
            n_wallets = len(wallets)
            severity = min(6.0, 2.5 + math.log2(n_wallets))

            # Volume boost: +0.5 for $50k+, +1.0 for $100k+
            if total_usd >= 100_000:
                severity = min(7.0, severity + 1.0)
            elif total_usd >= 50_000:
                severity = min(6.5, severity + 0.5)

            headline = f"{n_wallets} wallets, same direction ({outcome}/{side}), ${total_usd:,.0f}"

            # Cross-reference with wallet_clustering: check if any wallets
            # in this cluster share a common funder (linked wallets)
            funders: dict[str, list[str]] = {}
            for w in wallets:
                _, funder = get_cached_funder(w)
                if funder:
                    funders.setdefault(funder, []).append(w)

            shared_funders = {f: ws for f, ws in funders.items() if len(ws) >= 2}
            if shared_funders:
                n_shared = sum(len(ws) for ws in shared_funders.values())
                severity = min(8.0, severity + 1.5)
                headline += f" — {n_shared} share funder (linked)"

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
            print(f"  [concentrated_one_sided] Found {len(signals)} notable cluster(s)")
        return signals
