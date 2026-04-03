"""
Strategy: detect multiple wallets that were funded by the same source
address on Polygon (linked-wallet detection).

For each flagged wallet, queries the Etherscan V2 API for the first
inbound transfer.  If several wallets in the current scan share a common
funder, it signals a single actor deploying capital across wallets —
high conviction worth tracking.

Funder relationships are persisted in the database so that:
- Etherscan lookups are cached across runs (avoids redundant API calls)
- Known linked funders are auto-escalated when new wallets appear
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
MAX_FUNDER_CHILDREN = 20  # skip funders with >= N children (likely exchange hot wallets)

# In-memory cache for the current run (avoids repeated DB reads within a run)
_funder_cache: dict[str, str | None] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _query_etherscan(address: str, action: str, offset: int = 10) -> list[dict] | None:
    """Call Etherscan V2 API and return the result list.

    Returns [] on success with no results, None on API error (rate limit,
    invalid key, etc.).  Callers should NOT cache a negative funder result
    when None is returned — the lookup should be retried later."""
    try:
        resp = requests.get(
            ETHERSCAN_API,
            params={
                "module": "account",
                "action": action,
                "address": address,
                "chainid": POLYGON_CHAIN_ID,
                "startblock": 0,
                "endblock": 9999999999,
                "page": 1,
                "offset": offset,
                "sort": "asc",
                "apikey": ETHERSCAN_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Etherscan returns status "0" on errors AND on "no results found".
        # Distinguish them by checking the result string.
        if data.get("status") != "1":
            result_msg = str(data.get("result", ""))
            message = str(data.get("message", ""))
            if "No transactions found" in result_msg or "No transactions found" in message:
                return []  # genuine empty result
            print(
                f"[WARN] Etherscan {action} error for {address}: "
                f"{data.get('message', '')} — {result_msg}",
                file=sys.stderr,
            )
            return None  # API error — don't cache
        results = data.get("result", [])
        return results if isinstance(results, list) else []
    except requests.RequestException as e:
        print(f"[WARN] Etherscan {action} failed for {address}: {e}", file=sys.stderr)
        return None


def _get_first_funder(address: str) -> str | None:
    """Find the address that first funded *address* on Polygon.

    Checks both normal transactions (txlist) and internal/contract
    transactions (txlistinternal), filtering to inbound-only, and
    returns the sender of the earliest one.  Many Polymarket proxy
    wallets are funded via internal transactions, so txlist alone
    would miss the real funder.

    Results are persisted to the database."""
    address = address.lower()

    # Check in-memory cache first
    if address in _funder_cache:
        return _funder_cache[address]

    # Check persistent DB cache
    cached, db_funder = get_cached_funder(address)
    if cached:
        short = f"{address[:8]}...{address[-6:]}"
        short_f = f"{db_funder[:8]}...{db_funder[-6:]}" if db_funder else "?"
        if config.VERBOSE:
            print(f"    [cluster] {short} funded by {short_f} (from DB)")
        _funder_cache[address] = db_funder
        return db_funder

    if not ETHERSCAN_API_KEY:
        _funder_cache[address] = None
        return None

    time.sleep(FUNDER_LOOKUP_DELAY)

    # Query both normal and internal transactions, filter to inbound only,
    # and pick the earliest by block number.
    candidates: list[tuple[int, str]] = []  # (block, from_address)
    api_succeeded = True

    actions = ("txlist", "txlistinternal")
    for i, action in enumerate(actions):
        results = _query_etherscan(address, action)
        if results is None:
            api_succeeded = False
        else:
            for tx in results:
                if tx.get("to", "").lower() == address:
                    block = int(tx.get("blockNumber", 0))
                    sender = tx.get("from", "").lower()
                    if sender and sender != address:
                        candidates.append((block, sender))
                        break  # results are sorted asc, first inbound is enough
        # Rate-limit delay between consecutive Etherscan API calls
        if i < len(actions) - 1:
            time.sleep(FUNDER_LOOKUP_DELAY)

    if candidates:
        # Pick the earliest inbound tx across both query types
        candidates.sort()
        funder = candidates[0][1]
        _funder_cache[address] = funder
        save_funder(address, funder)
        short = f"{address[:8]}...{address[-6:]}"
        short_f = f"{funder[:8]}...{funder[-6:]}"
        if config.VERBOSE:
            print(f"    [cluster] {short} funded by {short_f}")
        return funder

    # Only persist a negative result (no funder) when the API calls
    # actually succeeded.  On API errors (rate limit, timeout, etc.),
    # skip caching so the wallet is retried on the next run.
    if api_succeeded:
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
        "the same source address on Polygon (linked wallets). Persists "
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

        # Also check historical DB for known linked funders that have wallets
        # in the current scan, even if those wallets' co-funded siblings
        # aren't in this window
        known_sybils = get_known_sybil_funders(MIN_SHARED_WALLETS)

        signals: list[Signal] = []
        seen_funders: set[str] = set()

        # First: flag clusters found in the current window
        for funder, wallets in funder_to_wallets.items():
            # Skip likely exchange hot wallets
            all_known = get_wallets_by_funder(funder)
            if len(all_known) >= MAX_FUNDER_CHILDREN:
                continue

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
            # Known linked funders get +1.0 boost
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
        # linked funder that wasn't already caught above
        for funder, historical_wallets in known_sybils.items():
            if funder in seen_funders:
                continue
            if len(historical_wallets) >= MAX_FUNDER_CHILDREN:
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
                        f"Known linked funder {short_funder}: "
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
