"""
Strategy: maintain a persistent store of flagged wallets and track
their historical accuracy.  A wallet that repeatedly places large,
correct bets is a sharp bettor worth following — especially if
they consistently beat implied odds.

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
    clear_wallet_pnl_by_type,
    get_unresolved_condition_ids,
    get_unresolved_bets_for_condition,
    get_wallet_stats,
    get_wallet_pnl_latest_timestamp,
    get_wallet_pnl_summary,
    mark_bets_resolved_bulk,
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
# Minimum edge (actual win% - implied win%) to consider notable
MIN_EDGE_THRESHOLD = 0.15
# If wallet has zero losses in the P&L data, require this many closed
# positions before trusting the 100% win rate
MIN_PERFECT_RECORD_POSITIONS = 20
MAX_PNL_POSITIONS = 1000  # cap total closed positions fetched per wallet
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
    Called once per wallet per run.

    Open positions are always re-fetched (small count, change frequently).
    Closed positions are fetched incrementally — only new positions since
    the last cached timestamp are requested, up to MAX_PNL_POSITIONS total
    on the initial backfill."""
    if wallet.lower() in _pnl_fetched:
        return
    _pnl_fetched.add(wallet.lower())

    # -- Open positions: clear and re-fetch (they change frequently) --
    clear_wallet_pnl_by_type(wallet, "open")
    _fetch_positions_page(wallet, "positions", "open", limit=50)

    # -- Closed positions: incremental fetch --
    latest_ts = get_wallet_pnl_latest_timestamp(wallet, "closed")
    if latest_ts:
        # Only fetch positions newer than what we have cached
        _fetch_positions_page(wallet, "closed-positions", "closed",
                              limit=MAX_PNL_POSITIONS, after_timestamp=latest_ts)
    else:
        # First time seeing this wallet — backfill up to MAX_PNL_POSITIONS
        _fetch_positions_page(wallet, "closed-positions", "closed",
                              limit=MAX_PNL_POSITIONS)


def _fetch_positions_page(wallet: str, endpoint: str, position_type: str,
                          limit: int, after_timestamp: int | None = None) -> int:
    """Paginate through a Data API positions endpoint. Returns count fetched."""
    offset = 0
    page_size = 50
    fetched = 0
    while fetched < limit:
        time.sleep(PNL_FETCH_DELAY)
        try:
            resp = requests.get(
                f"{DATA_API}/{endpoint}",
                params={"user": wallet, "limit": page_size, "offset": offset,
                        "sortBy": "timestamp"},
                timeout=15,
            )
            if resp.status_code != 200:
                break
            positions = resp.json()
            if not isinstance(positions, list) or len(positions) == 0:
                break

            new_count = 0
            for pos in positions:
                ts = pos.get("timestamp")
                if after_timestamp and ts and ts <= after_timestamp:
                    continue  # already cached
                record_wallet_pnl(wallet, pos, position_type)
                new_count += 1

            fetched += new_count
            if len(positions) < page_size:
                break  # last page
            # If incremental and entire page was old, we've caught up
            if after_timestamp and new_count == 0:
                break
            offset += page_size
        except requests.RequestException:
            break
    return fetched


# ---------------------------------------------------------------------------
# Resolution updates
# ---------------------------------------------------------------------------
_RESOLUTION_BATCH_SIZE = 100  # condition_ids per Gamma API request

# Wallets whose resolutions have already been updated this run
_resolutions_updated: set[str] = set()
# Total unique wallets expected this run (set by polybot.py before processing)
_total_unique_wallets: int = 0
# Condition IDs already checked for resolution this run (avoids re-checking
# the same markets when multiple wallets share unresolved conditions)
_conditions_checked: set[str] = set()


def _update_resolutions(wallet: str | None = None) -> int:
    """Check unresolved bets against Gamma API to see if markets have
    resolved.  Returns count of newly resolved bets.

    If wallet is provided, only checks condition_ids for that wallet.
    Batches condition_ids into single API calls for efficiency."""
    unresolved_cids = get_unresolved_condition_ids(wallet)
    if not unresolved_cids:
        return 0
    # Skip conditions already checked by a previous wallet this run
    unresolved_cids = [cid for cid in unresolved_cids if cid not in _conditions_checked]
    if not unresolved_cids:
        return 0
    _conditions_checked.update(unresolved_cids)
    total = len(unresolved_cids)
    print(f"  [win_rate_tracking] Checking {total} unresolved market(s) for resolution ({len(_conditions_checked)} total checked this run)...", flush=True)
    updated = 0
    all_updates: list[tuple[int, int]] = []

    for batch_start in range(0, total, _RESOLUTION_BATCH_SIZE):
        batch = unresolved_cids[batch_start : batch_start + _RESOLUTION_BATCH_SIZE]
        print(f"  [win_rate_tracking] Resolution batch {batch_start // _RESOLUTION_BATCH_SIZE + 1}/{(total + _RESOLUTION_BATCH_SIZE - 1) // _RESOLUTION_BATCH_SIZE} ({batch_start + len(batch)}/{total} markets, {updated} resolved so far)", flush=True)
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
                    max_idx = max(range(len(prices)), key=lambda i: float(prices[i]))
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
                all_updates.append((won, bet_id))
            updated += len(bets)

    # Single bulk write for all resolved bets
    mark_bets_resolved_bulk(all_updates)
    if updated:
        print(f"  [win_rate_tracking] Resolved {updated} bet(s)")
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

    def check_trade(self, trade: dict) -> Signal | None:
        """Record every large trade and check if the wallet has a
        notably high historical win rate."""
        wallet = trade.get("proxyWallet", "")
        if not wallet:
            return None

        record_tracked_bet(trade)
        _fetch_wallet_pnl(wallet)

        # Lazily resolve tracked bets for this wallet (once per wallet per run)
        if wallet.lower() not in _resolutions_updated:
            _resolutions_updated.add(wallet.lower())
            total_str = f"/{_total_unique_wallets}" if _total_unique_wallets else ""
            print(f"  [win_rate_tracking] Resolving wallet {len(_resolutions_updated)}{total_str} ({wallet[:8]}...)", flush=True)
            _update_resolutions(wallet)

        # Only emit one win_rate signal per wallet per run
        if wallet.lower() in _win_rate_signaled:
            return None

        stats = get_wallet_stats(wallet)
        pnl = get_wallet_pnl_summary(wallet)

        # Prefer wallet_pnl data (consistent win rate + edge from the same
        # dataset).  Fall back to tracked_bets only when P&L data is
        # insufficient.  Using both sources with mismatched denominators
        # would produce a meaningless edge calculation.
        win_rate = None
        edge = None
        source = ""

        if pnl["closed_positions"] >= MIN_RESOLVED_BETS:
            resolved = pnl["closed_positions"]
            wins = pnl["wins"]
            losses = pnl["losses"]
            win_rate = wins / resolved if resolved > 0 else 0

            # Even with pagination (up to MAX_PNL_POSITIONS), a wallet
            # showing zero losses on a small sample is unreliable.
            if losses == 0 and resolved < MIN_PERFECT_RECORD_POSITIONS:
                return None

            source = f"{wins}/{resolved} P&L"
            # Edge is computed from the same P&L dataset (self-consistent)
            edge = pnl.get("edge", 0)
        elif stats["resolved_bets"] >= MIN_RESOLVED_BETS:
            resolved = stats["resolved_bets"]
            wins = stats["wins"]
            win_rate = wins / resolved
            source = f"{wins}/{resolved} resolved"
            # Use P&L edge if available (computed from same price data),
            # otherwise fall back to raw win rate discounted by 0.5
            avg_price = pnl.get("avg_closed_price", 0)
            if pnl["closed_positions"] > 0 and avg_price > 0:
                edge = pnl.get("edge", 0)
            else:
                edge = win_rate - 0.5
        else:
            # Not enough data from either source
            return None

        if win_rate is None or win_rate < WIN_RATE_ALERT_THRESHOLD:
            return None

        # Skip if edge is too small (winning on heavy favorites isn't notable)
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

        avg_price = pnl.get("avg_closed_price", 0)
        if avg_price > 0:
            headline = (
                f"{win_rate:.0%} win rate ({source}) "
                f"at avg odds {avg_price:.0%} "
                f"(+{edge:.0%} edge)"
            )
        else:
            headline = f"{win_rate:.0%} win rate ({source})"

        # Boost severity for large positive edge
        if edge >= 0.30 and pnl["closed_positions"] >= MIN_RESOLVED_BETS:
            severity = min(6.0, severity + 1.0)
            headline += f", {pnl['closed_positions']} resolved positions"

        _win_rate_signaled.add(wallet.lower())
        return Signal(
            strategy=self.name,
            severity=severity,
            headline=headline,
            trade=trade,
            condition_id=trade.get("conditionId", ""),
        )
