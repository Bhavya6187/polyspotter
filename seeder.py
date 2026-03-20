"""
Seeder module — pushes composite alerts from polybot to the hosted backend.

Called at the end of each polybot run to sync alerts to the remote database.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import dateparser

import requests
from dotenv import load_dotenv

from detection_strategies import Signal
from db import get_wallet_pnl_summary, get_flagged_wallet_stats
from gamma_cache import get_market_tags, get_market_by_condition

load_dotenv()

BACKEND_URL = os.environ.get("POLYBOT_BACKEND_URL", "http://localhost:8000")

# When a cluster alert exists for an event with score >= this threshold,
# cap the number of individual composite alerts on the same event.
CLUSTER_SCORE_THRESHOLD = 15.0
MAX_INDIVIDUAL_PER_CLUSTERED_EVENT = 3


def _build_dedup_key(
    wallet: str | None,
    condition_id: str,
    tx_hashes: list[str] | None = None,
    cluster_direction: str | None = None,
) -> str:
    """Generate a stable dedup key for the backend (identity-based).

    For cluster alerts (wallet=None), the key uses condition_id + direction
    (outcome/side) so that distinct clusters on the same market stay separate
    while a growing cluster keeps the same key across runs — allowing the
    backend to upsert updated data.
    For individual/composite alerts, the key includes the sorted tx hashes
    so distinct trade sets on the same market stay separate."""
    if wallet is None:
        raw = f"cluster:{condition_id}:{cluster_direction or ''}"
    else:
        sorted_hashes = ",".join(sorted(tx_hashes)) if tx_hashes else ""
        raw = f"{wallet}:{condition_id}:{sorted_hashes}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_llm_cache_key(
    wallet: str | None,
    condition_id: str,
    tx_hashes: list[str] | None = None,
    cluster_direction: str | None = None,
    trade_count: int = 0,
    composite_score: float = 0.0,
) -> str:
    """Generate a content-sensitive cache key for LLM evaluations.

    Unlike the backend dedup key (which is stable for upserts), this key
    changes when the alert's content materially changes — forcing the LLM
    to re-evaluate. For clusters, trade_count and composite_score are
    included so a growing cluster (2→6 wallets, higher score) gets a
    fresh LLM evaluation instead of serving a stale cached verdict."""
    if wallet is None:
        raw = f"llm:cluster:{condition_id}:{cluster_direction or ''}:{trade_count}:{composite_score:.1f}"
    else:
        sorted_hashes = ",".join(sorted(tx_hashes)) if tx_hashes else ""
        raw = f"llm:{wallet}:{condition_id}:{sorted_hashes}"
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


def _resolve_tags(condition_id: str | None) -> list[str]:
    """Look up market tags from Gamma API event tags."""
    if not condition_id:
        return []
    return get_market_tags(condition_id)


_DEADLINE_RE = re.compile(r"(?:by|before)\s+(.+?)(?:\?|$)", re.IGNORECASE)


def _parse_end_date_from_title(title: str) -> str | None:
    """Try to extract a deadline date from a market title.

    Handles titles like "US x Iran ceasefire by March 31?" where Polymarket
    didn't set an endDate in the API.  Returns an ISO 8601 string matching
    the format used by the Gamma API (e.g. "2026-03-31T12:00:00Z")."""
    m = _DEADLINE_RE.search(title)
    if not m:
        return None
    dt = dateparser.parse(
        m.group(1).strip(),
        settings={"PREFER_DATES_FROM": "future", "TIMEZONE": "UTC",
                  "RETURN_AS_TIMEZONE_AWARE": True},
    )
    if not dt:
        return None
    # Normalize to noon UTC to match Gamma API convention
    dt = dt.replace(hour=12, minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_end_date(condition_id: str | None) -> str | None:
    """Look up market end date from Gamma API metadata.

    Falls back to parsing the date from the market title when the API
    doesn't include an endDate (e.g. "ceasefire by March 31?")."""
    if not condition_id:
        return None
    market = get_market_by_condition(condition_id)
    if not market:
        return None
    if market.get("endDate"):
        return market["endDate"]
    # Fallback: infer from title
    title = market.get("question") or market.get("title") or ""
    return _parse_end_date_from_title(title)


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
            all_sigs[s.dedup_key] = s
        for tx in cluster_sig.trade_hashes:
            for s in per_trade.get(tx, []):
                key = s.dedup_key
                if key not in all_sigs or s.severity > all_sigs[key].severity:
                    all_sigs[key] = s

        event_slug = sample.get("eventSlug", "")
        cluster_dir = f"{sample.get('outcome', '')}:{sample.get('side', '')}"
        alerts.append({
            "alert_type": "cluster",
            "composite_score": max_score,
            "tags": _resolve_tags(cid),
            "market_title": sample.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "wallet": None,
            "total_usd": total_usd,
            "trade_count": len(cluster_trades),
            "cluster_headline": cluster_sig.headline,
            "end_date": _resolve_end_date(cid),
            "scanned_at": now,
            "dedup_key": _build_dedup_key(
                None, cid, cluster_direction=cluster_dir,
            ),
            "llm_cache_key": _build_llm_cache_key(
                None, cid, cluster_direction=cluster_dir,
                trade_count=len(cluster_trades), composite_score=max_score,
            ),
            "trades": [_trade_to_dict(t) for t in cluster_trades],
            "signals": [_signal_to_dict(s) for s in all_sigs.values()],
        })

        for t in cluster_trades:
            w = t.get("proxyWallet", "").lower()
            if w:
                wallets_seen.add(w)

    # --- Build a set of (wallet, event) combos already in cluster alerts ---
    # so we can skip individual alerts that only add correlated_cross_market
    # noise on top of an existing cluster.
    clustered_wallet_events: set[tuple[str, str]] = set()
    for cid, market_sigs in per_market.items():
        cluster_sigs = [s for s in market_sigs if s.strategy == "concentrated_one_sided"]
        for cs in cluster_sigs:
            for tx in cs.trade_hashes:
                t = tx_to_trade.get(tx)
                if t:
                    w = t.get("proxyWallet", "").lower()
                    evt = t.get("eventSlug", "")
                    if w and evt:
                        clustered_wallet_events.add((w, evt))

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
                key = s.dedup_key
                if key not in seen_sigs or s.severity > seen_sigs[key].severity:
                    seen_sigs[key] = s
        deduped_sigs = list(seen_sigs.values())
        total_severity = sum(s.severity for s in deduped_sigs)

        # Skip if this wallet is already in a cluster alert for the same event
        # and the only signals here are correlated_cross_market — no new info.
        if (wallet.lower(), evt) in clustered_wallet_events:
            strategies_here = {s.strategy for s in deduped_sigs}
            if strategies_here == {"correlated_cross_market"}:
                continue

        all_entry_trades = [e[1] for e in entries]
        total_usd = sum(float(t.get("_usd_value", 0)) for t in all_entry_trades)
        primary_trade = entries[0][1]
        cid = primary_trade.get("conditionId", "")

        alerts.append({
            "alert_type": "composite",
            "composite_score": total_severity,
            "tags": _resolve_tags(cid),
            "market_title": primary_trade.get("title"),
            "condition_id": cid,
            "event_slug": evt,
            "market_url": f"https://polymarket.com/event/{evt}" if evt else None,
            "wallet": wallet,
            "total_usd": total_usd,
            "trade_count": len(all_entry_trades),
            "end_date": _resolve_end_date(cid),
            "scanned_at": now,
            "dedup_key": _build_dedup_key(wallet, cid, [e[0] for e in entries]),
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
            "tags": _resolve_tags(cid),
            "market_title": trade.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "wallet": wallet,
            "total_usd": float(trade.get("_usd_value", 0)),
            "trade_count": 1,
            "end_date": _resolve_end_date(cid),
            "scanned_at": now,
            "dedup_key": _build_dedup_key(wallet, cid, [trade.get("transactionHash", "")]),
            "trades": [_trade_to_dict(trade)],
            "signals": [_signal_to_dict(s) for s in market_sigs],
        })

        if wallet:
            wallets_seen.add(wallet.lower())

    # --- Cap individual alerts on events that already have a strong cluster --
    # When a cluster alert scores >= CLUSTER_SCORE_THRESHOLD, keep only the
    # top N individual alerts (by composite_score) on the same event slug.
    # The cluster already captures the coordinated flow; extra individual
    # alerts add noise and waste LLM evaluations.
    cluster_events: dict[str, float] = {}
    for a in alerts:
        if a["alert_type"] == "cluster" and a["composite_score"] >= CLUSTER_SCORE_THRESHOLD:
            evt = a.get("event_slug", "")
            if evt:
                cluster_events[evt] = max(cluster_events.get(evt, 0), a["composite_score"])

    if cluster_events:
        capped_alerts: list[dict] = []
        # Collect individual alerts per event, sort by score, keep top N
        event_individuals: dict[str, list[dict]] = defaultdict(list)
        for a in alerts:
            evt = a.get("event_slug", "")
            if a["alert_type"] != "cluster" and evt in cluster_events:
                event_individuals[evt].append(a)
            else:
                capped_alerts.append(a)

        n_capped = 0
        for evt, indiv in event_individuals.items():
            indiv.sort(key=lambda x: -x["composite_score"])
            capped_alerts.extend(indiv[:MAX_INDIVIDUAL_PER_CLUSTERED_EVENT])
            n_capped += max(0, len(indiv) - MAX_INDIVIDUAL_PER_CLUSTERED_EVENT)

        if n_capped:
            print(
                f"[seeder] Capped {n_capped} individual alert(s) on "
                f"{len(cluster_events)} event(s) with strong cluster alerts",
            )
        alerts = capped_alerts

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


def push_to_backend(signals: list[Signal], trades: list[dict]) -> int:
    """Build the payload and POST it to the backend ingest endpoint.

    Returns the number of alerts actually pushed (after LLM filtering)."""
    if not signals:
        print("[seeder] No signals to push.")
        return 0

    payload = build_alerts_payload(signals, trades)

    # -- LLM filter: evaluate each alert and discard uninteresting ones --------
    # Verdicts are cached locally in polybot.db (llm_evaluations table),
    # so previously-seen alerts are resolved from cache without an API call.
    from llm_filter import filter_alerts

    print(f"[seeder] Running LLM filter on {len(payload['alerts'])} alert(s)...")
    payload["alerts"] = filter_alerts(payload["alerts"])

    if not payload["alerts"]:
        print("[seeder] All alerts discarded by LLM filter. Nothing to push.")
        return 0

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
            f"updated: {result.get('updated_alerts', 0)}, "
            f"skipped: {result.get('skipped_alerts', 0)}"
        )
        return n_alerts
    except requests.RequestException as e:
        print(f"[seeder] ERROR pushing to backend: {e}", file=sys.stderr)
        return 0
