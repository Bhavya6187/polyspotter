"""
Strategy: detect correlated bets across related markets by the same
wallet within the scan window AND across historical runs.

If someone bets "Yes" on "Will X resign?" and simultaneously bets "No"
on "Will X win election?", that's a correlated position suggesting
conviction based on private information.

Related markets are identified by belonging to the same Polymarket event
(same eventSlug).  Within an event, opposing positions across different
markets by the same wallet are flagged.

Positions are classified as "bullish" or "bearish" on each market's
primary outcome.  If all positions across markets point the same
direction (e.g., all bullish on BTC), the wallet has a consistent view
and severity is discounted.  Mixed/opposing positions across markets
are more suspicious as they suggest nuanced informed positioning.

Historical trades are persisted so that cross-market positioning over
days/weeks is detected even if bets happen in separate scan windows.
"""

from __future__ import annotations

from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_wallet_cross_event_stats,
    get_wallet_event_history,
    record_wallet_event_trade,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_MARKETS = 2  # wallet must bet on >= N markets in the same event
MIN_TOTAL_USD = 2000  # minimum combined USD across the correlated bets
REPEAT_CROSS_EVENT_THRESHOLD = 3  # flag if wallet has cross-market bets on >= N events historically


def _is_bullish(trade: dict) -> bool:
    """Determine if a position is bullish on its outcome.

    BUY on an outcome means you're betting it will happen (bullish).
    SELL on an outcome means you're betting against it (bearish).
    """
    return trade.get("side", "") == "BUY"


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class CorrelatedCrossMarketStrategy(DetectionStrategy):
    name = "correlated_cross_market"
    description = (
        "Flags wallets that place bets across multiple markets within "
        "the same event, suggesting informed cross-market positioning. "
        "Persists history to detect patterns across scan windows."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        # Batch-only strategy
        return None

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        if not trades:
            return []

        # Record all trades for future cross-run detection
        for t in trades:
            record_wallet_event_trade(t)

        # Build: wallet -> event -> list of trades (current window)
        wallet_events: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

        for t in trades:
            wallet = t.get("proxyWallet", "")
            event_slug = t.get("eventSlug", "")
            if wallet and event_slug:
                wallet_events[wallet][event_slug].append(t)

        signals: list[Signal] = []
        wallets_with_cross_market: set[str] = set()

        for wallet, events in wallet_events.items():
            for event_slug, event_trades in events.items():
                # Combine current-window trades with historical trades
                # from prior runs for this wallet+event
                historical = get_wallet_event_history(wallet, event_slug)

                # Build combined view of markets hit (current + historical)
                markets_hit: dict[str, list[dict]] = defaultdict(list)

                # Current window trades
                for t in event_trades:
                    cid = t.get("conditionId", "")
                    if cid:
                        markets_hit[cid].append(t)

                # Historical trades (only add markets not already seen)
                current_cids = set(markets_hit.keys())
                historical_only_cids: set[str] = set()
                for h in historical:
                    cid = h["condition_id"]
                    if cid and cid not in current_cids:
                        historical_only_cids.add(cid)
                        markets_hit[cid].append(
                            {
                                "conditionId": cid,
                                "outcome": h["outcome"],
                                "side": h["side"],
                                "_usd_value": h["usd_value"],
                                "timestamp": h["trade_timestamp"],
                                "_historical": True,
                            }
                        )

                if len(markets_hit) < MIN_MARKETS:
                    continue

                total_usd = sum(float(t.get("_usd_value", 0)) for t in event_trades)
                # Include historical USD for threshold check
                historical_usd = sum(h["usd_value"] for h in historical if h["condition_id"] in historical_only_cids)
                combined_usd = total_usd + historical_usd

                if combined_usd < MIN_TOTAL_USD:
                    continue

                # --- Outcome correlation analysis ---
                # Classify each market position as bullish or bearish.
                # If all markets show the same direction, this is a
                # consistent view (e.g., all bullish on BTC) — less
                # suspicious.  Mixed directions suggest nuanced informed
                # positioning and warrant higher severity.
                market_directions: dict[str, bool] = {}  # cid -> is_bullish
                for cid, cid_trades in markets_hit.items():
                    # Use the largest trade to determine the dominant direction
                    dominant = max(cid_trades, key=lambda t: float(t.get("_usd_value", 0)))
                    market_directions[cid] = _is_bullish(dominant)

                all_bullish = all(market_directions.values())
                all_bearish = not any(market_directions.values())
                is_consistent = all_bullish or all_bearish

                wallets_with_cross_market.add(wallet.lower())

                tx_hashes = [t.get("transactionHash", "") for t in event_trades if t.get("transactionHash")]

                sample = event_trades[0]

                n_markets = len(markets_hit)

                if is_consistent:
                    # Consistent directional view — lower severity
                    # Skip entirely for 2-market consistent positions (very common)
                    if n_markets <= 2:
                        continue
                    severity = 1.5
                    direction = "bullish" if all_bullish else "bearish"
                    headline = f"{n_markets} markets in same event (consistent {direction}), ${combined_usd:,.0f}"
                else:
                    # Mixed directions across markets — more suspicious
                    severity = 3.0
                    headline = f"{n_markets} markets in same event (mixed directions), ${combined_usd:,.0f}"

                # Escalate if some markets were from prior runs
                if historical_only_cids:
                    headline += f" ({len(historical_only_cids)} market(s) from prior runs)"
                    severity += 1.0

                signals.append(
                    Signal(
                        strategy=self.name,
                        severity=severity,
                        headline=headline,
                        trade=sample,
                        condition_id=sample.get("conditionId", ""),
                        trade_hashes=tx_hashes,
                    )
                )

        # Check for wallets that repeatedly do cross-market positioning
        # across multiple events (serial informed trader pattern)
        for wallet in wallets_with_cross_market:
            stats = get_wallet_cross_event_stats(wallet)
            if stats["distinct_events"] >= REPEAT_CROSS_EVENT_THRESHOLD:
                # Find a representative trade for this wallet
                rep_trade = None
                for t in trades:
                    if t.get("proxyWallet", "").lower() == wallet:
                        rep_trade = t
                        break
                if not rep_trade:
                    continue

                signals.append(
                    Signal(
                        strategy=self.name,
                        severity=4.0,
                        headline=(
                            f"Serial cross-market trader: {stats['distinct_events']} events, "
                            f"{stats['distinct_markets']} markets, ${stats['total_usd']:,.0f} total"
                        ),
                        trade=rep_trade,
                        condition_id=rep_trade.get("conditionId", ""),
                    )
                )

        if signals:
            print(f"  [correlated_cross_market] Found {len(signals)} correlated position(s)")
        return signals
