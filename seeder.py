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
from db import get_wallet_pnl_summary, get_flagged_wallet_stats, get_wallet_current_streak
from gamma_cache import get_market_tags, get_market_by_condition

import json

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


def _normalize_gamma_game_start(raw: str | None) -> str | None:
    """Gamma returns gameStartTime as 'YYYY-MM-DD HH:MM:SS+00' — convert to ISO-8601."""
    if not raw:
        return None
    s = raw.strip().replace(" ", "T")
    # Normalize '+00' → '+00:00' so datetime.fromisoformat on the backend accepts it
    if re.search(r"[+-]\d{2}$", s):
        s += ":00"
    return s


def _resolve_event_timing(condition_id: str | None) -> tuple[str | None, str | None]:
    """Return (game_start_time, event_end_estimate) for a market.

    - game_start_time: best-effort start time for time-boxed events (sports/esports).
      Gamma exposes the same value through three fields with varying coverage:
      `gameStartTime` (most common), top-level `eventStartTime`, and
      `events[0].startTime`. We try them in order.
    - event_end_estimate: game_start_time when known, else the resolution deadline
      from _resolve_end_date(). This is what /api/resolving-soon and /api/top3
      sort on, so a sports game starting in 3h ranks before a political market
      whose deadline is 12h away (but whose event may have already happened)."""
    end_date = _resolve_end_date(condition_id)
    if not condition_id:
        return None, end_date
    market = get_market_by_condition(condition_id)
    if not market:
        return None, end_date

    # Try the three known Gamma fields in priority order.
    raw_start = market.get("gameStartTime") or market.get("eventStartTime")
    if not raw_start:
        events = market.get("events") or []
        if events and isinstance(events, list):
            raw_start = events[0].get("startTime")
    game_start = _normalize_gamma_game_start(raw_start)

    # Heuristic miss-detection: if Gamma marks this as a series-level market
    # (e.g. League of Legends, NBA games) but no start time is present, it's
    # almost certainly a data gap rather than an intentional null. Log so we
    # can spot systematic misses without hard-failing the ingest.
    if not game_start:
        events = market.get("events") or []
        series_slug = events[0].get("seriesSlug") if events else None
        category = events[0].get("category") if events else None
        if series_slug or category:
            print(
                f"[WARN] Sports market without start time: condition={condition_id} "
                f"series={series_slug!r} category={category!r} title={market.get('question','')[:60]!r}",
                file=sys.stderr,
            )

    event_end = game_start or end_date
    return game_start, event_end


def _resolve_market_media(condition_id: str | None) -> tuple[str | None, str | None]:
    """Return (image_url, description) from Gamma cache for a market."""
    if not condition_id:
        return None, None
    market = get_market_by_condition(condition_id)
    if not market:
        return None, None
    return market.get("image"), market.get("description")


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
        m_image, m_desc = _resolve_market_media(cid)
        game_start, event_end = _resolve_event_timing(cid)
        alerts.append({
            "alert_type": "cluster",
            "composite_score": max_score,
            "tags": _resolve_tags(cid),
            "market_title": sample.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "market_image": m_image,
            "market_description": m_desc,
            "wallet": None,
            "total_usd": total_usd,
            "trade_count": len(cluster_trades),
            "cluster_headline": cluster_sig.headline,
            "end_date": _resolve_end_date(cid),
            "game_start_time": game_start,
            "event_end_estimate": event_end,
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
        m_image, m_desc = _resolve_market_media(cid)
        game_start, event_end = _resolve_event_timing(cid)

        alerts.append({
            "alert_type": "composite",
            "composite_score": total_severity,
            "tags": _resolve_tags(cid),
            "market_title": primary_trade.get("title"),
            "condition_id": cid,
            "event_slug": evt,
            "market_url": f"https://polymarket.com/event/{evt}" if evt else None,
            "market_image": m_image,
            "market_description": m_desc,
            "wallet": wallet,
            "total_usd": total_usd,
            "trade_count": len(all_entry_trades),
            "end_date": _resolve_end_date(cid),
            "game_start_time": game_start,
            "event_end_estimate": event_end,
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

        m_image, m_desc = _resolve_market_media(cid)
        game_start, event_end = _resolve_event_timing(cid)
        alerts.append({
            "alert_type": "composite",
            "composite_score": total_severity,
            "tags": _resolve_tags(cid),
            "market_title": trade.get("title"),
            "condition_id": cid,
            "event_slug": event_slug,
            "market_url": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
            "market_image": m_image,
            "market_description": m_desc,
            "wallet": wallet,
            "total_usd": float(trade.get("_usd_value", 0)),
            "trade_count": 1,
            "end_date": _resolve_end_date(cid),
            "game_start_time": game_start,
            "event_end_estimate": event_end,
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

    # --- Drop sell-only alerts on multi-outcome markets ---
    # On binary markets (Yes/No), sells can be converted to equivalent buys
    # (Sell Yes → Buy No). On multi-outcome markets there's no single clear
    # opposite outcome, so we drop alerts where every trade is a SELL.
    pre_filter = len(alerts)
    filtered_alerts = []
    for a in alerts:
        trades_list = a.get("trades", [])
        if trades_list and all(t.get("side", "").upper() == "SELL" for t in trades_list):
            cid = a.get("condition_id", "")
            market = get_market_by_condition(cid) if cid else None
            if market:
                try:
                    outcomes = json.loads(market.get("outcomes", "[]"))
                except (json.JSONDecodeError, TypeError):
                    outcomes = []
                if len(outcomes) > 2:
                    continue  # skip: sell-only on multi-outcome market
        filtered_alerts.append(a)
    if len(filtered_alerts) < pre_filter:
        print(
            f"[seeder] Dropped {pre_filter - len(filtered_alerts)} sell-only alert(s) "
            f"on multi-outcome markets (no actionable copy trade)"
        )
    alerts = filtered_alerts

    # --- Build wallet profiles ---
    wallet_profiles: list[dict] = []
    for wallet in wallets_seen:
        pnl = get_wallet_pnl_summary(wallet)
        flagged = get_flagged_wallet_stats(wallet)

        closed = pnl.get("closed_positions", 0)
        wins = pnl.get("wins", 0)
        win_rate = (wins / closed) if closed > 0 else None

        profile = {
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
        }
        profile["current_streak"] = get_wallet_current_streak(wallet)
        wallet_profiles.append(profile)

    return {
        "alerts": alerts,
        "wallet_profiles": wallet_profiles,
    }


def build_theses_payload(signals: list, trades: list[dict]) -> list[dict]:
    """Build thesis payloads from correlated_cross_market signals."""
    from db import get_wallet_event_history
    from gamma_cache import get_market_by_condition

    cross_signals = [s for s in signals if s.strategy == "correlated_cross_market"]
    if not cross_signals:
        return []

    # Group by (wallet, event_slug)
    groups: dict[tuple[str, str], list] = {}
    for sig in cross_signals:
        wallet = sig.trade.get("proxyWallet", "").lower()
        event_slug = sig.trade.get("eventSlug", "")
        if wallet and event_slug:
            groups.setdefault((wallet, event_slug), []).append(sig)

    theses = []
    for (wallet, event_slug), sigs in groups.items():
        seen_cids = set()
        markets = []
        for sig in sigs:
            cid = sig.condition_id or sig.trade.get("conditionId", "")
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            market_info = get_market_by_condition(cid) or {}
            markets.append({
                "condition_id": cid,
                "market_title": market_info.get("title", sig.trade.get("title", "")),
                "outcome": sig.trade.get("outcome", ""),
                "side": sig.trade.get("side", ""),
                "usd_value": float(sig.trade.get("_usd_value", 0)),
                "entry_price": float(sig.trade.get("price", 0)),
            })

        # Also pull historical positions from wallet_event_history
        history = get_wallet_event_history(wallet, event_slug)
        for h in history:
            if h["condition_id"] not in seen_cids:
                seen_cids.add(h["condition_id"])
                # Use stored title/price, fall back to Gamma API
                title = h.get("market_title") or ""
                price = h.get("price") or 0
                if not title:
                    hmarket = get_market_by_condition(h["condition_id"]) or {}
                    title = hmarket.get("title", "")
                markets.append({
                    "condition_id": h["condition_id"],
                    "market_title": title,
                    "outcome": h["outcome"],
                    "side": h["side"],
                    "usd_value": float(h["usd_value"]),
                    "entry_price": float(price),
                })

        total_usd = sum(m["usd_value"] for m in markets)
        composite_score = max((s.severity for s in sigs), default=0)

        theses.append({
            "wallet": wallet,
            "event_slug": event_slug,
            "thesis_headline": None,  # Will be filled by LLM
            "markets": markets,
            "total_usd": total_usd,
            "composite_score": composite_score,
        })

    return theses


def _generate_thesis_headline(thesis: dict) -> str | None:
    """Generate a short thesis headline from market titles and bet directions."""
    market_descriptions = []
    for m in thesis["markets"]:
        direction = f"{m['side']} {m['outcome']}" if m.get("side") and m.get("outcome") else ""
        market_descriptions.append(f"{m.get('market_title', '')} ({direction})")

    prompt = (
        f"A trader is betting across these related markets:\n"
        + "\n".join(f"- {d}" for d in market_descriptions)
        + f"\nTotal position: ${thesis['total_usd']:,.0f}"
        + "\n\nWrite a 3-6 word thesis headline capturing what this trader believes. "
        + "Examples: 'Iran talks will collapse', 'Lakers sweep the series', 'Fed holds rates steady'. "
        + "Return ONLY the headline, no quotes."
    )

    try:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if not api_key:
            return None
        from openai import OpenAI
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        model = os.environ.get("AZURE_OPENAI_MODEL", "")
        client = OpenAI(base_url=endpoint, api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip().strip('"')
    except Exception:
        return None


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

    # Gather price candles for alerted markets
    from db import get_recent_price_candles
    alerted_cids = list({a["condition_id"] for a in payload["alerts"] if a.get("condition_id")})
    raw_candles = get_recent_price_candles(alerted_cids, since_hours=24)
    payload["price_candles"] = [
        {"condition_id": c["condition_id"], "token_id": c["token_id"],
         "outcome": c["outcome"], "t": c["t"], "p": c["p"]}
        for c in raw_candles
    ]

    # Build and add theses
    theses = build_theses_payload(signals, trades)
    for thesis in theses:
        if not thesis["thesis_headline"]:
            thesis["thesis_headline"] = _generate_thesis_headline(thesis)
    payload["theses"] = theses

    n_alerts = len(payload["alerts"])
    n_profiles = len(payload["wallet_profiles"])
    ingest_url = f"{BACKEND_URL}/api/ingest"
    print(f"[seeder] Pushing {n_alerts} alert(s) and {n_profiles} wallet profile(s) to {ingest_url}...")

    try:
        resp = requests.post(
            ingest_url,
            json=payload,
            timeout=120,
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
