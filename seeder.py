"""
Seeder module — pushes composite alerts from polybot to the hosted backend.

Called at the end of each polybot run to sync alerts to the remote database.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

from detection_strategies import Signal
from db import get_wallet_pnl_summary, get_flagged_wallet_stats

BACKEND_URL = os.environ.get("POLYBOT_BACKEND_URL", "http://localhost:8000")


def _build_dedup_key(wallet: str | None, condition_id: str, scanned_at: str) -> str:
    """Generate a dedup key so the same alert in the same scan window isn't duplicated."""
    raw = f"{wallet or 'cluster'}:{condition_id}:{scanned_at[:16]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _trade_to_dict(trade: dict) -> dict:
    """Convert a raw polybot trade dict into the API TradeIn shape."""
    ts = trade.get("timestamp", 0)
    return {
        "transaction_hash": trade.get("transactionHash", ""),
        "wallet": trade.get("proxyWallet", ""),
        "condition_id": trade.get("conditionId", ""),
        "outcome": trade.get("outcome", ""),
        "side": trade.get("side", ""),
        "usd_value": float(trade.get("_usd_value", 0)),
        "size": float(trade.get("size", 0)),
        "price": float(trade.get("price", 0)),
        "trade_timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None,
    }


def _signal_to_dict(sig: Signal) -> dict:
    return {
        "strategy": sig.strategy,
        "severity": sig.severity,
        "headline": sig.headline,
    }


def build_alerts_payload(
    signals: list[Signal], trades: list[dict]
) -> dict:
    """Build the ingest payload from polybot signals and trades.

    Mirrors the composite alert grouping logic in polybot.py but outputs
    structured dicts instead of formatted text.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Build tx_hash -> trade lookup
    tx_to_trade: dict[str, dict] = {}
    for t in trades:
        tx = t.get("transactionHash", "")
        if tx:
            tx_to_trade[tx] = t

    # Separate per-trade vs batch signals
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

    alerts: list[dict] = []
    clustered_tx_hashes: set[str] = set()
    wallets_seen: set[str] = set()

    # --- Cluster alerts (concentrated_one_sided) ---
    for cid, market_sigs in per_market.items():
        cluster_sigs = [s for s in market_sigs if s.strategy == "concentrated_one_sided"]
        if not cluster_sigs:
            continue

        cluster_sig = cluster_sigs[0]
        shared_sigs = market_sigs
        cluster_trades = [tx_to_trade[tx] for tx in cluster_sig.trade_hashes if tx in tx_to_trade]
        clustered_tx_hashes.update(cluster_sig.trade_hashes)

        # Find max composite score
        shared_total = sum(s.severity for s in shared_sigs)
        max_score = shared_total
        for tx in cluster_sig.trade_hashes:
            extra = sum(s.severity for s in per_trade.get(tx, []))
            max_score = max(max_score, shared_total + extra)

        total_usd = sum(float(t.get("_usd_value", 0)) for t in cluster_trades)
        sample = cluster_sig.trade

        # Collect all unique signals for this cluster
        all_sigs: dict[tuple[str, str], Signal] = {}
        for s in shared_sigs:
            all_sigs[(s.strategy, s.headline)] = s
        for tx in cluster_sig.trade_hashes:
            for s in per_trade.get(tx, []):
                key = (s.strategy, s.headline)
                if key not in all_sigs or s.severity > all_sigs[key].severity:
                    all_sigs[key] = s

        event_slug = sample.get("eventSlug", "")
        alerts.append({
            "alert_type": "cluster",
            "composite_score": max_score,
            "market_title": sample.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "wallet": None,
            "total_usd": total_usd,
            "trade_count": len(cluster_trades),
            "cluster_headline": cluster_sig.headline,
            "scanned_at": now,
            "dedup_key": _build_dedup_key(None, cid, now),
            "trades": [_trade_to_dict(t) for t in cluster_trades],
            "signals": [_signal_to_dict(s) for s in all_sigs.values()],
        })

        for t in cluster_trades:
            w = t.get("proxyWallet", "").lower()
            if w:
                wallets_seen.add(w)

    # --- Individual composites (grouped by wallet + event) ---
    wallet_event_groups: dict[tuple[str, str], list[tuple[str, dict, list[Signal]]]] = defaultdict(list)
    markets_with_per_trade: set[str] = set()

    for tx_hash, trade_sigs in per_trade.items():
        if tx_hash in clustered_tx_hashes:
            continue
        trade = tx_to_trade.get(tx_hash, trade_sigs[0].trade)
        cid = trade.get("conditionId", "")
        wallet = trade.get("proxyWallet", "")
        event_slug = trade.get("eventSlug", cid)
        markets_with_per_trade.add(cid)

        matching_batch = [s for s in per_market.get(cid, []) if tx_hash in s.trade_hashes]
        all_sigs_list = trade_sigs + matching_batch
        wallet_event_groups[(wallet, event_slug)].append((tx_hash, trade, all_sigs_list))

    for (wallet, evt), entries in wallet_event_groups.items():
        seen_sigs: dict[tuple[str, str], Signal] = {}
        for _, _, sigs in entries:
            for s in sigs:
                key = (s.strategy, s.headline)
                if key not in seen_sigs or s.severity > seen_sigs[key].severity:
                    seen_sigs[key] = s
        deduped_sigs = list(seen_sigs.values())
        total_severity = sum(s.severity for s in deduped_sigs)

        all_entry_trades = [e[1] for e in entries]
        total_usd = sum(float(t.get("_usd_value", 0)) for t in all_entry_trades)
        primary_trade = entries[0][1]
        cid = primary_trade.get("conditionId", "")

        alerts.append({
            "alert_type": "composite",
            "composite_score": total_severity,
            "market_title": primary_trade.get("title"),
            "condition_id": cid,
            "event_slug": evt,
            "market_url": f"https://polymarket.com/event/{evt}" if evt else None,
            "wallet": wallet,
            "total_usd": total_usd,
            "trade_count": len(all_entry_trades),
            "scanned_at": now,
            "dedup_key": _build_dedup_key(wallet, cid, now),
            "trades": [_trade_to_dict(t) for t in all_entry_trades],
            "signals": [_signal_to_dict(s) for s in deduped_sigs],
        })

        if wallet:
            wallets_seen.add(wallet.lower())

    # Batch-only markets
    for cid, market_sigs in per_market.items():
        has_cluster = any(s.strategy == "concentrated_one_sided" for s in market_sigs)
        if has_cluster or cid in markets_with_per_trade:
            continue
        trade = market_sigs[0].trade
        total_severity = sum(s.severity for s in market_sigs)
        wallet = trade.get("proxyWallet", "")
        event_slug = trade.get("eventSlug", "")

        alerts.append({
            "alert_type": "composite",
            "composite_score": total_severity,
            "market_title": trade.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "wallet": wallet,
            "total_usd": float(trade.get("_usd_value", 0)),
            "trade_count": 1,
            "scanned_at": now,
            "dedup_key": _build_dedup_key(wallet, cid, now),
            "trades": [_trade_to_dict(trade)],
            "signals": [_signal_to_dict(s) for s in market_sigs],
        })

        if wallet:
            wallets_seen.add(wallet.lower())

    # --- Build wallet profiles ---
    wallet_profiles: list[dict] = []
    for wallet in wallets_seen:
        pnl = get_wallet_pnl_summary(wallet)
        flagged = get_flagged_wallet_stats(wallet)

        closed = pnl.get("closed_positions", 0)
        wins = pnl.get("wins", 0)
        win_rate = (wins / closed) if closed > 0 else None

        wallet_profiles.append({
            "wallet": wallet,
            "total_positions": pnl.get("total_positions"),
            "closed_positions": closed,
            "wins": wins,
            "losses": pnl.get("losses"),
            "total_pnl": pnl.get("total_pnl"),
            "total_invested": pnl.get("total_invested"),
            "avg_win_price": pnl.get("avg_win_price"),
            "win_rate": win_rate,
            "times_flagged": flagged["times_flagged"] if flagged else 0,
        })

    return {
        "alerts": alerts,
        "wallet_profiles": wallet_profiles,
    }


def push_to_backend(signals: list[Signal], trades: list[dict]) -> None:
    """Build the payload and POST it to the backend ingest endpoint."""
    if not signals:
        print("[seeder] No signals to push.")
        return

    payload = build_alerts_payload(signals, trades)
    n_alerts = len(payload["alerts"])
    n_profiles = len(payload["wallet_profiles"])
    print(f"[seeder] Pushing {n_alerts} alert(s) and {n_profiles} wallet profile(s) to {BACKEND_URL}...")

    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/ingest",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        print(
            f"[seeder] Done — inserted: {result.get('inserted_alerts', 0)}, "
            f"skipped: {result.get('skipped_alerts', 0)}"
        )
    except requests.RequestException as e:
        print(f"[seeder] ERROR pushing to backend: {e}", file=sys.stderr)
