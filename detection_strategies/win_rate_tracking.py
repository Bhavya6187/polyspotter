"""
Strategy: maintain a persistent store of flagged wallets and track
their historical accuracy.  A wallet that repeatedly places large,
correct bets just before resolution is far more suspicious than one
that's wrong half the time.

Uses the centralized polybot.db database for persistence across runs.
On each run, records flagged trades.  Also checks resolved markets to
update win/loss records for previously-flagged wallets.
"""

from __future__ import annotations

import json
import sys
import time

import requests

from detection_strategies import DetectionStrategy, Signal
from db import (
    clear_wallet_pnl,
    get_unresolved_condition_ids,
    get_unresolved_bets_for_condition,
    get_wallet_stats,
    get_wallet_pnl_summary,
    mark_bet_resolved,
    record_tracked_bet,
    record_wallet_pnl,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
WIN_RATE_ALERT_THRESHOLD = 0.70   # flag if win rate >= 70%
MIN_RESOLVED_BETS = 3             # need at least N resolved bets to judge
LOOKUP_DELAY = 0.15
PNL_FETCH_DELAY = 0.1

# Wallets whose P&L has already been fetched this run
_pnl_fetched: set[str] = set()


# ---------------------------------------------------------------------------
# Wallet P&L fetching (populates wallet_pnl table on the fly)
# ---------------------------------------------------------------------------
def _fetch_wallet_pnl(wallet: str) -> None:
    """Fetch open + closed positions from the Data API and persist them.
    Called once per wallet per run."""
    if wallet.lower() in _pnl_fetched:
        return
    _pnl_fetched.add(wallet.lower())

    clear_wallet_pnl(wallet)

    for position_type, endpoint in [("open", "positions"), ("closed", "closed-positions")]:
        time.sleep(PNL_FETCH_DELAY)
        try:
            resp = requests.get(
                f"{DATA_API}/{endpoint}",
                params={"user": wallet},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            positions = resp.json()
            if isinstance(positions, list):
                for pos in positions:
                    record_wallet_pnl(wallet, pos, position_type)
        except requests.RequestException:
            pass


# ---------------------------------------------------------------------------
# Resolution updates
# ---------------------------------------------------------------------------
def _update_resolutions() -> int:
    """Check unresolved bets against Gamma API to see if markets have
    resolved.  Returns count of newly resolved bets."""
    unresolved_cids = get_unresolved_condition_ids()
    updated = 0

    for cid in unresolved_cids:
        time.sleep(LOOKUP_DELAY)
        try:
            resp = requests.get(
                f"{GAMMA_API}/markets",
                params={"condition_ids": cid},
                timeout=10,
            )
            resp.raise_for_status()
            markets = resp.json()
            if not markets:
                continue
            market = markets[0]
        except requests.RequestException:
            continue

        if not market.get("closed"):
            continue

        outcome_prices_str = market.get("outcomePrices", "")
        outcomes_str = market.get("outcomes", "")

        winning_outcome_name = None
        try:
            prices = json.loads(outcome_prices_str) if isinstance(outcome_prices_str, str) else outcome_prices_str
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            if prices and outcomes and len(prices) == len(outcomes):
                max_idx = prices.index(max(prices))
                if float(prices[max_idx]) >= 0.99:
                    winning_outcome_name = outcomes[max_idx]
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        if not winning_outcome_name:
            continue

        bets = get_unresolved_bets_for_condition(cid)
        for bet_id, bet_outcome, bet_side in bets:
            if bet_side == "BUY":
                won = 1 if bet_outcome == winning_outcome_name else 0
            else:
                won = 1 if bet_outcome != winning_outcome_name else 0
            mark_bet_resolved(bet_id, won)
            updated += 1

    return updated


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class WinRateTrackingStrategy(DetectionStrategy):
    name = "win_rate_tracking"
    description = (
        "Tracks flagged wallets across runs and alerts on wallets with "
        f">= {WIN_RATE_ALERT_THRESHOLD:.0%} win rate on {MIN_RESOLVED_BETS}+ resolved bets."
    )

    def __init__(self):
        updated = _update_resolutions()
        if updated:
            print(f"  [win_rate_tracking] Updated {updated} resolved bet(s)")

    def check_trade(self, trade: dict) -> Signal | None:
        """Record every large trade and check if the wallet has a
        suspiciously high historical win rate."""
        wallet = trade.get("proxyWallet", "")
        if not wallet:
            return None

        record_tracked_bet(trade)
        _fetch_wallet_pnl(wallet)

        stats = get_wallet_stats(wallet)
        pnl = get_wallet_pnl_summary(wallet)

        # Use tracked_bets resolution if enough data, otherwise fall back to
        # closed-positions P&L data from the Data API
        win_rate = None
        source = ""
        resolved = stats["resolved_bets"]
        wins = stats["wins"]

        if resolved >= MIN_RESOLVED_BETS:
            win_rate = wins / resolved
            source = "resolved"
        elif pnl["closed_positions"] >= MIN_RESOLVED_BETS:
            resolved = pnl["closed_positions"]
            wins = pnl["wins"]
            win_rate = wins / resolved if resolved > 0 else 0
            source = "P&L"

        if win_rate is None or win_rate < WIN_RATE_ALERT_THRESHOLD:
            return None

        severity = 4.0 if win_rate >= 0.90 else 3.0

        headline = f"{win_rate:.0%} win rate ({wins}/{resolved} {source})"

        # Boost severity if P&L data confirms profitability
        if pnl["closed_positions"] >= MIN_RESOLVED_BETS and pnl["total_pnl"] > 0:
            profit_ratio = pnl["total_pnl"] / pnl["total_invested"] if pnl["total_invested"] > 0 else 0
            if profit_ratio > 0.5:
                severity = min(6.0, severity + 1.0)
                headline += f", ${pnl['total_pnl']:+,.0f} P&L ({profit_ratio:.0%} ROI)"

        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=trade.get("conditionId", ""),
        )
