"""
Strategy: detect wallets betting across multiple markets within the same
Polymarket event (same eventSlug).

If someone bets on multiple markets within the same event, they likely have
a thesis about that event.  Score based on total dollar amount and the
wallet's historical win rate.

Historical trades are persisted so cross-market positioning over days/weeks
is detected even if bets happen in separate scan windows.
"""

from __future__ import annotations

from collections import defaultdict

from detection_strategies import DetectionStrategy, Signal
from db import (
    get_wallet_cross_event_stats,
    get_wallet_event_history,
    get_wallet_pnl_summary,
    record_wallet_event_trade,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_MARKETS = 2  # wallet must bet on >= N markets in the same event
MIN_TOTAL_USD = 2000  # minimum combined USD across the correlated bets
REPEAT_CROSS_EVENT_THRESHOLD = 10  # flag if wallet has cross-market bets on >= N events historically


class CorrelatedCrossMarketStrategy(DetectionStrategy):
    name = "correlated_cross_market"
    description = (
        "Flags wallets that place bets across multiple markets within "
        "the same event. Scores by dollar amount and win rate."
    )

    def check_trade(self, trade: dict) -> Signal | None:
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
                historical = get_wallet_event_history(wallet, event_slug)

                # Collect distinct markets (current + historical)
                current_cids = {t.get("conditionId", "") for t in event_trades if t.get("conditionId")}
                historical_only_cids: set[str] = set()
                for h in historical:
                    cid = h["condition_id"]
                    if cid and cid not in current_cids:
                        historical_only_cids.add(cid)

                n_markets = len(current_cids | historical_only_cids)
                if n_markets < MIN_MARKETS:
                    continue

                total_usd = sum(float(t.get("_usd_value", 0)) for t in event_trades)
                historical_usd = sum(h["usd_value"] for h in historical if h["condition_id"] in historical_only_cids)
                combined_usd = total_usd + historical_usd

                if combined_usd < MIN_TOTAL_USD:
                    continue

                wallets_with_cross_market.add(wallet.lower())

                # Base severity from dollar amount
                if combined_usd >= 50_000:
                    severity = 5.0
                elif combined_usd >= 20_000:
                    severity = 4.0
                elif combined_usd >= 10_000:
                    severity = 3.0
                elif combined_usd >= 5_000:
                    severity = 2.0
                else:
                    severity = 1.0

                # Boost if wallet has a strong win rate
                pnl = get_wallet_pnl_summary(wallet)
                win_pct = None
                if pnl["closed_positions"] >= 5:
                    win_pct = pnl["wins"] / pnl["closed_positions"]
                    if win_pct >= 0.65:
                        severity += 2.0
                    elif win_pct >= 0.50:
                        severity += 1.0

                headline = f"{n_markets} markets in same event, ${combined_usd:,.0f}"
                if win_pct is not None:
                    headline += f" (win rate {win_pct:.0%})"
                if historical_only_cids:
                    headline += f" ({len(historical_only_cids)} from prior runs)"

                sample = event_trades[0]
                tx_hashes = [t.get("transactionHash", "") for t in event_trades if t.get("transactionHash")]

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

            stats = get_wallet_cross_event_stats(wallet)
            if stats["distinct_events"] >= REPEAT_CROSS_EVENT_THRESHOLD:
                rep_trade = next((t for t in trades if t.get("proxyWallet", "").lower() == wallet), None)
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
