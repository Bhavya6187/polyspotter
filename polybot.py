#!/usr/bin/env python3
"""
Polymarket Notable Trade Scanner

Monitors Polymarket trades and surfaces large bets ($3,000+) that show
signals of informed edge — sharp bettors, coordinated flow, and
high-conviction positioning.  Strategies live in the
detection_strategies/ package.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict

# Force unbuffered stdout so progress prints appear immediately
if not os.environ.get("PYTHONUNBUFFERED"):
    sys.stdout.reconfigure(line_buffering=True)
from datetime import datetime, timezone, timedelta

import requests

from detection_strategies import Signal
from detection_strategies.win_rate_tracking import WinRateTrackingStrategy
from detection_strategies.new_wallet_large_bet import NewWalletLargeBetStrategy
from detection_strategies.timing_relative_resolution import TimingRelativeResolutionStrategy
from detection_strategies.pre_event_volume_spike import PreEventVolumeSpikeStrategy
from detection_strategies.wallet_clustering import WalletClusteringStrategy
from detection_strategies.concentrated_one_sided import ConcentratedOneSidedStrategy
from detection_strategies.price_impact import PriceImpactStrategy
from detection_strategies.low_activity_large_bet import LowActivityLargeBetStrategy
from detection_strategies.correlated_cross_market import CorrelatedCrossMarketStrategy
import config
from db import get_db, record_scan_start, record_scan_finish, get_last_scan_trade_ts
from gamma_cache import get_market_by_condition
from seeder import push_to_backend

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"

BET_THRESHOLD_USD = 3000  # minimum USD value to flag
TRADE_WINDOW_SECONDS = 6000  # how far back to look for trades
TRADE_PAGE_SIZE = 1000  # trades per API call (API max is 1,000)
MIN_MARKET_DURATION_HOURS = 1  # skip markets shorter than this (e.g., 5-min BTC binary options)
EXTREME_ODDS_THRESHOLD = 0.90  # skip trades at price > this
RESOLVED_MARKET_THRESHOLD = 0.98  # skip trades on markets where any outcome is >= this


def fetch_recent_trades(seconds: int = TRADE_WINDOW_SECONDS, since_ts: float | None = None) -> list[dict]:
    """Fetch trades from the last *seconds* seconds via the Data API,
    using server-side CASH filtering to only return trades >= threshold.

    If since_ts is provided, it overrides the seconds-based cutoff."""
    if since_ts is not None:
        cutoff = datetime.fromtimestamp(since_ts, tz=timezone.utc)
        cutoff_ts = since_ts
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        cutoff_ts = cutoff.timestamp()
    print(
        f"[*] Fetching trades >= ${BET_THRESHOLD_USD:,} since {cutoff.strftime('%Y-%m-%d %H:%M:%S UTC')}...",
        flush=True,
    )

    all_trades: list[dict] = []
    offset = 0

    while True:
        params = {
            "limit": TRADE_PAGE_SIZE,
            "offset": offset,
            "filterType": "CASH",
            "filterAmount": BET_THRESHOLD_USD,
        }
        page = None
        for attempt in range(3):
            try:
                resp = requests.get(f"{DATA_API}/trades", params=params, timeout=15)
                if resp.status_code == 400:
                    break  # API returns 400 when offset exceeds available data
                resp.raise_for_status()
                page = resp.json()
                break
            except requests.RequestException as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"[WARN] Fetch trades (offset={offset}) failed, retrying in {wait}s: {e}", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"[ERROR] Failed to fetch trades (offset={offset}) after 3 attempts: {e}", file=sys.stderr)
        if page is None:
            break

        if not isinstance(page, list) or not page:
            break

        for t in page:
            if t.get("timestamp", 0) >= cutoff_ts:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                t["_usd_value"] = size * price
                all_trades.append(t)

        offset += TRADE_PAGE_SIZE

    print(f"[*] Received {len(all_trades)} trades >= ${BET_THRESHOLD_USD:,} within the last {seconds}s", flush=True)
    return all_trades


def _parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def filter_short_markets(trades: list[dict]) -> list[dict]:
    """Remove trades on markets with duration < MIN_MARKET_DURATION_HOURS.

    Groups by conditionId so each market is looked up only once."""
    condition_ids = {t.get("conditionId", "") for t in trades if t.get("conditionId")}
    short_cids: set[str] = set()

    print(f"[*] Checking {len(condition_ids)} market(s) for duration filter...", flush=True)
    for cid in condition_ids:
        market = get_market_by_condition(cid)
        if not market:
            continue
        start = _parse_datetime(market.get("startDate"))
        end = _parse_datetime(market.get("endDate"))
        if start and end:
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours < MIN_MARKET_DURATION_HOURS:
                short_cids.add(cid)

    if not short_cids:
        return trades

    filtered = [t for t in trades if t.get("conditionId", "") not in short_cids]
    removed = len(trades) - len(filtered)
    print(f"[*] Filtered {removed} trade(s) on {len(short_cids)} short-duration market(s) (< {MIN_MARKET_DURATION_HOURS}h)", flush=True)
    return filtered


def _is_penny_collecting(trade: dict) -> bool:
    """Return True if a trade is penny-collecting on a near-certain outcome.

    BUY at high price (>0.90) = paying 95c to win 5c on a heavy favorite.
    SELL at low price (<0.10) = collecting 5c against a long-shot.
    Both are tiny-edge, low-conviction plays — not informed positioning."""
    price = float(trade.get("price", 0.5))
    side = trade.get("side", "").upper()
    lo = 1 - EXTREME_ODDS_THRESHOLD
    hi = EXTREME_ODDS_THRESHOLD
    return (side == "BUY" and price > hi) or (side == "SELL" and price < lo)


def filter_extreme_odds(trades: list[dict]) -> list[dict]:
    """Remove penny-collecting trades at extreme odds."""
    filtered = [t for t in trades if not _is_penny_collecting(t)]
    removed = len(trades) - len(filtered)
    if removed:
        print(f"[*] Filtered {removed} penny-collecting trade(s) at extreme odds", flush=True)
    return filtered


def filter_resolved_markets(trades: list[dict]) -> list[dict]:
    """Remove trades on markets that are effectively resolved.

    A market is considered resolved when any outcome's current price is
    >= RESOLVED_MARKET_THRESHOLD (0.98).  Trading on these markets is
    just collecting pennies on a known result — not informed positioning.

    Uses the Gamma API market cache (already populated by
    filter_short_markets) so this adds zero extra API calls."""
    condition_ids = {t.get("conditionId", "") for t in trades if t.get("conditionId")}
    resolved_cids: set[str] = set()

    for cid in condition_ids:
        market = get_market_by_condition(cid)
        if not market:
            continue
        try:
            prices = json.loads(market.get("outcomePrices", "[]"))
        except (json.JSONDecodeError, TypeError):
            continue
        if any(float(p) >= RESOLVED_MARKET_THRESHOLD for p in prices):
            resolved_cids.add(cid)

    if not resolved_cids:
        return trades

    filtered = [t for t in trades if t.get("conditionId", "") not in resolved_cids]
    removed = len(trades) - len(filtered)
    print(
        f"[*] Filtered {removed} trade(s) on {len(resolved_cids)} resolved market(s) "
        f"(outcome price >= {RESOLVED_MARKET_THRESHOLD:.0%})",
        flush=True,
    )
    return filtered


# ---------------------------------------------------------------------------
# Composite alert formatting
# ---------------------------------------------------------------------------
def _format_one_composite(
    trade: dict, sigs: list[Signal], total_severity: float, extra_trades: list[dict] | None = None
) -> str:
    """Format a single composite alert block.

    If extra_trades is provided, shows a consolidated view of multiple trades
    by the same wallet on the same market."""
    wallet = trade.get("proxyWallet", "???")
    short_wallet = f"{wallet[:8]}...{wallet[-6:]}" if len(wallet) > 14 else wallet

    signal_lines = []
    for s in sorted(sigs, key=lambda x: -x.severity):
        signal_lines.append(f"    [{s.severity:.1f}]  {s.strategy}: {s.headline}")

    all_trades = [trade] + (extra_trades or [])
    total_usd = sum(float(t.get("_usd_value", 0)) for t in all_trades)

    lines = [
        "",
        "=" * 72,
        f"  COMPOSITE ALERT  [Score: {total_severity:.1f}]",
        "=" * 72,
        f"  Market:     {trade.get('title', '?')}",
    ]

    if len(all_trades) == 1:
        usd = float(trade.get("_usd_value", 0))
        ts = trade.get("timestamp", 0)
        trade_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(f"  Trade:      ${usd:,.2f} — {trade.get('outcome', '?')} ({trade.get('side', '?')})")
        lines.append(f"  Time:       {trade_time}")
    else:
        lines.append(f"  Total:      ${total_usd:,.2f} across {len(all_trades)} trades")
        for t in sorted(all_trades, key=lambda x: -float(x.get("_usd_value", 0))):
            usd = float(t.get("_usd_value", 0))
            ts = t.get("timestamp", 0)
            t_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S UTC")
            lines.append(f"    ${usd:>10,.2f}  {t.get('outcome', '?')} ({t.get('side', '?')})  {t_time}")

    lines.extend(
        [
            f"  Wallet:     {short_wallet}",
            f"  Signals:",
            *signal_lines,
            f"  Market Slug: https://polymarket.com/event/{trade.get('eventSlug', '')}",
            "=" * 72,
            "",
        ]
    )
    return "\n".join(lines)


def _format_cluster_alert(
    cluster_sig: Signal,
    cluster_trades: list[dict],
    shared_sigs: list[Signal],
    per_trade_sigs: dict[str, list[Signal]],
) -> tuple[float, str]:
    """Format a single cluster alert showing all member trades in one block."""
    sample = cluster_sig.trade
    shared_total = sum(s.severity for s in shared_sigs)
    max_score = shared_total

    trade_rows: list[str] = []
    for t in sorted(cluster_trades, key=lambda x: -float(x.get("_usd_value", 0))):
        tx = t.get("transactionHash", "")
        wallet = t.get("proxyWallet", "???")
        short_wallet = f"{wallet[:8]}...{wallet[-6:]}" if len(wallet) > 14 else wallet
        usd = float(t.get("_usd_value", 0))
        ts = t.get("timestamp", 0)
        trade_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S UTC")

        extra_sigs = per_trade_sigs.get(tx, [])
        extra_total = sum(s.severity for s in extra_sigs)
        max_score = max(max_score, shared_total + extra_total)

        extra_str = ""
        if extra_sigs:
            parts = [f"+{s.severity:.1f} {s.headline}" for s in sorted(extra_sigs, key=lambda x: -x.severity)]
            extra_str = "  (" + ", ".join(parts) + ")"

        trade_rows.append(f"    ${usd:>10,.2f}  {short_wallet}  {trade_time}{extra_str}")

    signal_lines = []
    for s in sorted(shared_sigs, key=lambda x: -x.severity):
        signal_lines.append(f"    [{s.severity:.1f}]  {s.strategy}: {s.headline}")

    lines = [
        "",
        "=" * 72,
        f"  CLUSTER ALERT  [Score: {max_score:.1f}]",
        "=" * 72,
        f"  Market:     {sample.get('title', '?')}",
        f"  Cluster:    {cluster_sig.headline}",
        f"  Signals:",
        *signal_lines,
        f"  Trades ({len(cluster_trades)}):",
        *trade_rows,
        f"  Market Slug: https://polymarket.com/event/{sample.get('eventSlug', '')}",
        "=" * 72,
        "",
    ]
    return (max_score, "\n".join(lines))


def _format_composite_alerts(signals: list[Signal], trades: list[dict]) -> str:
    """Group signals by trade, compute composite scores, and format output.

    Per-trade signals are grouped by transaction hash.  Batch signals
    (those with trade_hashes spanning multiple trades) are grouped once
    per market (condition_id) and merged into per-trade composites to
    avoid duplicate alerts.

    concentrated_one_sided signals are rendered as a single cluster alert
    per market, listing all member trades, instead of repeating the
    cluster info on every individual trade.
    """
    if not signals:
        return ""

    # Build tx_hash -> actual trade dict lookup from the original trades
    tx_to_trade: dict[str, dict] = {}
    for t in trades:
        tx = t.get("transactionHash", "")
        if tx:
            tx_to_trade[tx] = t

    # Separate per-trade signals from batch (market-level) signals
    per_trade: dict[str, list[Signal]] = defaultdict(list)
    per_market: dict[str, list[Signal]] = defaultdict(list)

    for sig in signals:
        if sig.trade_hashes:
            cid = sig.condition_id or sig.trade.get("conditionId", "")
            if cid:
                per_market[cid].append(sig)
        else:
            tx = sig.trade.get("transactionHash", "")
            if tx:
                per_trade[tx].append(sig)

    # --- Cluster alerts for concentrated_one_sided --------------------------
    composites: list[tuple[float, str]] = []
    clustered_tx_hashes: set[str] = set()

    for cid, market_sigs in per_market.items():
        cluster_sigs = [s for s in market_sigs if s.strategy == "concentrated_one_sided"]
        if not cluster_sigs:
            continue

        cluster_sig = cluster_sigs[0]
        # Shared signals = all batch signals for this market
        shared_sigs = market_sigs

        # Gather trades in this cluster
        cluster_trades = [tx_to_trade[tx] for tx in cluster_sig.trade_hashes if tx in tx_to_trade]
        clustered_tx_hashes.update(cluster_sig.trade_hashes)

        # Collect per-trade signals for trades in this cluster
        cluster_per_trade: dict[str, list[Signal]] = {}
        for tx in cluster_sig.trade_hashes:
            if tx in per_trade:
                cluster_per_trade[tx] = per_trade[tx]

        composites.append(
            _format_cluster_alert(
                cluster_sig,
                cluster_trades,
                shared_sigs,
                cluster_per_trade,
            )
        )

    # --- Individual composites for non-clustered trades ---------------------
    # Group by (wallet, eventSlug) to consolidate same-wallet-same-event
    # This merges trades across related markets (e.g., spread lines for the
    # same game) into a single alert instead of fragmenting them.
    markets_with_per_trade: set[str] = set()
    wallet_event_groups: dict[tuple[str, str], list[tuple[str, dict, list[Signal]]]] = defaultdict(list)

    for tx_hash, trade_sigs in per_trade.items():
        if tx_hash in clustered_tx_hashes:
            continue
        trade = tx_to_trade.get(tx_hash, trade_sigs[0].trade)
        cid = trade.get("conditionId", "")
        wallet = trade.get("proxyWallet", "")
        event_slug = trade.get("eventSlug", cid)  # fall back to cid
        markets_with_per_trade.add(cid)

        matching_batch = [s for s in per_market.get(cid, []) if tx_hash in s.trade_hashes]
        all_sigs = trade_sigs + matching_batch
        wallet_event_groups[(wallet, event_slug)].append((tx_hash, trade, all_sigs))

    for (wallet, _evt), entries in wallet_event_groups.items():
        # Deduplicate signals: keep highest severity per (strategy, headline)
        seen_sigs: dict[tuple[str, str], Signal] = {}
        for _, _, sigs in entries:
            for s in sigs:
                key = s.dedup_key
                if key not in seen_sigs or s.severity > seen_sigs[key].severity:
                    seen_sigs[key] = s
        deduped_sigs = list(seen_sigs.values())
        total_severity = sum(s.severity for s in deduped_sigs)

        primary_trade = entries[0][1]
        extra_trades = [e[1] for e in entries[1:]] if len(entries) > 1 else None
        composites.append(
            (total_severity, _format_one_composite(primary_trade, deduped_sigs, total_severity, extra_trades))
        )

    # Markets that ONLY have batch signals (no per-trade or cluster signals)
    for cid, market_sigs in per_market.items():
        has_cluster = any(s.strategy == "concentrated_one_sided" for s in market_sigs)
        if has_cluster or cid in markets_with_per_trade:
            continue
        trade = market_sigs[0].trade
        total_severity = sum(s.severity for s in market_sigs)
        composites.append((total_severity, _format_one_composite(trade, market_sigs, total_severity)))

    # Sort by severity descending
    composites.sort(key=lambda x: -x[0])
    return "\n".join(text for _, text in composites)


def _format_summary(trades: list[dict], signals: list[Signal], strategy_names: str) -> str:
    """Format a ranked summary of the most notable activity."""
    # Build tx_hash -> actual trade dict lookup
    tx_to_trade: dict[str, dict] = {}
    for t in trades:
        tx = t.get("transactionHash", "")
        if tx:
            tx_to_trade[tx] = t

    # Separate per-trade signals from batch signals (same logic as composites)
    per_trade: dict[str, list[Signal]] = defaultdict(list)
    per_market: dict[str, list[Signal]] = defaultdict(list)

    for sig in signals:
        if sig.trade_hashes:
            cid = sig.condition_id or sig.trade.get("conditionId", "")
            if cid:
                per_market[cid].append(sig)
        else:
            tx = sig.trade.get("transactionHash", "")
            if tx:
                per_trade[tx].append(sig)

    # --- Cluster entries for concentrated_one_sided -------------------------
    ranked_entries: list[tuple[float, str]] = []
    clustered_tx_hashes: set[str] = set()

    for cid, market_sigs in per_market.items():
        cluster_sigs = [s for s in market_sigs if s.strategy == "concentrated_one_sided"]
        if not cluster_sigs:
            continue
        cluster_sig = cluster_sigs[0]
        shared_total = sum(s.severity for s in market_sigs)
        # Find max score across cluster trades (shared + per-trade)
        max_score = shared_total
        for tx in cluster_sig.trade_hashes:
            extra = sum(s.severity for s in per_trade.get(tx, []))
            max_score = max(max_score, shared_total + extra)

        total_usd = sum(
            float(tx_to_trade[tx].get("_usd_value", 0)) for tx in cluster_sig.trade_hashes if tx in tx_to_trade
        )
        n_trades = len(cluster_sig.trade_hashes)
        title = cluster_sig.trade.get("title", "?")
        n_sigs = len(market_sigs)
        ranked_entries.append(
            (
                max_score,
                f'    [{max_score:.1f}]  CLUSTER: ${total_usd:,.2f} across {n_trades} trades on "{title}" ({n_sigs} signal{"s" if n_sigs != 1 else ""})',
            )
        )
        clustered_tx_hashes.update(cluster_sig.trade_hashes)

    # --- Individual trade entries (grouped by wallet + event) ----------------
    markets_with_per_trade: set[str] = set()
    wallet_event_groups: dict[tuple[str, str], list[tuple[str, dict, list[Signal]]]] = defaultdict(list)

    for tx_hash, trade_sigs in per_trade.items():
        if tx_hash in clustered_tx_hashes:
            continue
        trade = tx_to_trade.get(tx_hash, trade_sigs[0].trade)
        cid = trade.get("conditionId", "")
        wallet = trade.get("proxyWallet", "")
        event_slug = trade.get("eventSlug", cid)
        markets_with_per_trade.add(cid)

        matching_batch = [s for s in per_market.get(cid, []) if tx_hash in s.trade_hashes]
        all_sigs = trade_sigs + matching_batch
        wallet_event_groups[(wallet, event_slug)].append((tx_hash, trade, all_sigs))

    individual_entries: list[tuple[float, str]] = []
    for (wallet, _evt), entries in wallet_event_groups.items():
        seen_sigs: dict[tuple[str, str], Signal] = {}
        for _, _, sigs in entries:
            for s in sigs:
                key = s.dedup_key
                if key not in seen_sigs or s.severity > seen_sigs[key].severity:
                    seen_sigs[key] = s
        deduped_sigs = list(seen_sigs.values())
        score = sum(s.severity for s in deduped_sigs)
        n = len(deduped_sigs)
        total_usd = sum(float(e[1].get("_usd_value", 0)) for e in entries)
        title = entries[0][1].get("title", "?")
        n_trades = len(entries)
        trade_str = f" ({n_trades} trades)" if n_trades > 1 else ""
        individual_entries.append(
            (
                score,
                f'    [{score:.1f}]  ${total_usd:,.2f}{trade_str} on "{title}" ({n} signal{"s" if n != 1 else ""})',
            )
        )

    # Batch-only markets (no cluster, no per-trade)
    for cid, market_sigs in per_market.items():
        has_cluster = any(s.strategy == "concentrated_one_sided" for s in market_sigs)
        if has_cluster or cid in markets_with_per_trade:
            continue
        score = sum(s.severity for s in market_sigs)
        n = len(market_sigs)
        trade = market_sigs[0].trade
        title = trade.get("title", "?")
        usd = float(trade.get("_usd_value", 0))
        individual_entries.append(
            (
                score,
                f'    [{score:.1f}]  ${usd:,.2f} on "{title}" ({n} signal{"s" if n != 1 else ""})',
            )
        )

    ranked_entries.sort(key=lambda x: -x[0])
    individual_entries.sort(key=lambda x: -x[0])
    unique_alerts = len(ranked_entries) + len(individual_entries)

    lines = [
        "",
        "-" * 72,
        "  Summary",
        f"    Trades scanned:       {len(trades)}",
        f"    Signals raised:       {len(signals)}",
        f"    Unique alerts:        {unique_alerts}",
        f"    Strategies used:      {strategy_names}",
    ]

    if ranked_entries:
        lines.append("")
        lines.append("  Top cluster alerts:")
        for _, text in ranked_entries[:5]:
            lines.append(text)

    if individual_entries:
        lines.append("")
        lines.append("  Top individual alerts:")
        for _, text in individual_entries[:5]:
            lines.append(text)

    lines.append("-" * 72)
    return "\n".join(lines)


OVERLAP_SECONDS = 600  # 10 minutes overlap between scan windows


def _build_strategies():
    """Build and return (per_trade, batch, all, strategy_names)."""
    # -------------------------------------------------------------------------
    # Strategy execution order (data dependencies documented inline)
    #
    # Per-trade phase (check_trade): runs once per trade, in this order:
    #   1. win_rate_tracking    — populates wallet_pnl table via Data API
    #   2. new_wallet_large_bet — reads wallet_pnl (from step 1)
    #   3. timing_relative_resolution — reads wallet_pnl (from step 1)
    #   4. low_activity_large_bet     — independent (fetches own orderbook)
    #
    # Batch phase (analyze_all): runs once across all trades, in this order:
    #   5. pre_event_volume_spike     — independent
    #   6. wallet_clustering          — writes funder data to wallet_funders table
    #   7. concentrated_one_sided     — reads funder data (from step 6)
    #   8. price_impact               — independent (fetches own candles/orderbook)
    #   9. correlated_cross_market    — independent
    # -------------------------------------------------------------------------
    per_trade = [
        WinRateTrackingStrategy(),  # 1. writes wallet_pnl
        NewWalletLargeBetStrategy(),  # 2. reads wallet_pnl
        TimingRelativeResolutionStrategy(),  # 3. reads wallet_pnl
        LowActivityLargeBetStrategy(),  # 4. independent
    ]
    batch = [
        PreEventVolumeSpikeStrategy(),  # 5. independent
        WalletClusteringStrategy(),  # 6. writes wallet_funders
        ConcentratedOneSidedStrategy(),  # 7. reads wallet_funders
        PriceImpactStrategy(),  # 8. independent
        CorrelatedCrossMarketStrategy(),  # 9. independent
    ]
    all_strats = per_trade + batch
    names = ", ".join(s.name for s in all_strats)
    return per_trade, batch, all_strats, names


def scan_once(per_trade_strategies, batch_strategies, all_strategies, strategy_names,
              since_ts: float | None = None) -> float | None:
    """Run a single scan iteration.  Returns the latest trade timestamp seen, or None."""
    run_id = record_scan_start(cutoff_ts=since_ts)

    try:
        if since_ts is not None:
            trades = fetch_recent_trades(since_ts=since_ts)
        else:
            trades = fetch_recent_trades()

        trades_before_filter = len(trades)

        if not trades:
            print("\n[*] No trades above threshold found.")
            record_scan_finish(run_id, trades_before_filter=0, trades_scanned=0)
            return None

        trades = filter_short_markets(trades)
        trades = filter_resolved_markets(trades)
        trades = filter_extreme_odds(trades)

        if not trades:
            print("\n[*] All trades filtered out.")
            record_scan_finish(run_id, trades_before_filter=trades_before_filter, trades_scanned=0)
            return None

        unique_markets = len({t.get("conditionId", "") for t in trades if t.get("conditionId")})

        print(f"\n[*] Running {len(all_strategies)} strategy(ies) on {len(trades)} trade(s)...", flush=True)
        all_signals: list[Signal] = []

        # -- per-trade analysis ----------------------------------------------------
        from detection_strategies import win_rate_tracking as _wrt
        _wrt._total_unique_wallets = len({t.get("proxyWallet", "").lower() for t in trades} - {""})
        per_trade_signal_count = 0
        for i, trade in enumerate(trades, 1):
            usd = trade.get("_usd_value", 0)
            title = trade.get("title", "?")
            if config.VERBOSE:
                print(f'\n  [{i}/{len(trades)}] ${usd:,.2f} on "{title}"')
            elif i == 1 or i % 25 == 0 or i == len(trades):
                print(
                    f"  Per-trade analysis: {i}/{len(trades)} trades processed ({per_trade_signal_count} signals so far)",
                    flush=True,
                )

            for strategy in per_trade_strategies:
                signal = strategy.check_trade(trade)
                if signal:
                    all_signals.append(signal)
                    per_trade_signal_count += 1

        # -- batch analysis --------------------------------------------------------
        print(f"\n[*] Running batch analysis across all {len(trades)} trade(s)...", flush=True)
        for strategy in batch_strategies:
            print(f"  Running {strategy.name}...", flush=True)
            batch_signals = strategy.analyze_all(trades)
            if batch_signals:
                print(f"    -> {len(batch_signals)} signal(s)")
            all_signals.extend(batch_signals)

        # -- composite output ------------------------------------------------------
        print(f"\n[*] Compositing {len(all_signals)} signal(s) into deduplicated alerts...", flush=True)
        print(_format_composite_alerts(all_signals, trades))
        print(_format_summary(trades, all_signals, strategy_names))

        # -- push to backend -------------------------------------------------------
        alerts_pushed = push_to_backend(all_signals, trades)

        # -- record scan run -------------------------------------------------------
        latest_ts = max((t.get("timestamp", 0) for t in trades), default=None)
        record_scan_finish(
            run_id,
            latest_trade_ts=latest_ts,
            trades_before_filter=trades_before_filter,
            trades_scanned=len(trades),
            signals_raised=len(all_signals),
            unique_markets=unique_markets,
            alerts_pushed=alerts_pushed,
        )

        return latest_ts

    except Exception as e:
        record_scan_finish(run_id, error=str(e))
        raise


def run():
    parser = argparse.ArgumentParser(description="Polymarket Notable Trade Scanner")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-trade detail logging (cache hits, ok results, cluster lines)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (legacy behavior)",
    )
    args = parser.parse_args()

    config.VERBOSE = args.verbose

    # Ensure the database is initialized before strategies run
    get_db()

    per_trade_strategies, batch_strategies, all_strategies, strategy_names = _build_strategies()

    print("=" * 72)
    mode = "single run" if args.once else "continuous"
    print(f"  Polymarket Notable Trade Scanner ({mode})")
    print("=" * 72)
    print(f"  Bet threshold:  ${BET_THRESHOLD_USD:,}")
    print(f"  Trade window:   last {TRADE_WINDOW_SECONDS}s (initial)")
    print(f"  Overlap:        {OVERLAP_SECONDS}s between iterations")
    print(f"  Min market dur: {MIN_MARKET_DURATION_HOURS}h")
    print(f"  Strategies:     {strategy_names}")
    print()

    if args.once:
        scan_once(per_trade_strategies, batch_strategies, all_strategies, strategy_names)
        print("Done.")
        return

    # -- continuous mode -------------------------------------------------------
    iteration = 0
    while True:
        iteration += 1

        # Determine the cutoff: use last scan's latest trade ts minus overlap,
        # or fall back to the default window on first run.
        last_ts = get_last_scan_trade_ts()
        if last_ts is not None:
            since_ts = last_ts - OVERLAP_SECONDS
            since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
            print(f"\n{'#' * 72}")
            print(f"  Iteration {iteration} — scanning from {since_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                  f"(last trade minus {OVERLAP_SECONDS // 60}min overlap)")
            print(f"{'#' * 72}\n")
        else:
            since_ts = None
            print(f"\n{'#' * 72}")
            print(f"  Iteration {iteration} — first run, using default {TRADE_WINDOW_SECONDS}s window")
            print(f"{'#' * 72}\n")

        try:
            scan_once(per_trade_strategies, batch_strategies, all_strategies,
                      strategy_names, since_ts=since_ts)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"\n[ERROR] Scan iteration {iteration} failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

        # Wait before the next iteration
        wait = 60
        print(f"\n[*] Sleeping {wait}s before next iteration (Ctrl+C to stop)...", flush=True)
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\n[*] Interrupted — shutting down.")
            break


if __name__ == "__main__":
    run()
