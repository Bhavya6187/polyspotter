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
WIN_RATE_ALERT_THRESHOLD = 0.75  # flag if win rate >= 75%
MIN_RESOLVED_BETS = 10  # need at least N resolved bets to judge
# Minimum edge (actual win% - implied win%) to consider suspicious
MIN_EDGE_THRESHOLD = 0.15
# If wallet has zero losses in the P&L data, require this many closed
# positions before trusting the 100% win rate
MIN_PERFECT_RECORD_POSITIONS = 20
MAX_PNL_POSITIONS = 200  # cap total positions fetched per endpoint
LOOKUP_DELAY = 0
PNL_FETCH_DELAY = 0.1

# Wallets whose P&L has already been fetched this run
_pnl_fetched: set[str] = set()

# Wallets that have already emitted a win_rate signal this run (one per wallet)
_win_rate_signaled: set[str] = set()


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
        offset = 0
        page_size = 50
        fetched = 0
        while fetched < MAX_PNL_POSITIONS:
            time.sleep(PNL_FETCH_DELAY)
            try:
                resp = requests.get(
                    f"{DATA_API}/{endpoint}",
                    params={"user": wallet, "limit": page_size, "offset": offset},
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                positions = resp.json()
                if not isinstance(positions, list) or len(positions) == 0:
                    break
                for pos in positions:
                    record_wallet_pnl(wallet, pos, position_type)
                fetched += len(positions)
                if len(positions) < page_size:
                    break  # last page
                offset += page_size
            except requests.RequestException:
                break


# ---------------------------------------------------------------------------
# Resolution updates
# ---------------------------------------------------------------------------
_RESOLUTION_BATCH_SIZE = 100  # condition_ids per Gamma API request


def _update_resolutions() -> int:
    """Check unresolved bets against Gamma API to see if markets have
    resolved.  Returns count of newly resolved bets.

    Batches condition_ids into single API calls for efficiency."""
    unresolved_cids = get_unresolved_condition_ids()
    if not unresolved_cids:
        return 0
    total = len(unresolved_cids)
    print(f"  [win_rate_tracking] Checking {total} unresolved market(s) for resolution...", flush=True)
    updated = 0

    for batch_start in range(0, total, _RESOLUTION_BATCH_SIZE):
        batch = unresolved_cids[batch_start : batch_start + _RESOLUTION_BATCH_SIZE]
        if batch_start > 0:
            print(f"  [win_rate_tracking] {batch_start}/{total} checked ({updated} resolved so far)", flush=True)
        time.sleep(LOOKUP_DELAY)
        try:
            params = [("condition_ids", cid) for cid in batch]
            params.append(("limit", len(batch)))
            resp = requests.get(
                f"{GAMMA_API}/markets",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            markets = resp.json()
        except requests.RequestException:
            continue

        for market in markets:
            if not market.get("closed"):
                continue

            cid = market.get("conditionId", "")
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

        # Only emit one win_rate signal per wallet per run
        if wallet.lower() in _win_rate_signaled:
            return None

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
            source = f"{wins}/{resolved} resolved"
        elif pnl["closed_positions"] >= MIN_RESOLVED_BETS:
            resolved = pnl["closed_positions"]
            wins = pnl["wins"]
            losses = pnl["losses"]
            win_rate = wins / resolved if resolved > 0 else 0

            # Even with pagination (up to MAX_PNL_POSITIONS), a wallet
            # showing zero losses on a small sample is unreliable.
            if losses == 0 and resolved < MIN_PERFECT_RECORD_POSITIONS:
                return None

            source = f"{wins}/{resolved} P&L"
        else:
            # Not enough data from either source
            return None

        if win_rate is None or win_rate < WIN_RATE_ALERT_THRESHOLD:
            return None

        # --- Odds-adjusted edge calculation ---
        # avg_closed_price approximates implied win probability.
        # A 100% win rate at avg_price=0.92 is unremarkable (expected 92%).
        # A 100% win rate at avg_price=0.40 is extraordinary (edge = 60%).
        avg_price = pnl.get("avg_win_price", 0) or pnl.get("avg_closed_price", 0)
        implied_win_rate = avg_price if 0 < avg_price < 1 else 0

        if implied_win_rate > 0:
            edge = win_rate - implied_win_rate
        else:
            # No price data — fall back to raw win rate but discount severity
            edge = win_rate - 0.5

        # Skip if edge is too small (winning on heavy favorites isn't suspicious)
        if edge < MIN_EDGE_THRESHOLD:
            return None

        # Severity scales with edge magnitude
        if edge >= 0.50:
            severity = 4.0  # extraordinary edge (50%+ above implied)
        elif edge >= 0.30:
            severity = 3.0  # strong edge
        elif edge >= 0.15:
            severity = 2.0  # moderate edge
        else:
            severity = 1.0

        if implied_win_rate > 0:
            headline = (
                f"{win_rate:.0%} win rate ({source}) "
                f"at avg odds {implied_win_rate:.0%} "
                f"(+{edge:.0%} edge)"
            )
        else:
            headline = f"{win_rate:.0%} win rate ({source})"

        # Boost severity if P&L data confirms profitability
        if pnl["closed_positions"] >= MIN_RESOLVED_BETS and pnl["total_pnl"] > 0:
            profit_ratio = pnl["total_pnl"] / pnl["total_invested"] if pnl["total_invested"] > 0 else 0
            if profit_ratio > 0.5:
                severity = min(6.0, severity + 1.0)
                headline += f", ${pnl['total_pnl']:+,.0f} P&L ({profit_ratio:.0%} ROI)"

        _win_rate_signaled.add(wallet.lower())
        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=trade.get("conditionId", ""),
        )
