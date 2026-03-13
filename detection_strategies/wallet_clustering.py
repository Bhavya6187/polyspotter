"""
Strategy: detect multiple "new" wallets that were funded by the same
source address on Polygon (Sybil detection).

For each flagged wallet, queries the Etherscan V2 API for the first
inbound transfer.  If several wallets in the current scan share a common
funder, it suggests a single actor splitting bets across wallets.

Funder relationships are persisted in the database so that:
- Etherscan lookups are cached across runs (avoids redundant API calls)
- Known Sybil funders are auto-escalated when new wallets appear
- Clusters that span multiple scan windows are detected

Requires an Etherscan API key in the ETHERSCAN_API_KEY environment
variable (free tier is fine — 5 calls/sec).
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()

from detection_strategies import DetectionStrategy, Signal
import config
from db import (
    get_cached_funder,
    get_known_sybil_funders,
    get_wallets_by_funder,
    save_funder,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ETHERSCAN_API = "https://api.etherscan.io/v2/api"
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
POLYGON_CHAIN_ID = 137
FUNDER_LOOKUP_DELAY = 0.25  # seconds between Etherscan calls
MIN_SHARED_WALLETS = 2  # flag when >= N wallets share the same funder

# In-memory cache for the current run (avoids repeated DB reads within a run)
_funder_cache: dict[str, str | None] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_first_funder(address: str) -> str | None:
    """Query Etherscan V2 API for the first inbound (normal) transaction to
    this address on Polygon.  Returns the 'from' address of the earliest tx,
    or None.  Results are persisted to the database."""
    address = address.lower()

    # Check in-memory cache first
    if address in _funder_cache:
        return _funder_cache[address]

    # Check persistent DB cache
    db_funder = get_cached_funder(address)
    if db_funder is not None:
        short = f"{address[:8]}...{address[-6:]}"
        short_f = f"{db_funder[:8]}...{db_funder[-6:]}" if db_funder else "?"
        if config.VERBOSE:
            print(f"    [sybil] {short} funded by {short_f} (from DB)")
        _funder_cache[address] = db_funder
        return db_funder

    if not ETHERSCAN_API_KEY:
        _funder_cache[address] = None
        return None

    time.sleep(FUNDER_LOOKUP_DELAY)

    try:
        resp = requests.get(
            ETHERSCAN_API,
            params={
                "module": "account",
                "action": "txlist",
                "address": address,
                "chainid": POLYGON_CHAIN_ID,
                "startblock": 0,
                "endblock": 9999999999,
                "page": 1,
                "offset": 1,
                "sort": "asc",
                "apikey": ETHERSCAN_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("result", [])
        if isinstance(results, list) and results:
            funder = results[0].get("from", "").lower()
            _funder_cache[address] = funder
            save_funder(address, funder)
            short = f"{address[:8]}...{address[-6:]}"
            short_f = f"{funder[:8]}...{funder[-6:]}" if funder else "?"
            if config.VERBOSE:
                print(f"    [sybil] {short} funded by {short_f}")
            return funder
    except requests.RequestException as e:
        print(f"[WARN] Etherscan lookup failed for {address}: {e}", file=sys.stderr)

    _funder_cache[address] = None
    save_funder(address, None)
    return None


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class WalletClusteringStrategy(DetectionStrategy):
    name = "wallet_clustering"
    description = (
        "Detects multiple wallets in the scan window that were funded by "
        "the same source address on Polygon (Sybil indicator). Persists "
        "funder relationships across runs for cross-window cluster detection."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        # Batch-only strategy — analysis happens in analyze_all
        return None

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        if not trades:
            return []

        if not ETHERSCAN_API_KEY:
            print("  [wallet_clustering] Skipped — set ETHERSCAN_API_KEY to enable")
            return []

        # Collect unique wallets from all trades
        wallet_trades: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            w = t.get("proxyWallet", "")
            if w:
                wallet_trades[w.lower()].append(t)

        # Look up funders for each wallet (DB-cached + API)
        funder_to_wallets: dict[str, list[str]] = defaultdict(list)
        for wallet in wallet_trades:
            funder = _get_first_funder(wallet)
            if funder:
                funder_to_wallets[funder].append(wallet)

        # Also check historical DB for known Sybil funders that have wallets
        # in the current scan, even if those wallets' co-funded siblings
        # aren't in this window
        known_sybils = get_known_sybil_funders(MIN_SHARED_WALLETS)

        signals: list[Signal] = []
        seen_funders: set[str] = set()

        # First: flag clusters found in the current window
        for funder, wallets in funder_to_wallets.items():
            if len(wallets) < MIN_SHARED_WALLETS:
                # Check if this funder has historical wallets that push it
                # over the threshold
                historical_wallets = get_wallets_by_funder(funder)
                all_wallets = set(wallets) | set(historical_wallets)
                if len(all_wallets) < MIN_SHARED_WALLETS:
                    continue
                # Some wallets are from prior runs — include them for context
                wallets_in_window = wallets
                extra_historical = [w for w in historical_wallets if w not in set(wallets)]
            else:
                wallets_in_window = wallets
                extra_historical = []

            seen_funders.add(funder)

            all_cluster_trades = []
            for w in wallets_in_window:
                all_cluster_trades.extend(wallet_trades[w])

            total_usd = sum(float(t.get("_usd_value", 0)) for t in all_cluster_trades)

            tx_hashes = [t.get("transactionHash", "") for t in all_cluster_trades if t.get("transactionHash")]

            short_funder = f"{funder[:8]}...{funder[-6:]}"
            sample = all_cluster_trades[0] if all_cluster_trades else trades[0]

            n_total = len(set(wallets_in_window) | set(extra_historical))
            headline = f"{n_total} wallets share funder {short_funder}, ${total_usd:,.0f} total"
            if extra_historical:
                headline += f" (+{len(extra_historical)} from prior runs)"

            # Severity scales with cluster size:
            #   2 wallets -> 5.0, 4 -> 6.0, 8 -> 7.0, 16 -> 8.0
            # Known Sybil funders get +1.0 boost
            base = 4.0 + math.log2(n_total)
            severity = min(8.0, base + (1.0 if funder in known_sybils else 0.0))

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

        # Second: check if any current-window wallet belongs to a known
        # Sybil funder that wasn't already caught above
        for funder, historical_wallets in known_sybils.items():
            if funder in seen_funders:
                continue
            current_wallets = [w for w in wallet_trades if w in set(historical_wallets)]
            if not current_wallets:
                continue

            all_cluster_trades = []
            for w in current_wallets:
                all_cluster_trades.extend(wallet_trades[w])

            total_usd = sum(float(t.get("_usd_value", 0)) for t in all_cluster_trades)

            tx_hashes = [t.get("transactionHash", "") for t in all_cluster_trades if t.get("transactionHash")]

            short_funder = f"{funder[:8]}...{funder[-6:]}"
            sample = all_cluster_trades[0] if all_cluster_trades else trades[0]

            signals.append(
                Signal(
                    strategy=self.name,
                    severity=6.0,
                    headline=(
                        f"Known Sybil funder {short_funder}: "
                        f"{len(current_wallets)} wallet(s) active, "
                        f"{len(historical_wallets)} total known, ${total_usd:,.0f}"
                    ),
                    trade=sample,
                    condition_id=sample.get("conditionId", ""),
                    trade_hashes=tx_hashes,
                )
            )

        if signals:
            print(f"  [wallet_clustering] Found {len(signals)} wallet cluster(s)")
        return signals
