"""
4-stage Twitter bot: event picker → deterministic data fetch → chart picker → writer.

Run via cron:
    python storybot/twitter_pipeline.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone


def _parse_iso(value) -> datetime | None:
    """Parse a Postgres-shaped timestamp into an aware datetime, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _extract_sharp_wallet(chosen_alerts: list[dict]) -> dict | None:
    """Try llm_copy_action first; fall back to wallet_pnl SQLite lookup if a
    win_rate_tracking signal exists but no record string is in the payload."""
    for a in chosen_alerts:
        copy = a.get("llm_copy_action") or {}
        if isinstance(copy, str):
            try:
                copy = json.loads(copy)
            except json.JSONDecodeError:
                copy = {}
        record = copy.get("wallet_record") or copy.get("record")
        win_pct = copy.get("win_pct") or copy.get("win_rate")
        if record and a.get("wallet"):
            return {
                "wallet": a["wallet"],
                "record": str(record),
                "win_pct": float(win_pct) if win_pct is not None else None,
            }

    # Fallback: any alert has a win_rate_tracking signal? Ask wallet_pnl.
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any((s.get("strategy") == "win_rate_tracking") for s in signals):
            continue
        wallet = a.get("wallet")
        if not wallet:
            continue
        try:
            from bot_utils import query_sqlite
            rows = query_sqlite(
                "SELECT wins, losses, win_rate FROM wallet_pnl "
                "WHERE wallet = ? LIMIT 1",
                (wallet,),
            )
        except Exception:
            rows = []
        if rows:
            r = rows[0]
            wins, losses = r.get("wins"), r.get("losses")
            wr = r.get("win_rate")
            if wins is not None and losses is not None:
                return {
                    "wallet": wallet,
                    "record": f"{wins}-{losses}",
                    "win_pct": float(wr) if wr is not None else None,
                }
    return None


def _cluster_size(chosen_alerts: list[dict]) -> int | None:
    """Largest cluster_size implied by wallet_clustering or concentrated_one_sided signals."""
    sizes = []
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") in ("wallet_clustering", "concentrated_one_sided"):
                # severity is roughly the cluster size for these strategies.
                sev = s.get("severity")
                if isinstance(sev, (int, float)) and sev > 0:
                    sizes.append(int(sev))
    return max(sizes) if sizes else None


def _has_volume_spike(chosen_alerts: list[dict]) -> bool:
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") == "pre_event_volume_spike":
                return True
    return False


def _minutes_to_resolution(chosen_alerts: list[dict]) -> int | None:
    """Smallest positive (resolution_time - now) in minutes, across chosen alerts."""
    now = datetime.now(timezone.utc)
    best = None
    for a in chosen_alerts:
        when = _parse_iso(a.get("game_start_time")) or _parse_iso(a.get("event_end_estimate"))
        if when is None:
            continue
        delta_min = int((when - now).total_seconds() // 60)
        if delta_min < 0:
            continue
        if best is None or delta_min < best:
            best = delta_min
    return best


def _dominant_outcome(trades: list[dict]) -> str | None:
    """Outcome with the largest USD share of the trades."""
    if not trades:
        return None
    totals: Counter = Counter()
    for t in trades:
        oc = t.get("outcome")
        if oc:
            totals[oc] += float(t.get("usdcSize") or 0.0)
    if not totals:
        return None
    return totals.most_common(1)[0][0]


def _biggest_price_move(trades: list[dict]) -> dict | None:
    """First→last price on the dominant outcome. None if <2 trades on that outcome."""
    outcome = _dominant_outcome(trades)
    if outcome is None:
        return None
    sub = [t for t in trades if t.get("outcome") == outcome and t.get("price") is not None]
    sub.sort(key=lambda t: float(t.get("timestamp") or 0.0))
    if len(sub) < 2:
        return None
    return {"from": float(sub[0]["price"]), "to": float(sub[-1]["price"])}


def _peak_hour_volume_usd(trades: list[dict]) -> float | None:
    """Max USD across rolling 60-minute windows. None if 0 trades."""
    if not trades:
        return None
    sorted_t = sorted(trades, key=lambda t: float(t.get("timestamp") or 0.0))
    # Window sum is correct under the precondition that usdcSize >= 0,
    # which holds for Polymarket trades. Clamping below makes the
    # algorithm robust if the precondition is ever broken upstream.
    best = 0.0
    left = 0
    running = 0.0
    for right in range(len(sorted_t)):
        running += max(0.0, float(sorted_t[right].get("usdcSize") or 0.0))
        while (float(sorted_t[right].get("timestamp") or 0.0)
               - float(sorted_t[left].get("timestamp") or 0.0)) > 3600:
            running -= max(0.0, float(sorted_t[left].get("usdcSize") or 0.0))
            left += 1
        if running > best:
            best = running
    return best if best > 0 else None


def _time_span_minutes(trades: list[dict]) -> int:
    if not trades:
        return 0
    times = [float(t.get("timestamp") or 0.0) for t in trades if t.get("timestamp")]
    if not times:
        return 0
    return int((max(times) - min(times)) // 60)


def _distinct_wallets(trades: list[dict]) -> int:
    return len({t.get("wallet") for t in trades if t.get("wallet")})


def build_facts_bundle(chosen_alerts: list[dict], trades: list[dict]) -> dict:
    """Derive a small dict of facts for downstream LLM stages to quote precisely.

    All fields gracefully degrade to null/0 when underlying data is missing.
    """
    total_usd = sum(float(t.get("usdcSize") or 0.0) for t in trades)
    return {
        "distinct_wallets": _distinct_wallets(trades),
        "total_usd": total_usd,
        "trade_count": len(trades),
        "time_span_minutes": _time_span_minutes(trades),
        "biggest_price_move": _biggest_price_move(trades),
        "peak_hour_volume_usd": _peak_hour_volume_usd(trades),
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts),
        "cluster_size": _cluster_size(chosen_alerts),
        "has_volume_spike": _has_volume_spike(chosen_alerts),
        "minutes_to_resolution": _minutes_to_resolution(chosen_alerts),
    }


SYSTEM_PROMPT_EVENT_PICKER = """You pick the single best event-cluster from \
the last ~3 hours of Polymarket alerts to tweet about, or skip if nothing \
stands out. You DO NOT write the tweet — that's a later stage.

You see up to 20 compact alerts, sorted by composite_score, each with its
top signals (strategy + severity + headline), market, wallet, $ size, event,
tags, and timing.

## Your job
1. Find the strongest *story*. A story = one event with one or more alerts
   that share a thesis. Multiple alerts on the same event_slug or
   condition_id usually belong together. A single alert is also fine if
   the signal is strong enough on its own.
2. Decide skip vs post:
   - skip if all alerts are small, generic, or lack a clear narrative
   - post if there's a real surprise: a sharp wallet, coordinated flow,
     a price/volume move, late-game timing, etc.
3. If posting, return the alert_ids that belong to that one event-cluster
   and a one-paragraph event_summary that frames what's surprising.

## Output (strict JSON only)
{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "alert_ids": [<int>, ...] | null,
  "event_summary": "<paragraph>" | null
}

When decision=post:
- alert_ids must be 1+ real IDs from the list shown to you, all sharing one event.
- event_summary must be a short paragraph (2-4 sentences) describing the event,
  the cluster, and the single most surprising fact. Plain English. No tweet
  voice yet. Downstream stages use this as framing.

When decision=skip, alert_ids and event_summary should be null.
"""


def pick_event(llm_client, seed_alerts: list[dict], *, usage: dict | None = None) -> dict:
    """Stage 1: pick an event-cluster to tweet about, or skip."""
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_EVENT_PICKER},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=8000,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "reason": f"invalid JSON: {exc}",
                "alert_ids": None, "event_summary": None}


def validate_event_pick(pick: dict, seed_alerts: list[dict]) -> tuple[bool, str]:
    """Sanity-check stage 1 output. Returns (ok, error_message)."""
    d = pick.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"
    ids = pick.get("alert_ids") or []
    if not isinstance(ids, list) or not ids:
        return False, "alert_ids must be a non-empty list when posting"
    try:
        wanted = {int(i) for i in ids}
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {ids!r}"
    seed_ids = {int(a.get("id") or 0) for a in seed_alerts}
    missing = wanted - seed_ids
    if missing:
        return False, f"alert_ids not in seed: {sorted(missing)}"
    summary = pick.get("event_summary")
    if not isinstance(summary, str) or not summary.strip():
        return False, "event_summary must be a non-empty string when posting"
    return True, ""


def _select_chosen_alerts(alert_ids: list[int], seed_alerts: list[dict]) -> list[dict]:
    """Filter seed_alerts down to those whose id is in alert_ids.

    Preserves alert_ids order so chosen_alerts[i] corresponds to alert_ids[i]
    (matching the trades-loop ordering in fetch_data_bundle).
    """
    by_id = {int(a.get("id") or 0): a for a in seed_alerts}
    return [by_id[int(i)] for i in alert_ids if int(i) in by_id]


def fetch_data_bundle(alert_ids: list[int], seed_alerts: list[dict]) -> dict:
    """Stage 2: fetch trades + Gamma tokens for chosen alerts, build facts_bundle.

    Returns: {chosen_alerts, trades, token_map, facts_bundle}.
    Failures are absorbed — missing trades become [], missing tokens become {}.
    """
    from tweet_utils import fetch_alert_trades, fetch_market_tokens
    from bot_utils import log

    chosen = _select_chosen_alerts(alert_ids, seed_alerts)

    trades: list[dict] = []
    for aid in alert_ids:
        try:
            trades.extend(fetch_alert_trades(int(aid)))
        except Exception as exc:
            log("alert_trades_fetch_error",
                alert_id=aid, error=f"{type(exc).__name__}: {exc}")

    # token_map is flat {outcome_name -> token_id}. Multi-market clusters
    # would collide on shared outcome names (e.g. two markets each with a
    # "Yes") — the current pipeline assumes one cid per event-cluster.
    token_map: dict[str, str] = {}
    seen_cids: set[str] = set()
    for a in chosen:
        cid = a.get("condition_id")
        if not cid or cid in seen_cids:
            continue
        seen_cids.add(cid)
        token_map.update(fetch_market_tokens(cid))

    return {
        "chosen_alerts": chosen,
        "trades": trades,
        "token_map": token_map,
        "facts_bundle": build_facts_bundle(chosen, trades),
    }


if __name__ == "__main__":
    import sys
    print("twitter_pipeline.py: main() not implemented yet", file=sys.stderr)
    sys.exit(1)
