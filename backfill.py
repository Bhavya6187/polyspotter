#!/usr/bin/env python3
"""
Backfill script: fetch 30 days of historical trades from the Polymarket
Data API and populate the database tables used by detection strategies.

Tables populated:
  - tracked_bets          (win_rate_tracking)
  - wallet_event_history  (correlated_cross_market)
  - price_history         (price_impact)
  - timing_flags          (timing_relative_resolution)
  - flagged_wallets       (new_wallet_large_bet)
  - wallet_funders        (wallet_clustering)
  - market_volume_snapshots (pre_event_volume_spike)
  - wallet_pnl            (positions & P&L from Data API)
  - price_candles         (CLOB historical price time-series)
  - orderbook_snapshots   (CLOB order book depth)

Usage:
    python backfill.py [--days 30] [--threshold 3000] [--skip-etherscan] [--skip-profiles]

    --days           Number of days to backfill (default: 30)
    --threshold      Minimum USD trade size (default: 3000)
    --skip-etherscan Skip Etherscan funder lookups (wallet_clustering)
    --skip-profiles  Skip Gamma profile lookups (new_wallet_large_bet)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

from db import (
    get_db,
    record_tracked_bet,
    mark_bet_resolved,
    get_unresolved_bets_for_condition,
    record_wallet_event_trade,
    record_price_observation,
    record_timing_flag,
    record_flagged_wallet,
    record_volume_snapshot,
    save_funder,
    get_cached_funder,
    record_wallet_pnl,
    record_price_candles_batch,
    record_orderbook_snapshot,
)

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
ETHERSCAN_API = "https://api.etherscan.io/v2/api"
POLYGON_CHAIN_ID = 137

CLOB_API = "https://clob.polymarket.com"

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")

# Rate limiting delays (seconds)
GAMMA_DELAY = 0.15
ETHERSCAN_DELAY = 0.25
PROFILE_DELAY = 0.25
DATA_API_DELAY = 0.1
CLOB_DELAY = 0.1

PAGE_SIZE = 10000


# ---------------------------------------------------------------------------
# Market metadata cache (in-memory for the run)
# ---------------------------------------------------------------------------
_market_cache: dict[str, dict] = {}


def get_market(condition_id: str) -> dict | None:
    if condition_id in _market_cache:
        return _market_cache[condition_id]
    time.sleep(GAMMA_DELAY)
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"condition_ids": condition_id},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
        if markets:
            _market_cache[condition_id] = markets[0]
            return markets[0]
    except requests.RequestException as e:
        print(f"  [WARN] Market lookup failed for {condition_id[:12]}...: {e}",
              file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Wallet profile cache
# ---------------------------------------------------------------------------
_profile_cache: dict[str, tuple[datetime | None, dict]] = {}


def get_wallet_profile(address: str) -> tuple[datetime | None, dict]:
    if address in _profile_cache:
        return _profile_cache[address]
    time.sleep(PROFILE_DELAY)
    try:
        resp = requests.get(
            f"{GAMMA_API}/public-profile",
            params={"address": address},
            timeout=10,
        )
        if resp.status_code == 404:
            _profile_cache[address] = (None, {})
            return (None, {})
        resp.raise_for_status()
        profile = resp.json()
    except requests.RequestException:
        _profile_cache[address] = (None, {})
        return (None, {})

    created_str = profile.get("createdAt")
    created_at = None
    if created_str:
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    _profile_cache[address] = (created_at, profile)
    return (created_at, profile)


# ---------------------------------------------------------------------------
# Step 1: Fetch all trades
# ---------------------------------------------------------------------------
def fetch_trades(days: int, threshold: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()
    print(f"[1/11] Fetching trades >= ${threshold:,} since {cutoff.strftime('%Y-%m-%d')}...")

    all_trades: list[dict] = []
    offset = 0
    done = False

    while not done:
        params = {
            "limit": PAGE_SIZE,
            "offset": offset,
            "filterType": "CASH",
            "filterAmount": threshold,
        }
        try:
            resp = requests.get(f"{DATA_API}/trades", params=params, timeout=30)
            if resp.status_code == 400:
                break
            resp.raise_for_status()
            page = resp.json()
        except requests.RequestException as e:
            print(f"  [ERROR] Fetch failed at offset {offset}: {e}", file=sys.stderr)
            break

        if not isinstance(page, list) or not page:
            break

        page_added = 0
        for t in page:
            ts = t.get("timestamp", 0)
            if ts >= cutoff_ts:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                t["_usd_value"] = size * price
                all_trades.append(t)
                page_added += 1
            else:
                # Trades are roughly ordered newest-first; once we pass the
                # cutoff we can stop (but finish scanning this page in case
                # ordering isn't perfectly strict)
                done = True

        print(f"  offset {offset}: {page_added} trades in window "
              f"({len(all_trades)} total)")
        offset += PAGE_SIZE

    print(f"  Fetched {len(all_trades)} trades total\n")
    return all_trades


# ---------------------------------------------------------------------------
# Step 2: Backfill tracked_bets (win_rate_tracking)
# ---------------------------------------------------------------------------
def backfill_tracked_bets(trades: list[dict]) -> None:
    print(f"[2/11] Backfilling tracked_bets ({len(trades)} trades)...")
    conn = get_db()

    # Get existing (wallet, condition_id, trade_timestamp) to avoid duplicates
    existing = set()
    rows = conn.execute(
        "SELECT wallet, condition_id, trade_timestamp FROM tracked_bets"
    ).fetchall()
    for r in rows:
        existing.add((r[0], r[1], r[2]))

    inserted = 0
    for t in trades:
        wallet = t.get("proxyWallet", "").lower()
        cid = t.get("conditionId", "")
        ts = t.get("timestamp", 0)
        if not wallet or not cid:
            continue
        if (wallet, cid, ts) in existing:
            continue
        record_tracked_bet(t)
        existing.add((wallet, cid, ts))
        inserted += 1

    print(f"  Inserted {inserted} tracked bets\n")


# ---------------------------------------------------------------------------
# Step 3: Resolve tracked bets (win_rate_tracking)
# ---------------------------------------------------------------------------
def resolve_tracked_bets() -> None:
    print("[3/11] Resolving tracked bets against market outcomes...")
    conn = get_db()

    unresolved_cids = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT condition_id FROM tracked_bets WHERE resolved = 0"
        ).fetchall()
    ]
    print(f"  {len(unresolved_cids)} unresolved condition(s) to check")

    resolved_count = 0
    for i, cid in enumerate(unresolved_cids):
        if (i + 1) % 50 == 0:
            print(f"  checked {i + 1}/{len(unresolved_cids)} conditions "
                  f"({resolved_count} bets resolved)...")

        market = get_market(cid)
        if not market or not market.get("closed"):
            continue

        outcome_prices_str = market.get("outcomePrices", "")
        outcomes_str = market.get("outcomes", "")

        winning_outcome = None
        try:
            prices = json.loads(outcome_prices_str) if isinstance(outcome_prices_str, str) else outcome_prices_str
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            if prices and outcomes and len(prices) == len(outcomes):
                max_idx = prices.index(max(prices))
                if float(prices[max_idx]) >= 0.99:
                    winning_outcome = outcomes[max_idx]
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        if not winning_outcome:
            continue

        bets = get_unresolved_bets_for_condition(cid)
        for bet_id, bet_outcome, bet_side in bets:
            if bet_side == "BUY":
                won = 1 if bet_outcome == winning_outcome else 0
            else:
                won = 1 if bet_outcome != winning_outcome else 0
            mark_bet_resolved(bet_id, won)
            resolved_count += 1

    print(f"  Resolved {resolved_count} bets\n")


# ---------------------------------------------------------------------------
# Step 4: Backfill wallet_event_history (correlated_cross_market)
#         + price_history (price_impact)
#         + market_volume_snapshots (pre_event_volume_spike)
#         + timing_flags (timing_relative_resolution)
# ---------------------------------------------------------------------------
def backfill_event_price_timing_volume(trades: list[dict]) -> None:
    print("[4/11] Backfilling wallet_event_history, price_history, "
          "timing_flags, and volume snapshots...")

    conn = get_db()

    # --- Dedup sets ---
    existing_events = set()
    rows = conn.execute(
        "SELECT wallet, condition_id, trade_timestamp FROM wallet_event_history"
    ).fetchall()
    for r in rows:
        existing_events.add((r[0], r[1], r[2]))

    existing_prices = set()
    rows = conn.execute(
        "SELECT condition_id, outcome, trade_timestamp FROM price_history"
    ).fetchall()
    for r in rows:
        existing_prices.add((r[0], r[1], r[2]))

    existing_timing = set()
    rows = conn.execute(
        "SELECT wallet, condition_id, trade_timestamp FROM timing_flags"
    ).fetchall()
    for r in rows:
        existing_timing.add((r[0], r[1], r[2]))

    # --- Collect unique condition_ids for market lookups ---
    cids = {t.get("conditionId", "") for t in trades} - {""}
    print(f"  Looking up {len(cids)} unique markets for metadata...")

    market_data: dict[str, dict] = {}
    for i, cid in enumerate(cids):
        if (i + 1) % 50 == 0:
            print(f"  fetched {i + 1}/{len(cids)} markets...")
        m = get_market(cid)
        if m:
            market_data[cid] = m

    print(f"  Got metadata for {len(market_data)} markets")

    # --- Record volume snapshots (one per market) ---
    vol_recorded = 0
    for cid, m in market_data.items():
        vol_24h = float(m.get("volume24hr", 0) or 0)
        if vol_24h > 0:
            record_volume_snapshot(cid, vol_24h)
            vol_recorded += 1

    # --- Process trades ---
    evt_inserted = 0
    price_inserted = 0
    timing_inserted = 0

    for t in trades:
        wallet = t.get("proxyWallet", "").lower()
        cid = t.get("conditionId", "")
        outcome = t.get("outcome", "")
        ts = t.get("timestamp", 0)
        price = float(t.get("price", 0))
        usd = float(t.get("_usd_value", 0))

        # wallet_event_history
        event_slug = t.get("eventSlug", "")
        if wallet and event_slug and cid and (wallet, cid, ts) not in existing_events:
            record_wallet_event_trade(t)
            existing_events.add((wallet, cid, ts))
            evt_inserted += 1

        # price_history
        if cid and outcome and price > 0 and (cid, outcome, ts) not in existing_prices:
            record_price_observation(cid, outcome, price, ts)
            existing_prices.add((cid, outcome, ts))
            price_inserted += 1

        # timing_flags — check if trade was near market resolution
        if wallet and cid and cid in market_data:
            m = market_data[cid]
            end_str = m.get("endDate")
            if end_str and (wallet, cid, ts) not in existing_timing:
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    trade_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    minutes_to = (end_dt - trade_dt).total_seconds() / 60
                    if 0 <= minutes_to <= 60:
                        record_timing_flag(wallet, cid, minutes_to, usd, ts)
                        existing_timing.add((wallet, cid, ts))
                        timing_inserted += 1
                except ValueError:
                    pass

    print(f"  wallet_event_history: {evt_inserted} inserted")
    print(f"  price_history:        {price_inserted} inserted")
    print(f"  timing_flags:         {timing_inserted} inserted")
    print(f"  volume_snapshots:     {vol_recorded} inserted\n")


# ---------------------------------------------------------------------------
# Step 5: Backfill flagged_wallets (new_wallet_large_bet)
# ---------------------------------------------------------------------------
def backfill_flagged_wallets(trades: list[dict], skip_profiles: bool) -> None:
    print("[5/11] Backfilling flagged_wallets (new wallet detection)...")

    if skip_profiles:
        print("  Skipped (--skip-profiles)\n")
        return

    conn = get_db()
    existing = set()
    rows = conn.execute("SELECT wallet FROM flagged_wallets").fetchall()
    for r in rows:
        existing.add(r[0])

    # Collect unique wallets
    wallet_trades: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        w = t.get("proxyWallet", "").lower()
        if w:
            wallet_trades[w].append(t)

    wallets = list(wallet_trades.keys())
    print(f"  Checking {len(wallets)} unique wallets for profile age...")

    flagged = 0
    for i, wallet in enumerate(wallets):
        if (i + 1) % 50 == 0:
            print(f"  checked {i + 1}/{len(wallets)} wallets ({flagged} flagged)...")

        created_at, _ = get_wallet_profile(wallet)

        # Check each trade — was the wallet "new" at the time of that trade?
        for t in wallet_trades[wallet]:
            trade_ts = t.get("timestamp", 0)
            trade_dt = datetime.fromtimestamp(trade_ts, tz=timezone.utc)
            usd = float(t.get("_usd_value", 0))

            is_new = False
            if created_at is None:
                is_new = True
            else:
                age_at_trade = (trade_dt - created_at).days
                if age_at_trade <= 30:
                    is_new = True

            if is_new and wallet not in existing:
                record_flagged_wallet(wallet, usd)
                existing.add(wallet)
                flagged += 1

    print(f"  Flagged {flagged} wallets\n")


# ---------------------------------------------------------------------------
# Step 6: Backfill wallet_funders (wallet_clustering)
# ---------------------------------------------------------------------------
def backfill_wallet_funders(trades: list[dict], skip_etherscan: bool) -> None:
    print("[6/11] Backfilling wallet_funders (Etherscan funder lookups)...")

    if skip_etherscan or not ETHERSCAN_API_KEY:
        reason = "--skip-etherscan" if skip_etherscan else "no ETHERSCAN_API_KEY"
        print(f"  Skipped ({reason})\n")
        return

    wallets = {t.get("proxyWallet", "").lower() for t in trades} - {""}

    # Filter out wallets we already have cached
    to_lookup = []
    for w in wallets:
        if get_cached_funder(w) is None:
            to_lookup.append(w)

    print(f"  {len(wallets)} unique wallets, {len(to_lookup)} need Etherscan lookup...")

    looked_up = 0
    for i, wallet in enumerate(to_lookup):
        if (i + 1) % 20 == 0:
            print(f"  looked up {i + 1}/{len(to_lookup)} wallets...")

        time.sleep(ETHERSCAN_DELAY)
        try:
            resp = requests.get(
                ETHERSCAN_API,
                params={
                    "module": "account",
                    "action": "txlist",
                    "address": wallet,
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
                save_funder(wallet, funder)
                looked_up += 1
            else:
                save_funder(wallet, None)
        except requests.RequestException as e:
            print(f"  [WARN] Etherscan failed for {wallet[:10]}...: {e}",
                  file=sys.stderr)
            save_funder(wallet, None)

    print(f"  Looked up {looked_up} funder(s)\n")


# ---------------------------------------------------------------------------
# Step 7: Backfill wallet activity (full trade history per wallet via Data API)
# ---------------------------------------------------------------------------
def backfill_wallet_activity(trades: list[dict]) -> None:
    """Fetch full trade history for each wallet via /activity endpoint.

    This enriches tracked_bets, wallet_event_history, price_history, and
    timing_flags with trades that fell below the size threshold or outside
    the time window.
    """
    print("[7/11] Backfilling wallet activity (full history per wallet)...")

    conn = get_db()
    wallets = {t.get("proxyWallet", "").lower() for t in trades} - {""}
    print(f"  Fetching activity for {len(wallets)} unique wallets...")

    # Load existing dedup keys
    existing_bets = set()
    for r in conn.execute(
        "SELECT wallet, condition_id, trade_timestamp FROM tracked_bets"
    ).fetchall():
        existing_bets.add((r[0], r[1], r[2]))

    existing_events = set()
    for r in conn.execute(
        "SELECT wallet, condition_id, trade_timestamp FROM wallet_event_history"
    ).fetchall():
        existing_events.add((r[0], r[1], r[2]))

    existing_prices = set()
    for r in conn.execute(
        "SELECT condition_id, outcome, trade_timestamp FROM price_history"
    ).fetchall():
        existing_prices.add((r[0], r[1], r[2]))

    bets_added = 0
    events_added = 0
    prices_added = 0
    activity_total = 0

    for i, wallet in enumerate(wallets):
        if (i + 1) % 20 == 0:
            print(f"  processed {i + 1}/{len(wallets)} wallets "
                  f"({activity_total} activity records)...")

        # Paginate through /activity
        offset = 0
        while True:
            time.sleep(DATA_API_DELAY)
            try:
                resp = requests.get(
                    f"{DATA_API}/activity",
                    params={"user": wallet, "limit": 500, "offset": offset},
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                page = resp.json()
            except requests.RequestException:
                break

            if not isinstance(page, list) or not page:
                break

            for act in page:
                if act.get("type") != "TRADE":
                    continue
                activity_total += 1

                cid = act.get("conditionId", "")
                ts = act.get("timestamp", 0)
                outcome = act.get("outcome", "")
                side = act.get("side", "")
                price = float(act.get("price", 0) or 0)
                usdc_size = float(act.get("usdcSize", 0) or 0)
                event_slug = act.get("eventSlug", "")

                # Build a trade-like dict for existing record functions
                trade_like = {
                    "proxyWallet": wallet,
                    "conditionId": cid,
                    "outcome": outcome,
                    "side": side,
                    "price": price,
                    "timestamp": ts,
                    "eventSlug": event_slug,
                    "_usd_value": usdc_size,
                }

                # tracked_bets: record ALL trades (not just large ones)
                if wallet and cid and (wallet, cid, ts) not in existing_bets:
                    record_tracked_bet(trade_like)
                    existing_bets.add((wallet, cid, ts))
                    bets_added += 1

                # wallet_event_history
                if wallet and event_slug and cid and (wallet, cid, ts) not in existing_events:
                    record_wallet_event_trade(trade_like)
                    existing_events.add((wallet, cid, ts))
                    events_added += 1

                # price_history
                if cid and outcome and price > 0 and (cid, outcome, ts) not in existing_prices:
                    record_price_observation(cid, outcome, price, ts)
                    existing_prices.add((cid, outcome, ts))
                    prices_added += 1

            if len(page) < 500:
                break
            offset += 500

    print(f"  Total activity records processed: {activity_total}")
    print(f"  tracked_bets added:        {bets_added}")
    print(f"  wallet_event_history added: {events_added}")
    print(f"  price_history added:        {prices_added}\n")


# ---------------------------------------------------------------------------
# Step 8: Backfill wallet P&L (positions + closed-positions via Data API)
# ---------------------------------------------------------------------------
def backfill_wallet_pnl(trades: list[dict]) -> None:
    """Fetch open and closed positions for each wallet.

    /positions gives current open positions with live P&L.
    /closed-positions gives resolved positions with realized P&L.
    This directly feeds win_rate_tracking and concentrated_one_sided.
    """
    print("[8/11] Backfilling wallet P&L (positions + closed-positions)...")

    wallets = {t.get("proxyWallet", "").lower() for t in trades} - {""}
    print(f"  Fetching positions for {len(wallets)} unique wallets...")

    open_count = 0
    closed_count = 0

    for i, wallet in enumerate(wallets):
        if (i + 1) % 20 == 0:
            print(f"  processed {i + 1}/{len(wallets)} wallets "
                  f"({open_count} open, {closed_count} closed)...")

        # Open positions
        time.sleep(DATA_API_DELAY)
        try:
            resp = requests.get(
                f"{DATA_API}/positions",
                params={"user": wallet},
                timeout=15,
            )
            if resp.status_code == 200:
                positions = resp.json()
                if isinstance(positions, list):
                    for pos in positions:
                        record_wallet_pnl(wallet, pos, "open")
                        open_count += 1
        except requests.RequestException:
            pass

        # Closed positions
        time.sleep(DATA_API_DELAY)
        try:
            resp = requests.get(
                f"{DATA_API}/closed-positions",
                params={"user": wallet},
                timeout=15,
            )
            if resp.status_code == 200:
                positions = resp.json()
                if isinstance(positions, list):
                    for pos in positions:
                        record_wallet_pnl(wallet, pos, "closed")
                        closed_count += 1
        except requests.RequestException:
            pass

    print(f"  Open positions:   {open_count}")
    print(f"  Closed positions: {closed_count}\n")


# ---------------------------------------------------------------------------
# Step 9: Backfill price candles (CLOB /prices-history per token)
# ---------------------------------------------------------------------------
def backfill_price_candles(trades: list[dict]) -> None:
    """Fetch continuous price history from CLOB for each token.

    This provides much richer price data than trade-by-trade observations,
    enabling better price_impact detection (velocity, trends, anomalies).
    """
    print("[9/11] Backfilling price candles (CLOB price history)...")

    # Collect unique (condition_id, token_id, outcome) from trades
    tokens: dict[str, tuple[str, str]] = {}  # token_id -> (condition_id, outcome)
    for t in trades:
        asset = t.get("asset", "")
        cid = t.get("conditionId", "")
        outcome = t.get("outcome", "")
        if asset and cid:
            tokens[asset] = (cid, outcome)

    # Also try to get token IDs from market metadata cache
    for cid, m in _market_cache.items():
        token_ids = m.get("clobTokenIds")
        outcomes = m.get("outcomes")
        if isinstance(token_ids, list) and isinstance(outcomes, list):
            try:
                parsed_outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            except (json.JSONDecodeError, ValueError):
                parsed_outcomes = outcomes
            for j, tid in enumerate(token_ids):
                if tid and tid not in tokens:
                    outcome_name = parsed_outcomes[j] if j < len(parsed_outcomes) else ""
                    tokens[tid] = (cid, outcome_name)

    print(f"  Fetching price history for {len(tokens)} unique tokens...")

    total_candles = 0
    for i, (token_id, (cid, outcome)) in enumerate(tokens.items()):
        if (i + 1) % 50 == 0:
            print(f"  fetched {i + 1}/{len(tokens)} tokens "
                  f"({total_candles} candle points)...")

        time.sleep(CLOB_DELAY)
        try:
            resp = requests.get(
                f"{CLOB_API}/prices-history",
                params={"market": token_id, "interval": "all", "fidelity": 60},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            history = data.get("history", [])
            if history:
                inserted = record_price_candles_batch(cid, token_id, outcome, history)
                total_candles += inserted
        except requests.RequestException:
            pass

    print(f"  Total candle points recorded: {total_candles}\n")


# ---------------------------------------------------------------------------
# Step 10: Backfill order book snapshots (CLOB /book per token)
# ---------------------------------------------------------------------------
def backfill_orderbook_snapshots(trades: list[dict]) -> None:
    """Fetch current order book depth for each token.

    Captures bid/ask spread, depth, and mid-price for liquidity analysis.
    Enriches price_impact and low_activity_large_bet strategies.
    """
    print("[10/11] Backfilling order book snapshots (CLOB depth)...")

    # Collect unique tokens (only for active/open markets)
    tokens: dict[str, tuple[str, str]] = {}  # token_id -> (condition_id, outcome)
    for t in trades:
        asset = t.get("asset", "")
        cid = t.get("conditionId", "")
        outcome = t.get("outcome", "")
        if asset and cid:
            tokens[asset] = (cid, outcome)

    print(f"  Fetching order books for {len(tokens)} unique tokens...")

    recorded = 0
    for i, (token_id, (cid, outcome)) in enumerate(tokens.items()):
        if (i + 1) % 50 == 0:
            print(f"  fetched {i + 1}/{len(tokens)} order books...")

        time.sleep(CLOB_DELAY)
        try:
            resp = requests.get(
                f"{CLOB_API}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if bids or asks:
                record_orderbook_snapshot(cid, token_id, outcome, bids, asks)
                recorded += 1
        except requests.RequestException:
            pass

    print(f"  Order book snapshots recorded: {recorded}\n")


# ---------------------------------------------------------------------------
# Step 11: Summary
# ---------------------------------------------------------------------------
def print_summary() -> None:
    print("[11/11] Backfill complete. Database summary:")
    conn = get_db()

    tables = [
        ("tracked_bets", "win_rate_tracking"),
        ("wallet_event_history", "correlated_cross_market"),
        ("price_history", "price_impact"),
        ("timing_flags", "timing_relative_resolution"),
        ("flagged_wallets", "new_wallet_large_bet"),
        ("wallet_funders", "wallet_clustering"),
        ("market_volume_snapshots", "pre_event_volume_spike"),
        ("wallet_pnl", "positions & P&L"),
        ("price_candles", "CLOB price history"),
        ("orderbook_snapshots", "order book depth"),
    ]

    for table, strategy in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:30s} {count:>8,} rows  ({strategy})")

    # Win rate stats
    row = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) FROM tracked_bets"
    ).fetchone()
    total, resolved = row[0] or 0, row[1] or 0
    pct = f"{resolved/total:.0%}" if total > 0 else "n/a"
    print(f"\n  Tracked bets: {total} total, {resolved} resolved ({pct})")

    # P&L stats
    row = conn.execute(
        """SELECT COUNT(*),
                  SUM(CASE WHEN position_type='closed' AND realized_pnl > 0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN position_type='closed' AND realized_pnl <= 0 THEN 1 ELSE 0 END),
                  SUM(realized_pnl)
           FROM wallet_pnl WHERE position_type='closed'"""
    ).fetchone()
    closed = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0
    total_pnl = row[3] or 0
    print(f"  Closed positions: {closed} ({wins} wins, {losses} losses, "
          f"${total_pnl:+,.0f} total P&L)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Backfill polybot database")
    parser.add_argument("--days", type=int, default=30,
                        help="Days of history to backfill (default: 30)")
    parser.add_argument("--threshold", type=int, default=3000,
                        help="Min USD trade size (default: 3000)")
    parser.add_argument("--skip-etherscan", action="store_true",
                        help="Skip Etherscan funder lookups")
    parser.add_argument("--skip-profiles", action="store_true",
                        help="Skip Gamma profile age lookups")
    args = parser.parse_args()

    print("=" * 60)
    print("  Polybot Database Backfill")
    print("=" * 60)
    print(f"  Days:       {args.days}")
    print(f"  Threshold:  ${args.threshold:,}")
    print(f"  Etherscan:  {'skip' if args.skip_etherscan else ('enabled' if ETHERSCAN_API_KEY else 'no key')}")
    print(f"  Profiles:   {'skip' if args.skip_profiles else 'enabled'}")
    print()

    get_db()

    trades = fetch_trades(args.days, args.threshold)
    if not trades:
        print("No trades found. Nothing to backfill.")
        return

    backfill_tracked_bets(trades)
    resolve_tracked_bets()
    backfill_event_price_timing_volume(trades)
    backfill_flagged_wallets(trades, args.skip_profiles)
    backfill_wallet_funders(trades, args.skip_etherscan)
    backfill_wallet_activity(trades)
    backfill_wallet_pnl(trades)
    backfill_price_candles(trades)
    backfill_orderbook_snapshots(trades)
    print_summary()


if __name__ == "__main__":
    main()
