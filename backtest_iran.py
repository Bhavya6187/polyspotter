#!/usr/bin/env python3
"""
Backtest: US strikes Iran event (Feb 28 spike)

Fetches historical trades for the "US strikes Iran by..." event from the
Polymarket Data API, then runs the existing detection strategies to see
which trades would have been flagged.

Uses a separate SQLite database (backtest.db) to avoid polluting the
production database.
"""

import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

# ---------------------------------------------------------------------------
# Monkey-patch db.py to use a separate backtest database BEFORE importing
# anything that touches the database.
# ---------------------------------------------------------------------------
BACKTEST_DB = os.path.join(os.path.dirname(__file__), "backtest.db")

# Remove stale backtest DB (and WAL/SHM files) so we start fresh each run
for suffix in ("", "-wal", "-shm"):
    path = BACKTEST_DB + suffix
    if os.path.exists(path):
        os.remove(path)

import db as _db_module

_backtest_conn = None


def _backtest_get_db() -> sqlite3.Connection:
    global _backtest_conn
    if _backtest_conn is not None:
        return _backtest_conn
    _backtest_conn = sqlite3.connect(BACKTEST_DB)
    _backtest_conn.execute("PRAGMA journal_mode=WAL")
    _backtest_conn.execute("PRAGMA synchronous=NORMAL")
    _db_module._init_tables(_backtest_conn)
    return _backtest_conn


_db_module.get_db = _backtest_get_db
_db_module._conn = None  # reset so our patched version gets called

import config
config.VERBOSE = False

# Import strategy modules WITHOUT triggering detection_strategies/__init__.py
# (which creates strategy instances that call get_db at import time).
# We use importlib to load each strategy module directly.
import importlib
import importlib.util
from dataclasses import dataclass, field


@dataclass
class Signal:
    """Mirror of detection_strategies.Signal for backtest isolation."""
    strategy: str
    severity: float
    headline: str
    trade: dict
    condition_id: str = ""
    trade_hashes: list[str] = field(default_factory=list)


def _load_strategy_module(name: str):
    """Load a strategy module from detection_strategies/ without going through __init__.py."""
    # First ensure the detection_strategies package is minimally registered
    # so that `from detection_strategies import ...` works inside the modules
    if "detection_strategies" not in sys.modules:
        import types
        pkg = types.ModuleType("detection_strategies")
        pkg.__path__ = [os.path.join(os.path.dirname(__file__), "detection_strategies")]
        pkg.__package__ = "detection_strategies"
        # Add base classes that strategies import from the package
        from abc import ABC, abstractmethod

        class DetectionStrategy(ABC):
            name: str = "unnamed"
            description: str = ""
            @abstractmethod
            def check_trade(self, trade: dict):
                ...
            def analyze_all(self, trades: list[dict]) -> list:
                return []

        pkg.Signal = Signal
        pkg.DetectionStrategy = DetectionStrategy
        sys.modules["detection_strategies"] = pkg

    module_path = os.path.join(os.path.dirname(__file__), "detection_strategies", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"detection_strategies.{name}", module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"detection_strategies.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_wrt = _load_strategy_module("win_rate_tracking")
WinRateTrackingStrategy = _wrt.WinRateTrackingStrategy

_nwlb = _load_strategy_module("new_wallet_large_bet")
NewWalletLargeBetStrategy = _nwlb.NewWalletLargeBetStrategy

_trs = _load_strategy_module("timing_relative_resolution")
TimingRelativeResolutionStrategy = _trs.TimingRelativeResolutionStrategy

_pevs = _load_strategy_module("pre_event_volume_spike")
PreEventVolumeSpikeStrategy = _pevs.PreEventVolumeSpikeStrategy

_wc = _load_strategy_module("wallet_clustering")
WalletClusteringStrategy = _wc.WalletClusteringStrategy

_cos = _load_strategy_module("concentrated_one_sided")
ConcentratedOneSidedStrategy = _cos.ConcentratedOneSidedStrategy

_ccm = _load_strategy_module("correlated_cross_market")
CorrelatedCrossMarketStrategy = _ccm.CorrelatedCrossMarketStrategy

# ---------------------------------------------------------------------------
# Event configuration
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

EVENT_SLUG = "us-strikes-iran-by"

# Key markets — the Feb 28 market is the primary target, plus longer-dated
# markets that would have seen the same spike as traders piled in.
TARGET_MARKETS = {
    "0x3488f31e6449f9803f99a8b5dd232c7ad883637f1c86e6953305a2ef19c77f20": "US strikes Iran by February 28, 2026?",
    "0x4b02efe53e631ada84681303fd66d79ad615f3d2b6a28b4633d43d935f89af58": "US strikes Iran by March 31, 2026?",
    "0x797d586ad45522306490b0cc9b2f21bdf957f3843476fae99f3bcc2cec83b74b": "US strikes Iran by June 30, 2026?",
}

# Time window: Feb 26 00:00 UTC to Mar 1 00:00 UTC (captures the spike)
WINDOW_START = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# Lower threshold to catch more trades
BET_THRESHOLD_USD = 1000

PAGE_SIZE = 1000  # Data API appears to cap at 1000 per page
FETCH_DELAY = 0.3  # seconds between API pages


# ---------------------------------------------------------------------------
# Trade fetching
# ---------------------------------------------------------------------------
def fetch_trades_for_market(condition_id: str, label: str) -> list[dict]:
    """Fetch all trades for a specific market within the time window."""
    print(f"\n  Fetching trades for: {label}")
    print(f"    condition_id: {condition_id}")

    all_trades = []
    offset = 0
    start_ts = WINDOW_START.timestamp()
    end_ts = WINDOW_END.timestamp()

    while True:
        params = {
            "limit": PAGE_SIZE,
            "offset": offset,
            "market": condition_id,
        }
        try:
            time.sleep(FETCH_DELAY)
            resp = requests.get(f"{DATA_API}/trades", params=params, timeout=30)
            if resp.status_code == 400:
                break
            resp.raise_for_status()
            page = resp.json()
        except requests.RequestException as e:
            print(f"    [ERROR] Failed at offset {offset}: {e}")
            break

        if not isinstance(page, list) or not page:
            break

        in_window = 0
        for t in page:
            ts = t.get("timestamp", 0)
            if start_ts <= ts <= end_ts:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                t["_usd_value"] = size * price
                all_trades.append(t)
                in_window += 1

        print(f"    Page {offset // PAGE_SIZE + 1}: {len(page)} trades, {in_window} in window")

        # If the oldest trade on this page is before our window start,
        # we've gone far enough back
        oldest_ts = min(t.get("timestamp", float("inf")) for t in page)
        if oldest_ts < start_ts:
            break

        if len(page) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    print(f"    Total in window: {len(all_trades)} trades")
    return all_trades


def fetch_all_event_trades() -> list[dict]:
    """Fetch trades for all target markets."""
    all_trades = []
    for cid, label in TARGET_MARKETS.items():
        trades = fetch_trades_for_market(cid, label)
        all_trades.extend(trades)

    # Deduplicate by transaction hash (a trade could appear in multiple queries)
    seen = set()
    deduped = []
    for t in all_trades:
        tx = t.get("transactionHash", "")
        if tx and tx not in seen:
            seen.add(tx)
            deduped.append(t)

    # Sort by timestamp
    deduped.sort(key=lambda t: t.get("timestamp", 0))
    return deduped


# ---------------------------------------------------------------------------
# Analysis & output
# ---------------------------------------------------------------------------
def print_trade_summary(trades: list[dict]):
    """Print an overview of the fetched trades."""
    if not trades:
        print("\n  No trades found in the window.")
        return

    total_usd = sum(t.get("_usd_value", 0) for t in trades)
    wallets = {t.get("proxyWallet", "") for t in trades} - {""}

    # Group by market
    by_market = defaultdict(list)
    for t in trades:
        by_market[t.get("conditionId", "unknown")].append(t)

    # Group by day
    by_day = defaultdict(list)
    for t in trades:
        ts = t.get("timestamp", 0)
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[day].append(t)

    print(f"\n{'=' * 72}")
    print(f"  TRADE OVERVIEW: {EVENT_SLUG}")
    print(f"{'=' * 72}")
    print(f"  Window:         {WINDOW_START.strftime('%Y-%m-%d')} to {WINDOW_END.strftime('%Y-%m-%d')}")
    print(f"  Total trades:   {len(trades)}")
    print(f"  Total volume:   ${total_usd:,.2f}")
    print(f"  Unique wallets: {len(wallets)}")

    print(f"\n  By market:")
    for cid, market_trades in sorted(by_market.items(), key=lambda x: -sum(t.get("_usd_value", 0) for t in x[1])):
        vol = sum(t.get("_usd_value", 0) for t in market_trades)
        title = market_trades[0].get("title", cid[:16])
        buys_yes = [t for t in market_trades if t.get("outcome") == "Yes" and t.get("side") == "BUY"]
        buys_no = [t for t in market_trades if t.get("outcome") == "No" and t.get("side") == "BUY"]
        print(f"    {title}")
        print(f"      {len(market_trades)} trades, ${vol:,.0f} volume")
        print(f"      YES buys: {len(buys_yes)} (${sum(t.get('_usd_value', 0) for t in buys_yes):,.0f})")
        print(f"      NO buys:  {len(buys_no)} (${sum(t.get('_usd_value', 0) for t in buys_no):,.0f})")

    print(f"\n  By day:")
    for day in sorted(by_day.keys()):
        day_trades = by_day[day]
        vol = sum(t.get("_usd_value", 0) for t in day_trades)
        day_wallets = {t.get("proxyWallet", "") for t in day_trades} - {""}
        large = [t for t in day_trades if t.get("_usd_value", 0) >= 3000]
        print(f"    {day}: {len(day_trades)} trades, ${vol:,.0f}, "
              f"{len(day_wallets)} wallets, {len(large)} >= $3k")

    # Show the largest individual trades
    print(f"\n  Top 20 largest trades:")
    sorted_trades = sorted(trades, key=lambda t: -t.get("_usd_value", 0))
    for i, t in enumerate(sorted_trades[:20], 1):
        usd = t.get("_usd_value", 0)
        wallet = t.get("proxyWallet", "???")
        short_wallet = f"{wallet[:8]}...{wallet[-6:]}" if len(wallet) > 14 else wallet
        ts = t.get("timestamp", 0)
        trade_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
        outcome = t.get("outcome", "?")
        side = t.get("side", "?")
        title = t.get("title", "?")[:40]
        print(f"    {i:>2}. ${usd:>10,.2f}  {outcome}/{side}  {trade_time}  {short_wallet}  {title}")

    print(f"{'=' * 72}")


def run_strategies(trades: list[dict]) -> list[Signal]:
    """Run detection strategies on the fetched trades."""
    # Filter to trades above threshold for strategy analysis
    large_trades = [t for t in trades if t.get("_usd_value", 0) >= BET_THRESHOLD_USD]
    print(f"\n[*] Running strategies on {len(large_trades)} trades >= ${BET_THRESHOLD_USD:,}...")

    # Per-trade strategies
    per_trade_strategies = [
        WinRateTrackingStrategy(),          # populates wallet_pnl
        NewWalletLargeBetStrategy(),        # reads wallet_pnl
        TimingRelativeResolutionStrategy(), # reads wallet_pnl
    ]

    # Batch strategies
    # NOTE: WalletClusteringStrategy is skipped — it makes hundreds of
    # Etherscan API calls (one per unique wallet) which is very slow for
    # backtesting.  ConcentratedOneSidedStrategy still runs (it only reads
    # cached funder data, so won't find Sybil overlaps without clustering,
    # but will still detect one-sided coordinated buying).
    batch_strategies = [
        PreEventVolumeSpikeStrategy(),
        # WalletClusteringStrategy(),  # too slow for backtest (Etherscan rate limits)
        ConcentratedOneSidedStrategy(),
        CorrelatedCrossMarketStrategy(),
    ]

    all_signals: list[Signal] = []

    # Per-trade phase
    for i, trade in enumerate(large_trades, 1):
        usd = trade.get("_usd_value", 0)
        title = trade.get("title", "?")
        if i % 50 == 0 or i == 1:
            print(f"  Processing trade {i}/{len(large_trades)}...")

        for strategy in per_trade_strategies:
            try:
                signal = strategy.check_trade(trade)
                if signal:
                    all_signals.append(signal)
            except Exception as e:
                pass  # strategy errors shouldn't halt backtest

    # Batch phase
    print(f"\n[*] Running batch strategies across {len(large_trades)} trades...")
    for strategy in batch_strategies:
        try:
            batch_signals = strategy.analyze_all(large_trades)
            all_signals.extend(batch_signals)
        except Exception as e:
            print(f"  [WARN] {strategy.name} failed: {e}")

    return all_signals


def format_signals(signals: list[Signal], trades: list[dict]):
    """Format and print the detection results."""
    if not signals:
        print("\n  No signals detected.")
        return

    # Group by strategy
    by_strategy = defaultdict(list)
    for s in signals:
        by_strategy[s.strategy].append(s)

    print(f"\n{'=' * 72}")
    print(f"  DETECTION RESULTS")
    print(f"{'=' * 72}")
    print(f"  Total signals: {len(signals)}")

    print(f"\n  By strategy:")
    for strat, sigs in sorted(by_strategy.items(), key=lambda x: -len(x[1])):
        max_sev = max(s.severity for s in sigs)
        print(f"    {strat}: {len(sigs)} signals (max severity: {max_sev:.1f})")

    # Show all signals sorted by severity
    print(f"\n  All signals (sorted by severity):")
    for s in sorted(signals, key=lambda x: -x.severity):
        wallet = s.trade.get("proxyWallet", "???")
        short_wallet = f"{wallet[:8]}...{wallet[-6:]}" if len(wallet) > 14 else wallet
        usd = s.trade.get("_usd_value", 0)
        ts = s.trade.get("timestamp", 0)
        trade_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
        title = s.trade.get("title", "?")[:35]
        print(f"\n    [{s.severity:.1f}] {s.strategy}")
        print(f"         {s.headline}")
        print(f"         ${usd:,.2f} | {trade_time} | {short_wallet}")
        print(f"         {title}")

    # Unique wallets flagged
    flagged_wallets = set()
    for s in signals:
        w = s.trade.get("proxyWallet", "")
        if w:
            flagged_wallets.add(w)

    print(f"\n  Unique wallets flagged: {len(flagged_wallets)}")
    for w in sorted(flagged_wallets):
        wallet_sigs = [s for s in signals if s.trade.get("proxyWallet") == w]
        total_sev = sum(s.severity for s in wallet_sigs)
        strats = {s.strategy for s in wallet_sigs}
        short = f"{w[:8]}...{w[-6:]}" if len(w) > 14 else w
        print(f"    {short}  score={total_sev:.1f}  strategies={', '.join(sorted(strats))}")

    print(f"\n{'=' * 72}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 72)
    print("  BACKTEST: US Strikes Iran Event")
    print(f"  Window: {WINDOW_START.strftime('%Y-%m-%d %H:%M UTC')} to {WINDOW_END.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Threshold: ${BET_THRESHOLD_USD:,}")
    print("=" * 72)

    # Step 1: Fetch trades
    print("\n[1/3] Fetching historical trades...")
    trades = fetch_all_event_trades()

    if not trades:
        print("\nNo trades found. The Data API may not support historical queries")
        print("by condition_id with the 'market' parameter.")
        print("\nTrying alternative: fetching from /activity endpoint...")
        # Fallback: try fetching with different API patterns
        return

    # Step 2: Print trade overview
    print("\n[2/3] Trade overview...")
    print_trade_summary(trades)

    # Step 3: Run strategies
    print("\n[3/3] Running detection strategies...")
    signals = run_strategies(trades)
    format_signals(signals, trades)

    # Cleanup
    if _backtest_conn:
        _backtest_conn.close()
    if os.path.exists(BACKTEST_DB):
        os.remove(BACKTEST_DB)

    print("\nBacktest complete.")


if __name__ == "__main__":
    main()
