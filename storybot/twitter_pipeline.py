"""
4-stage Twitter bot: event picker → deterministic data fetch → chart picker → writer.

Run via cron:
    python storybot/twitter_pipeline.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

# Make the project root importable so `import db` works when this script
# is run directly (cron / manual run from storybot/), not just under pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import chart_grid
import charts
from openai import OpenAI

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")
_LIVE_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_runs")
_RUN_OUTPUT_DIR = _DRY_RUN_DIR if DRY_RUN else _LIVE_RUN_DIR


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


# Min resolved P&L positions for a wallet's record to be a "story".
# Mirrors detection_strategies.win_rate_tracking.MIN_RESOLVED_BETS and
# storybot.charts.WALLET_RECORD_MIN_BETS so the bundle, the chart picker,
# and the chart fetcher all agree on what counts.
_SHARP_WALLET_MIN_BETS = 10

# Strategies whose presence on a chosen alert means the wallet's record is
# the load-bearing fact — and therefore worth a wallet_pnl lookup so the
# chart picker can pick wallet_record_card.
_SHARP_WALLET_STRATEGIES = ("win_rate_tracking", "correlated_cross_market")


def _distinct_trade_wallets(trades: list[dict]) -> list[str]:
    """Distinct wallets across the trades, in first-seen order. Handles both
    'proxyWallet' (Polymarket Data API) and 'wallet' (internal/test) keys."""
    if not isinstance(trades, list):
        return []
    seen: dict[str, None] = {}
    for t in trades:
        if not isinstance(t, dict):
            continue
        w = t.get("proxyWallet") or t.get("wallet")
        if w and w not in seen:
            seen[w] = None
    return list(seen)


def _best_sharp_wallet_via_pnl(wallets: list[str]) -> tuple[str, int, int] | None:
    """Pick the wallet with the highest win_rate among those clearing
    _SHARP_WALLET_MIN_BETS resolved P&L positions. Returns (wallet, wins, losses)
    or None. Failures (missing db, bad row) degrade silently to None."""
    import db
    best: tuple[str, int, int] | None = None
    best_rate = -1.0
    for w in wallets:
        try:
            summary = db.get_wallet_pnl_summary(w)
        except Exception:
            continue
        closed = int(summary.get("closed_positions") or 0)
        if closed < _SHARP_WALLET_MIN_BETS:
            continue
        wins = int(summary.get("wins") or 0)
        losses = int(summary.get("losses") or 0)
        rate = wins / closed if closed > 0 else 0.0
        if rate > best_rate:
            best = (w, wins, losses)
            best_rate = rate
    return best


def _wallet_bet_usd(wallet: str, trades: list[dict]) -> float:
    """Sum usdcSize across `trades` placed by `wallet`. Handles both
    'proxyWallet' (Polymarket Data API) and 'wallet' (internal/test) keys."""
    if not wallet:
        return 0.0
    total = 0.0
    for t in trades:
        if not isinstance(t, dict):
            continue
        w = t.get("proxyWallet") or t.get("wallet")
        if w == wallet:
            total += float(t.get("usdcSize") or 0.0)
    return total


def _extract_sharp_wallet(chosen_alerts: list[dict],
                          trades: list[dict]) -> dict | None:
    """Look up the wallet's record via wallet_pnl summary when the cluster
    carries a win_rate_tracking or correlated_cross_market signal. For cluster
    alerts (no top-level wallet), scan the cluster's trades and pick the
    highest-win-rate wallet meeting the min resolved-positions threshold —
    matching the chart fetcher's cluster path in
    storybot.charts.fetch_wallet_record_card_data.

    Returned dict includes `bet_usd` — the sharp wallet's own contribution
    summed across `trades` — so the writer can name it separately from the
    cluster total when they materially differ.
    """
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any(s.get("strategy") in _SHARP_WALLET_STRATEGIES for s in signals):
            continue
        candidates = [a["wallet"]] if a.get("wallet") else _distinct_trade_wallets(trades)
        if not candidates:
            continue
        best = _best_sharp_wallet_via_pnl(candidates)
        if best is None:
            continue
        wallet, wins, losses = best
        closed = wins + losses
        return {
            "wallet": wallet,
            "record": f"{wins}-{losses}",
            "win_pct": (wins / closed) if closed > 0 else None,
            "alert_id": int(a.get("id") or 0),
            "bet_usd": _wallet_bet_usd(wallet, trades),
        }
    return None


def _extract_fresh_wallet(chosen_alerts: list[dict],
                          trades: list[dict]) -> dict | None:
    """Surface a fresh-account bet if the cluster contains a new_wallet_large_bet
    signal. Returns {wallet, alert_id, wallet_age_days} for the first match,
    else None. wallet_age_days is None when the lookup failed (e.g. Gamma
    profile missing).

    Single-wallet alerts: look up the wallet's age via
    charts._fetch_wallet_created_at; the chart_grid FRESH WALLET tile reads
    wallet_age_days from facts_bundle["has_fresh_wallet"].

    Cluster alerts (no top-level wallet): scan the cluster's trades and pick
    the youngest wallet within FRESH_WALLET_MAX_DAYS — matching the chart
    fetcher's cluster path in storybot.charts.fetch_fresh_wallet_card_data.
    """
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any(s.get("strategy") == "new_wallet_large_bet" for s in signals):
            continue
        if a.get("wallet"):
            created_at = charts._fetch_wallet_created_at(a["wallet"])
            age_days = None
            if created_at is not None:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created_at).days
            return {"wallet": a["wallet"], "alert_id": int(a.get("id") or 0),
                    "wallet_age_days": age_days}
        candidates = _distinct_trade_wallets(trades)
        if not candidates:
            continue
        best = charts.youngest_fresh_wallet(candidates)
        if best is None:
            continue
        wallet, age_days = best
        return {"wallet": wallet, "alert_id": int(a.get("id") or 0),
                "wallet_age_days": age_days}
    return None


# Severity for wallet_clustering / concentrated_one_sided is log-scaled and
# saturates at 8.0, so it can't stand in for the actual cluster size — a sev=8
# wallet_clustering signal could cover anywhere from 8 to 30+ wallets. The real
# count lives in the headline:
#   wallet_clustering (in-window):  "{N} wallets share funder ..."
#   wallet_clustering (known sybil): "Known linked funder ...: {K} wallet(s) active, {N} total known, ..."
#   concentrated_one_sided:          "{N} wallets, same direction ..."
_CLUSTER_SIZE_TOTAL_KNOWN_RE = re.compile(r"(\d+)\s+total known")
_CLUSTER_SIZE_LEADING_WALLETS_RE = re.compile(r"^\s*(\d+)\s+wallets?\b")


def _parse_cluster_size_from_headline(headline: str) -> int | None:
    if not isinstance(headline, str):
        return None
    m = _CLUSTER_SIZE_TOTAL_KNOWN_RE.search(headline)
    if m is None:
        m = _CLUSTER_SIZE_LEADING_WALLETS_RE.match(headline)
    if m is None:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _cluster_size(chosen_alerts: list[dict]) -> int | None:
    """Largest cluster_size implied by wallet_clustering or concentrated_one_sided signals."""
    sizes = []
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") not in ("wallet_clustering", "concentrated_one_sided"):
                continue
            n = _parse_cluster_size_from_headline(s.get("headline") or "")
            if n is not None:
                sizes.append(n)
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
    Note: volume_multiplier_x is enriched in build_enriched_facts_bundle (it
    requires a gamma + sqlite fetch); build_facts_bundle alone leaves it None.
    """
    total_usd = sum(float(t.get("usdcSize") or 0.0) for t in trades)
    return {
        "distinct_wallets": _distinct_wallets(trades),
        "total_usd": total_usd,
        "trade_count": len(trades),
        "time_span_minutes": _time_span_minutes(trades),
        "biggest_price_move": _biggest_price_move(trades),
        "peak_hour_volume_usd": _peak_hour_volume_usd(trades),
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts, trades),
        "has_fresh_wallet": _extract_fresh_wallet(chosen_alerts, trades),
        "cluster_size": _cluster_size(chosen_alerts),
        "has_volume_spike": _has_volume_spike(chosen_alerts),
        "minutes_to_resolution": _minutes_to_resolution(chosen_alerts),
        "volume_multiplier_x": None,
    }


SYSTEM_PROMPT_EVENT_PICKER = """You pick the single best event-cluster from \
the last ~3 hours of Polymarket alerts to tweet about, or skip if nothing \
stands out. You DO NOT write the tweet — that's a later stage.

You see up to 20 compact alerts, sorted by composite_score, each with its
top signals (strategy + severity + headline), market, wallet, $ size, event,
tags, timing, and the alert's intended `side` (the outcome the informed
flow is on — e.g. "Yes", "No", "Over", "Under", a team name).

## Your job
1. Find the strongest *story with directional alpha*. A story = one event
   where informed flow is pushing in ONE direction that a reader could
   actually act on. Multiple alerts on the same event_slug or condition_id
   usually belong together. A single alert is also fine if the signal is
   strong enough on its own.
2. Decide skip vs post:
   - post if there's a real surprise the reader can act on: a sharp wallet
     taking a clear side, coordinated flow on one side, a price/volume move
     in one direction, late-game timing on a specific outcome, etc.
   - skip if all alerts are small, generic, lack a clear narrative, OR lack
     a clear directional thesis (see below).

## Directional alpha is required (HARD RULE)
A tweet without a side is not alpha. The reader needs to know which way
informed money is leaning so they can decide whether to follow.

When candidate alerts are on the SAME market (same condition_id) but
disagree on side — e.g. one cluster bought Over and a separate sharp
wallet bought Under on the same total — that is NOT a story. Sports
totals and binary markets routinely attract action on both sides; framing
it as "sharps colliding" reads as analysis, not edge, and gives the
reader nothing to do. In that situation:
  (a) prune the cluster to ONLY the alerts on the dominant side (by
      $ size or by sharpness) and post that as a directional story —
      provided the remaining side still stands on its own as a surprise; OR
  (b) skip the event entirely and look for another cluster.
Never post a cluster whose `alert_ids` mix opposing sides on the same market.

Multi-market clusters (same event, different condition_ids — e.g. moneyline
+ spread + total) can carry alerts on different outcomes because each
condition_id is a separate bet. That's allowed as long as the alerts
collectively express ONE coherent thesis on the event (e.g. "team X wins
big"), not contradictory views.

3. If posting, return the alert_ids that belong to that one directional
   cluster and a one-paragraph event_summary that frames what's surprising
   AND names the side the informed flow is on.

## Output (strict JSON only)
{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "alert_ids": [<int>, ...] | null,
  "event_summary": "<paragraph>" | null
}

When decision=post:
- alert_ids must be 1+ real IDs from the list shown to you, all sharing one
  event AND (when on the same condition_id) all on the same side.
- event_summary must be a short paragraph (2-4 sentences) describing the
  event, the cluster, the side the informed flow is on, and the single
  most surprising fact. Plain English. No tweet voice yet. Downstream
  stages use this as framing.

When decision=skip, alert_ids and event_summary should be null.
Valid skip reasons include: no clear directional thesis, opposing flow
on the same market, all alerts too small/generic, event already covered
by a recent tweet (see below).

## No back-to-back repeats (HARD RULE)
The user payload includes `recent_tweets` — the last ~10 tweets we shipped,
each with the tweet text, the condition_ids it covered, and tweeted_at.
Do NOT pick a cluster whose alerts re-cover an event we just tweeted:

- Same condition_id as any recent tweet → SKIP (or prune the cluster to
  alerts on a different condition_id, if the remaining alerts still stand
  on their own).
- Same event_slug as a recent tweet, even on a different condition_id, when
  the recent tweet already framed the same broader thesis (e.g. we already
  tweeted "Team X to win" on the moneyline and you're picking the spread
  on the same game with the same directional thesis) → SKIP. A genuinely
  new angle on the same event (e.g. moneyline tweeted, now a sharp wallet
  hits the player-prop with a different thesis) is fine — say so in
  `reason`.
- A wallet you just spotlighted (record-led story) hitting a different
  market with a tiny stake is NOT a fresh story → SKIP.

When in doubt about whether two events are "the same story", lean SKIP —
the cost of a duplicate is high, the cost of a missed alert is low.
"""


def pick_event(llm_client, seed_alerts: list[dict],
               *, recent_tweets: list[dict] | None = None,
               usage: dict | None = None) -> dict:
    """Stage 1: pick an event-cluster to tweet about, or skip.

    `recent_tweets` is the output of `fetch_recent_tweets` — the last ~10
    posted tweets with their tweet text and covered condition_ids. The
    picker uses it to avoid re-covering an event we just tweeted.
    """
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    payload = {
        "alerts": compact,
        "recent_tweets": recent_tweets or [],
    }
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score, plus the last "
        f"{len(recent_tweets or [])} tweets we shipped (do not re-cover "
        f"the same event):\n\n"
        f"{json.dumps(payload, default=str, indent=2)}"
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


SYSTEM_PROMPT_CHART_PICKER = """You pick a chart that proves the surprise the \
upcoming tweet will lead with. You also write the hook_anchor — one short \
phrase naming the surprising fact the chart visualizes.

You see:
- event_summary: a paragraph framing the story
- facts_bundle: precise numbers about the chosen event
- chosen_alerts: the compact alert rows that make up the cluster

## Available chart types
- "wallet_record_card" — one wallet's win record + their bet on this market.
  Pick this iff facts_bundle.has_sharp_wallet is non-null AND
  facts_bundle.has_sharp_wallet.bet_usd >= 5000. Below that $ floor the
  sharp wallet's fresh stake is too small to anchor the chart on its own;
  pick whichever OTHER chart type has the strongest supporting fact
  (price_sparkline if biggest_price_move is meaningful, volume_bar if
  has_volume_spike, cluster_card if cluster_size >= 3 with a shared funder,
  fresh_wallet_card if has_fresh_wallet, else "none"). The wallet's record
  can still ride along in the tweet text — but the chart shouldn't lead
  with a record that came from a $1-2k bet.
- "fresh_wallet_card" — one wallet's age + their bet on this market.
  Pick this iff facts_bundle.has_fresh_wallet is non-null AND
  wallet_record_card is not eligible (either has_sharp_wallet is null,
  or bet_usd is below the $5k floor described above).
- "price_sparkline" — price over time on the dominant outcome.
  Pick this iff facts_bundle.biggest_price_move is non-null AND the move is
  meaningful. Polymarket prices are 0.0-1.0 probabilities; "3 cents" means a
  delta of 0.03. Threshold: |to - from| >= 0.03 OR
  |to - from| / max(from, to, 0.01) >= 0.10.
- "volume_bar" — volume bars showing a spike.
  Pick this iff facts_bundle.volume_multiplier_x is non-null AND >= 5.0.
  has_volume_spike alone isn't enough — the chart's underlying renderer
  needs the gamma-vs-baseline ratio to clear 5×, and volume_multiplier_x
  carries that exact ratio. Below 5×, pick whichever OTHER chart type
  has the strongest supporting fact (or "none").
- "cluster_card" — multi-wallet cluster card with a SHARED FUNDER.
  Pick this iff facts_bundle.cluster_size >= 3 AND no sharp_wallet record
  dominates (otherwise prefer wallet_record_card and mention the cluster
  in the tweet text) AND at least one chosen alert's cluster_headline ends
  with "share funder (linked)". Without that marker the wallets don't
  share a funder in our index and the card will fail to render — pick
  volume_bar or price_sparkline instead (or none).
- "none" — if nothing supports a chart cleanly.

## Hook anchor
A 2-5 word phrase the writer will lead with. Examples:
- "29-4 sharp record"
- "6-day-old account"
- "32c → 41c flip"
- "12× normal volume"
- "five accounts, one funder"

If chart_type is "none", hook_anchor is still required and should name the
surprising thing in the story (the writer leads with it regardless).

## Output (strict JSON only)
{
  "chart_type": "wallet_record_card" | "fresh_wallet_card" | "price_sparkline" | "volume_bar" | "cluster_card" | "none",
  "hook_anchor": "<phrase>"
}
"""


def pick_chart(llm_client, chosen_alerts: list[dict], event_summary: str,
               bundle: dict, *, usage: dict | None = None) -> dict:
    """Stage 3: pick a chart_type and hook_anchor."""
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
    }
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_CHART_PICKER},
            {"role": "user", "content": json.dumps(payload, default=str, indent=2)},
        ],
        temperature=1,
        max_completion_tokens=4000,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"chart_type": "none", "hook_anchor": "",
                "_parse_error": f"invalid JSON: {exc}"}


_VALID_CHART_TYPES = frozenset(charts.CHART_TYPES)


def validate_chart_pick(pick: dict) -> tuple[bool, str]:
    if pick.get("_parse_error"):
        return False, pick["_parse_error"]
    ct = pick.get("chart_type")
    if ct not in _VALID_CHART_TYPES:
        return False, f"unknown chart_type: {ct!r}"
    anchor = pick.get("hook_anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        return False, "hook_anchor must be a non-empty string"
    if len(anchor) > 80:
        return False, f"hook_anchor too long ({len(anchor)} > 80 chars)"
    return True, ""


SYSTEM_PROMPT_WRITER = f"""You are the social media voice for PolySpotter — a \
service that surfaces notable bets on Polymarket (whales, sharp wallets, \
coordinated flow, informed edge). You compose ONE tweet for one event that \
earlier stages have already decided is worth tweeting about.

You see:
- event_summary: a paragraph framing the story
- facts_bundle: precise numbers (price moves, volume, sharp wallet record, etc.)
- chosen_alerts: the compact alert rows
- chart_type: which chart will ship with the tweet
- hook_anchor: a short phrase describing what the chart visualizes. This is a
  CHART LABEL, not a tweet opener. Do NOT echo it verbatim. Treat it as a hint
  about which fact the chart will reinforce; you still write the tweet's lede
  in your own plain-English voice.
- lede_shape_hint (optional): if present, this is the lede SHAPE (timing,
  impact, size, age, cluster, behavior, stakes) the rerank stage wants you
  to lean into for THIS candidate. Variant generation calls the writer 2-3
  times with different hints to diversify openers. Treat it as a steering
  preference, not a hard rule — pick the hinted shape if the facts support
  it, fall back to the strongest shape otherwise.

Your job: write a tweet that fits in 280 characters (URLs count as 23 chars).

## Image grid
The chart shipped with this tweet is a grid: a hero panel (corresponding
to chart_type) plus up to 3 stat tiles drawn from {{CLOCK, CLUSTER $,
LINKED ACCOUNTS, VOLUME ×, PRICE MOVE, SHARP RECORD, FRESH WALLET, WALLETS}}. The
active tile list is in image_tiles. Don't waste tweet characters listing
tile facts unless they're load-bearing for the lede shape.

## Recent openers to avoid
The user payload includes `recent_openers_to_avoid` — the opening clauses of
the last few tweets we shipped. Do NOT mimic their structure. If your draft
opens with a near-clone of any listed opener (same first 3-4 words, same
template — "$Xk just hit…", "With N minutes to tip…", "A wallet that's…"),
rewrite the lede with a different shape from the priority list above. Variety
is itself an engagement lever; back-to-back tweets with the same template
train followers to scroll past.

## Audience
Sports/markets-curious reader who has never heard of PolySpotter and may not
know Polymarket. They will not parse insider shorthand. Every tweet must work
as a self-contained sentence.

- Anchor the venue once: "on Polymarket", "Polymarket account", "prediction-market bettors".
- Spell out what every bet is ON: "Under 7.5 runs" not "Under 7.5", "Yes on Fed
  cuts in May" not "Yes for $40k", "buying No at 12c" not "buying at 12c".
- When citing a win rate or record, say what it counts: "88% across 50+ Polymarket
  bets" / "178-20 on past markets", not "wins 88% of the time".
- Translate the strategy concept into plain behavior, not the label:
  - wallet_clustering / concentrated_one_sided →
    "three accounts sharing one funder", "a group of accounts moving in
    lockstep on the same side"
  - timing_relative_resolution → "buying with X minutes left",
    "an account that keeps showing up minutes before resolution"
  - new_wallet_large_bet → "a 12-day-old account dropping $80k"
  - win_rate_tracking → "an account hitting 88% of prior bets"
  - pre_event_volume_spike → "10x the usual flow into this market"
  - price_impact → "a single buy that pushed the line from 32c to 41c"

## Style
- Confident, punchy, human. Like a sharp friend explaining what they just spotted —
  NOT analyst-speak, NOT a press release, NOT scanner output.
- Lead with WHAT JUST HAPPENED or WHAT'S AT STAKE — never with who placed
  the bet. The first clause is the scroll-stopper; "who they are" comes
  second as supporting evidence. Read hook_anchor as a hint about which
  fact the chart proves, not as a tweet opener.
- HARD RULE — never open the tweet with a literal win-loss record.
  "A 174-32 account just…", "A 35-7 Polymarket account just…", "An
  account that's X-Y on past markets…" are all banned ledes; they
  read like scanner output and the reader bounces. The record is
  credibility evidence, not the hook — place it mid-sentence or in a
  follow-up clause: "…and the lead wallet is 174-32 on past calls",
  "…from a wallet that's 35-7 on tracked markets". If hook_anchor is
  itself a record number, paraphrase the behavior — don't echo the digits.
- Pick the lede shape from what's actually surprising. When more than one
  applies, use this priority (strongest scroll-stop first):
  1. timing-led — there's a hard clock: "With 4 minutes left, someone
     bought…", "Minutes before tip, five accounts piled in on…"
  2. impact-led — a single buy moved the market: "One buy just flipped
     this market from 32c to 41c…", "$13k just jolted the line 13% in
     minutes…"
  3. size-led — outsized stake on a quiet market: "$50k just landed on
     a market that's seen $4k all week…"
  4. age-led (new_wallet_large_bet): "A 12-day-old account just dropped
     $80k…"
  5. cluster-led — only when the cluster IS the surprise (many wallets,
     one funder, simultaneous): "Eighteen Polymarket accounts sharing
     one funder just bought…". Write as behavior, never as a tile
     caption ("18-wallet cluster" → banned).
  6. behavior-led for sharp wallets — describe the action and stake
     first, then qualify with the record: "Someone is quietly building
     a $113k thesis across Polymarket's US-Iran meeting markets — and
     the lead wallet is 174-32 on past calls". The digits come second.
  7. stakes-led — for long-resolution events with no hard clock
     (minutes_to_resolution > 360 or null). Frame the bet's payoff
     so the reader feels what's on the line: "If this resolves Yes, the
     No side eats $19k.", "$50k of Yes is one ruling away from
     evaporating." Stakes-led ledes outperform timing-led ledes for
     geopolitical / macro markets, where a "decision day" is days or
     weeks out and a soft clock reads as filler.
  When timing AND a sharp record both apply, timing wins. When a cluster
  AND a sharp record both apply, the cluster scale or funder link leads,
  with the record as a one-clause qualifier. For long-resolution events
  (minutes_to_resolution > 360 or null) prefer stakes-led over a soft
  clock.
- Pacing: 2-3 short sentences beats one long clause-stack. Aim for ≤20 words
  per sentence. Punchy rhythm > polished prose.
- Round numbers for readability: "$78k" not "$78,131.61"; "$2.8M" not "$2,789,285.20".
  Win-rate records stay exact ("178-20").
- Stat budget: max 3 distinct numerical STATS in the body (URLs don't
  count). A "stat" is one fact, not one number — a stat can contain
  multiple numbers and still count as one. Examples of one stat each:
  a price flip "34c → 29c" (one fact: the price move, two numbers),
  a record "178-20" or "50-1", a dollar figure "$8k", a multiplier
  "12× usual", a wallet count "three accounts", a wallet age "31-day-old",
  a clock "147 minutes", a percentage "88%". Before submitting, count
  the STATS, not the digits. If you're at 4+, drop the weakest stat
  first (usually the soft clock like "147 minutes"). Keep whichever
  stat anchors the chart (see Image-text linkage above).
- Refer to wallets by what makes them notable ("a 178-20 wallet", "a fresh account
  up $400k"), not by 0x address.
- Sharp wallet vs cluster total: when has_sharp_wallet is set AND its bet_usd
  is materially less than total_usd (rule of thumb: bet_usd <= 0.5 * total_usd),
  these are two different facts and you MUST name them separately. The sharp
  wallet's own stake is bet_usd; the surrounding cluster's total stake is
  total_usd minus bet_usd (or just the total, if you frame it as "the cluster
  put $X total"). Never imply the sharp wallet bet the full cluster sum.
  Pattern: "<behavior-led lede with the sharp wallet's bet>. <cluster
  sentence naming the rest>." Example: "$1k just landed on Rafael Jodar
  to upset Sinner — from a wallet that's 184-13 on Polymarket. Seven
  more accounts sharing the same funder piled another $22k on the same
  side." (The record qualifies the wallet; it doesn't open the tweet.)
- Cumulative cluster vs this run's trades: event_summary and chosen_alerts
  headlines may cite cluster-scale figures (wallet counts, dollar totals)
  that exceed facts_bundle.total_usd — those are cumulative across flagged
  trades, not a single push. Frame them with present perfect ("have built",
  "have put", "now sit at") and never with temporal compression ("just bought",
  "in the last hour", "minutes before X") unless facts_bundle.total_usd backs
  the claim. If a cited dollar figure is larger than facts_bundle.total_usd,
  treat it as cumulative and phrase it accordingly.
- The closing line earns its spot. Strong closers, in priority order:
  (a) time-to-resolution if facts_bundle.minutes_to_resolution is set and
      under ~360: "First pitch in 90 minutes.", "Tips off in 11.",
      "We'll know by close.";
  (b) a concrete stake or escalation: "$113k now riding on this thesis.",
      "Their related exposure on this event is $81k.";
  (c) a counter-fact that sharpens the conflict: "A $231k whale just took
      the other side."
  NEVER vague chest-thumps like "Not random.", "Something's cooking.",
  "Worth a look.". If none of (a)-(c) applies cleanly, end on the link.
- Cap "Polymarket" at ONE mention in the tweet body. Repeating it 2-3
  times wastes characters and reads like scanner output. Vary the venue
  reference: "the line", "this market", "prediction-market bettors",
  "the market". Drop the venue entirely if the link makes it obvious.
- Image-text linkage. The chart that ships with this tweet visualizes
  ONE specific fact (named by hook_anchor and implied by chart_type).
  The tweet body MUST reference that fact in plain English so the
  reader's eye routes to the chart instead of treating it as decoration:
  - chart_type=wallet_record_card → name the record digits ("a 110-3
    wallet", "the lead wallet is 732-127").
  - chart_type=fresh_wallet_card → name the wallet age ("a 31-day-old
    account") or a clear fresh-wallet descriptor ("brand-new account",
    "fresh wallet", "new account").
  - chart_type=price_sparkline → name the price move in cents
    ("79c → 62c", "32c flip") or a percent shift.
  - chart_type=volume_bar → name the multiplier ("12× usual",
    "ran 25x").
  - chart_type=cluster_card → name the wallet count ("three accounts",
    "8 wallets").
  When chart_type=none, no anchor is required.
- The closer (the LAST sentence before the link) MUST do work. Banned
  closer phrases (vague chest-thumps): "Not random.", "Something's
  cooking.", "Worth a look.", "Watch this space.", "Eyes on this.",
  "Stay tuned.", "Buckle up.", "We'll see.", "Let's see.", "Interesting
  times.", "This could be big.", "Watch closely.", "Keep an eye." Pick
  a concrete closer instead: a clock, a stake/escalation, a counter-fact,
  or a reply-bait question ("Cubs or fade?", "Over or under?"). A tweet
  with only ONE sentence in the body before the URL is rejected — the
  body needs at least two sentences so the closer has somewhere to live.
- 0-1 emoji, only if it earns its spot. No hashtags. No @mentions.
- BANNED jargon: "deployed capital", "real size", "meaningful size", "conviction
  flow", "high-conviction", "scan window", "composite score", "alerted flow",
  "positioning", "near-resolution flag", "priced in", "coordinated burst",
  "pile-in", "counterpunch", "looked cleaner", "linked wallet(s)", "wallet trio",
  "wallet duo", "wallet squad", "informed flow", "smart money flow".
- Banned tile-talk lede shapes: "<N>-wallet <SIDE> cluster", "<N>x volume spike",
  "<wallet> sharp record" used as a noun-phrase opener. Restate as behavior.
- Banned CTAs: "in bio", "full breakdown", "link below", "more at", "link in bio".

## Worked examples

### Sharp-wallet story (the most over-formulaic case)

BAD (record-led, scanner output, no urgency):
  "A Polymarket account that's 174-32 on past markets just put $1.7k
  on Yes on a US-Iran peace deal by June."
Why it's bad: opens with the literal record, no clock, no stakes, no
reason for a casual reader to stop scrolling.

GOOD (lead with the cumulative thesis, demote the record to a clause):
  "Someone is quietly building a $113k thesis across Polymarket's
  US-Iran meeting markets — and the lead wallet is 174-32 on past
  calls. Latest add: $2.9k on a meeting by late spring.
  https://polyspotter.com/alert/130328"

### Timing-led story (the ideal — leans into urgency)

GOOD:
  "With 11 minutes to tip, five Polymarket accounts bought $82k on
  the 76ers to beat the Celtics. Three share one funder. Volume ran
  99x usual.
  https://polyspotter.com/alert/131163"
Why it works: hard clock first three words; size, funder link, then
volume context. No record number anywhere.

### Cluster story (when the cluster IS the surprise)

BAD (tile-caption opener):
  "7-wallet NO cluster against Finland winning Eurovision 2026:
  bettors bought $20k of No. Volume hit 130x usual."
Why it's bad: "7-wallet NO cluster" is a chart caption, not a tweet.

GOOD (behavior, scale, time-frame as closer):
  "Eight Polymarket accounts just bought $23k of No on Finland
  winning Eurovision 2026, blowing out the market's usual volume
  by 82x — months before the final."

## Link (mandatory)
Include exactly one polyspotter.com deep link. Prefer the market page; use a
wallet link only when the story is about one specific wallet.
- market: https://polyspotter.com/market/<slug>
    <slug> = kebab-cased market_title (lowercase, non-alnum → single dash,
    trim leading/trailing dashes, max 80 chars) + "-" + first 7 chars of
    condition_id (i.e. "0x" + 5 hex chars).
- wallet: https://polyspotter.com/wallet/<wallet_address>
- alert:  https://polyspotter.com/alert/<alert_id>
- tag:    https://polyspotter.com/tag/<tag-slug>

## Output (strict JSON only)
{{
  "tweet": "<text with one polyspotter.com link>"
}}
"""


def validate_tweet(text: str) -> tuple[bool, str]:
    """Length / banned-phrase / banned-opener / link presence checks. No JSON parsing."""
    from tweet_utils import (
        TWEET_MAX_CHARS, TWEET_MAX_POLYMARKET_MENTIONS,
        _BANNED_TWEET_PHRASES, _POLYSPOTTER_URL_RE,
        _TWEET_RECORD_OPENER_RE, _count_polymarket_mentions_in_body,
        _tweet_length, check_tweet_closer,
    )
    if not isinstance(text, str) or not text.strip():
        return False, "tweet must be a non-empty string"
    tlen = _tweet_length(text)
    if tlen > TWEET_MAX_CHARS:
        return False, f"tweet length {tlen} exceeds {TWEET_MAX_CHARS}"
    lower = text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned CTA phrase {phrase!r}"
    if _TWEET_RECORD_OPENER_RE.match(text):
        return False, ("tweet must not open with a literal win-loss record "
                       "(e.g. 'A 174-32 account just…'); rewrite the lede "
                       "as behavior, timing, or impact and demote the record "
                       "to a later clause")
    poly_count = _count_polymarket_mentions_in_body(text)
    if poly_count > TWEET_MAX_POLYMARKET_MENTIONS:
        return False, (
            f"tweet mentions 'Polymarket' {poly_count} times — cap is "
            f"{TWEET_MAX_POLYMARKET_MENTIONS}; vary the venue reference "
            "('the line', 'this market', 'prediction market', or drop it)"
        )
    if not _POLYSPOTTER_URL_RE.search(text):
        return False, "tweet must contain a polyspotter.com deep link"
    ok_closer, closer_err = check_tweet_closer(text)
    if not ok_closer:
        return False, closer_err
    return True, ""


# Chart anchor patterns. Each chart_type the writer might pick has a
# corresponding "this is the fact the chart visualizes" signal we expect to
# find somewhere in the tweet body so the chart and text reinforce each
# other rather than competing for the reader's eye.
_FRESH_WALLET_AGE_RE = re.compile(
    r"\b(\d+)\s*[- ]\s*day[- ]?old\b", re.IGNORECASE
)
_FRESH_WALLET_DESCRIPTOR_RE = re.compile(
    r"\b(?:brand[- ]?new|fresh|new)\s+(?:account|wallet)\b", re.IGNORECASE
)
_PRICE_CENTS_RE = re.compile(r"\b\d{1,3}\s*c\b", re.IGNORECASE)
_PRICE_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_VOLUME_MULTIPLIER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*[x×]\b", re.IGNORECASE)
_CLUSTER_DIGIT_COUNT_RE = re.compile(
    r"\b\d+\s+(?:accounts?|wallets?)\b", re.IGNORECASE
)
_CLUSTER_WORD_COUNT_RE = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|"
    r"twenty|thirty)\s+(?:accounts?|wallets?)\b",
    re.IGNORECASE,
)


def validate_tweet_anchor(text: str, chart_pick: dict,
                          bundle: dict) -> tuple[bool, str]:
    """Image-text linkage check: the tweet body must reference the fact the
    chart visualizes, so the reader's eye routes to the chart instead of
    treating it as decoration.

    chart_type='none' (or missing) always passes. Bundle fields that are
    null also pass — there's nothing to anchor against.

    Returns (ok, error). Caller threads the error back into the writer
    retry on failure.
    """
    from tweet_utils import _POLYSPOTTER_URL_STRIP_RE
    if not isinstance(text, str):
        return False, "tweet must be a string"
    chart_type = (chart_pick or {}).get("chart_type")
    if not chart_type or chart_type == "none":
        return True, ""
    body = _POLYSPOTTER_URL_STRIP_RE.sub("", text or "")
    bundle = bundle or {}

    if chart_type == "wallet_record_card":
        record = ((bundle.get("has_sharp_wallet") or {}).get("record"))
        if not record:
            return True, ""
        if record not in body:
            return False, (
                f"chart shows wallet record {record!r} but the tweet "
                "body does not name it; mention the record digits "
                "(e.g. 'a 110-3 wallet') so the chart and text reinforce"
            )
        return True, ""

    if chart_type == "fresh_wallet_card":
        info = bundle.get("has_fresh_wallet") or {}
        age = info.get("wallet_age_days")
        if age is None:
            return True, ""
        if (_FRESH_WALLET_AGE_RE.search(body)
                or _FRESH_WALLET_DESCRIPTOR_RE.search(body)):
            return True, ""
        return False, (
            f"chart shows a {age}-day-old wallet but the tweet body "
            "does not reference its age; say "
            f"'{int(age)}-day-old account' or 'brand-new account' to "
            "anchor the chart"
        )

    if chart_type == "price_sparkline":
        move = bundle.get("biggest_price_move")
        if not move:
            return True, ""
        if _PRICE_CENTS_RE.search(body) or _PRICE_PERCENT_RE.search(body):
            return True, ""
        return False, (
            "chart is a price sparkline but the tweet body does not name "
            "the price move; add a cent callout (e.g. '79c → 62c') or a "
            "percent shift to anchor the chart"
        )

    if chart_type == "volume_bar":
        mult = bundle.get("volume_multiplier_x")
        if mult is None:
            return True, ""
        if _VOLUME_MULTIPLIER_RE.search(body):
            return True, ""
        return False, (
            "chart is a volume bar but the tweet body does not name the "
            "volume multiplier (e.g. '12× usual'); anchor the chart with "
            "a volume callout"
        )

    if chart_type == "cluster_card":
        cluster_size = bundle.get("cluster_size")
        if not cluster_size:
            return True, ""
        if (_CLUSTER_DIGIT_COUNT_RE.search(body)
                or _CLUSTER_WORD_COUNT_RE.search(body)):
            return True, ""
        return False, (
            "chart is a cluster card but the tweet body does not name "
            "the wallet count (e.g. 'three accounts'); anchor the chart "
            "with the cluster size"
        )

    return True, ""


def _writer_user_message(chosen_alerts: list[dict], event_summary: str,
                         bundle: dict, chart_pick: dict,
                         image_tiles: list[str] | None = None,
                         recent_openers: list[str] | None = None,
                         lede_shape_hint: str | None = None) -> str:
    from bot_utils import _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
        "chart_type": chart_pick.get("chart_type"),
        "hook_anchor": chart_pick.get("hook_anchor"),
        "image_tiles": image_tiles or [],
        "recent_openers_to_avoid": recent_openers or [],
        "lede_shape_hint": lede_shape_hint,
    }
    return json.dumps(payload, default=str, indent=2)


# Lede shapes the writer can lean into. Order matches the priority list in
# SYSTEM_PROMPT_WRITER (timing first, stakes last). _eligible_lede_shapes
# walks this list and keeps shapes whose facts the bundle supports.
_LEDE_SHAPES_PRIORITY = (
    "timing", "impact", "size", "age", "cluster", "behavior", "stakes",
)

# Bundle thresholds. Mirrors the chart_picker thresholds where they overlap
# (price move >= 0.03 absolute) so a chart that argues "price moved" lines
# up with a tweet that opens "price moved".
_LEDE_PRICE_DELTA_MIN = 0.03
_LEDE_SIZE_USD_MIN = 10000.0
_LEDE_TIMING_MAX_MINUTES = 360  # 6h — beyond this, soft clocks read as filler
_LEDE_CLUSTER_SIZE_MIN = 3


def _eligible_lede_shapes(bundle: dict) -> list[str]:
    """Return the lede shapes whose facts the bundle supports, in priority
    order. Used to drive multi-candidate generation: each eligible shape
    becomes one writer call with that shape as a hint."""
    bundle = bundle or {}
    out: list[str] = []
    mtr = bundle.get("minutes_to_resolution")
    move = bundle.get("biggest_price_move") or {}
    total = float(bundle.get("total_usd") or 0)
    fresh = bundle.get("has_fresh_wallet")
    cluster = int(bundle.get("cluster_size") or 0)
    sharp = bundle.get("has_sharp_wallet")

    if isinstance(mtr, (int, float)) and 0 < mtr < _LEDE_TIMING_MAX_MINUTES:
        out.append("timing")
    if move:
        try:
            delta = abs(float(move.get("to") or 0) - float(move.get("from") or 0))
        except (TypeError, ValueError):
            delta = 0.0
        if delta >= _LEDE_PRICE_DELTA_MIN:
            out.append("impact")
    if total >= _LEDE_SIZE_USD_MIN:
        out.append("size")
    if fresh:
        out.append("age")
    if cluster >= _LEDE_CLUSTER_SIZE_MIN:
        out.append("cluster")
    if sharp:
        out.append("behavior")
    if mtr is None or (isinstance(mtr, (int, float))
                       and mtr >= _LEDE_TIMING_MAX_MINUTES):
        out.append("stakes")
    return out


def _pick_candidate_shapes(bundle: dict, n: int = 3) -> list[str]:
    """Pick up to N lede shapes for candidate generation. Always returns at
    least one — falls back to 'stakes' if no other shape is eligible, since
    the stakes frame ("$X is on the line") works for any market."""
    shapes = _eligible_lede_shapes(bundle)[:max(1, int(n))]
    if not shapes:
        shapes = ["stakes"]
    return shapes


# Heuristic rerank signals. Cheap, deterministic — no LLM call.
_CLOCK_CLOSER_RE = re.compile(
    r"\b(?:in|by|with|tips?\s+off\s+in|first\s+pitch\s+in|"
    r"puck\s+drops?\s+in|kickoff\s+in)\s+\d+\s*"
    r"(?:min(?:ute)?s?|hours?|hr)\b",
    re.IGNORECASE,
)
_DOLLAR_CLOSER_RE = re.compile(r"\$\d")
_CONTRAST_CLAUSE_RE = re.compile(
    r"\b(?:but|while|yet|though|whereas)\b", re.IGNORECASE
)


def _score_candidate(text: str, bundle: dict, chart_pick: dict) -> float:
    """Heuristic score for picking among valid candidates. Higher = better.

    Signals (deterministic, cheap):
    - Concrete clock closer (e.g. "Tips off in 12 minutes."): +3
    - Dollar escalation in closer: +2
    - Contrast/counter clause in closer: +1
    - Reply-bait question anywhere in body: +1
    - Length in 200-260 char sweet spot (Twitter-counted): +2
    - Length > 270 (cramped, near the 280 cap): -1

    The score doesn't replace validation — it ranks among already-valid
    candidates. Order is the tiebreaker: when scores tie, the highest-
    priority shape wins (caller passes candidates in priority order).
    """
    from tweet_utils import _POLYSPOTTER_URL_STRIP_RE, _tweet_length
    body = _POLYSPOTTER_URL_STRIP_RE.sub("", text or "").strip()
    if not body:
        return 0.0

    # Closer-bearing signals.
    sentences = []
    parts = re.split(r"(?<=[.!?])\s+", body)
    for s in parts:
        s = s.strip().rstrip(".!?").strip()
        if s:
            sentences.append(s)
    last = sentences[-1] if sentences else ""

    score = 0.0
    if _CLOCK_CLOSER_RE.search(last):
        score += 3.0
    elif _DOLLAR_CLOSER_RE.search(last):
        score += 2.0
    elif _CONTRAST_CLAUSE_RE.search(last):
        score += 1.0

    if "?" in body:
        score += 1.0

    tlen = _tweet_length(text)
    if 200 <= tlen <= 260:
        score += 2.0
    elif tlen > 270:
        score -= 1.0

    return score


def write_tweet(llm_client, chosen_alerts: list[dict], event_summary: str,
                bundle: dict, chart_pick: dict, *,
                image_tiles: list[str] | None = None,
                recent_openers: list[str] | None = None,
                lede_shape_hint: str | None = None,
                usage: dict | None = None,
                prior_error: str | None = None) -> dict:
    """Stage 4: compose one candidate tweet.

    `lede_shape_hint` (timing/impact/size/age/cluster/behavior/stakes) steers
    the writer toward a specific lede shape so multi-candidate generation
    yields diverse openers. Caller invokes this once per shape and reranks.
    """
    from bot_utils import MODEL, _accumulate_usage
    messages = [{"role": "system", "content": SYSTEM_PROMPT_WRITER}]
    user_payload = _writer_user_message(
        chosen_alerts, event_summary, bundle, chart_pick,
        image_tiles=image_tiles, recent_openers=recent_openers,
        lede_shape_hint=lede_shape_hint,
    )
    if prior_error:
        user_payload = (
            f"Your previous tweet failed validation: {prior_error}. Regenerate.\n\n"
            + user_payload
        )
    messages.append({"role": "user", "content": user_payload})
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
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
        return {"tweet": "", "_parse_error": f"invalid JSON: {exc}"}


SYSTEM_PROMPT_TWEET_VALIDATOR = """You are the fact-checker and style police for a \
Polymarket tweet bot. You see a candidate tweet plus the exact facts the writer was \
given. You flag claims that don't reconcile with those facts AND clear style \
violations. You do NOT verify Polymarket reality, news, or anything outside the \
provided bundle — bundle errors are not your problem.

You see: tweet, event_summary, facts_bundle, chosen_alerts, chart_type, hook_anchor,
image_tiles, recent_openers, recent_tweets.

## Tier 1 — hard rejections (fact reconciliation)

1. Dollar figures. Every $ in the tweet must round-match facts_bundle.total_usd,
   has_sharp_wallet.bet_usd, peak_hour_volume_usd, or a defensible sum.
   Tolerance: ±10% or ±$500, whichever is larger.

2. Volume multiplier. "Nx" / "N times" volume must match
   facts_bundle.volume_multiplier_x within ±20%. Do NOT accept volume figures
   from event_summary or alert headlines — those use a different baseline. If
   volume_multiplier_x is null, the tweet must not claim a volume multiplier.

3. Wallet record. Digits like "732-127", "85%", "110-3" must match
   facts_bundle.has_sharp_wallet.record / win_pct exactly (round win_pct to
   nearest %). Records cited that don't appear in the bundle are rejected.

4. Wallet age. "N-day-old account" must be within ±2 days of
   facts_bundle.has_fresh_wallet.wallet_age_days.

5. Time-to-resolution. Hard clocks ("11 minutes to tip", "first pitch in 90")
   must match facts_bundle.minutes_to_resolution within ±20%. If
   minutes_to_resolution > 360, no hard clock allowed; soft "by Tuesday" is fine.

6. Side. The outcome the tweet credits with informed flow must match
   event_summary and chosen_alerts. Yes when alerts are No → reject.

7. Sharp vs cluster stake. When has_sharp_wallet.bet_usd <= 0.5 * total_usd,
   the tweet must not imply the sharp wallet bet the full cluster sum.

8. Price move. Specific cents like "32c", "41c", or a delta like "32c → 41c"
   must match facts_bundle.biggest_price_move.from / .to (×100, nearest cent).
   If biggest_price_move is null, no specific price flip allowed.

9. Wallet count. "Five accounts", "8 wallets", "three wallets" must match
   facts_bundle.distinct_wallets or cluster_size within ±1.

## Tier 2 — hard rejections (clear style violations)

10. Banned jargon. Tweet must not contain any of:
    "deployed capital", "real size", "meaningful size", "conviction flow",
    "high-conviction", "scan window", "composite score", "alerted flow",
    "positioning", "near-resolution flag", "priced in", "coordinated burst",
    "pile-in", "counterpunch", "looked cleaner", "linked wallet",
    "linked wallets", "wallet trio", "wallet duo", "wallet squad",
    "informed flow", "smart money flow".

11. Strategy-label leakage. Tweet must not surface raw strategy names as nouns:
    "wallet clustering", "price impact", "volume spike", "win rate tracking",
    "new wallet large bet", "concentrated one-sided", "correlated cross-market".
    Behavior is required, not labels (e.g. "10× the usual flow" not "volume
    spike"; "three accounts sharing one funder" not "wallet clustering").

12. Hashtags / mentions / emoji budget. Reject any "#" hashtag, any "@"
    mention, or more than one emoji.

13. Raw wallet addresses. Tweet must not contain a 0x-prefixed address.
    Wallets are described by record, age, or behavior.

14. Vague chest-thump closer. The final clause must not be: "Not random.",
    "Something's cooking.", "Worth a look.", "Watch this space.", "Eyes on
    this.", or any equivalent empty signal-off. Closers must be a concrete
    clock, stake, or counter-fact.

14b. Recent-event repeat (double-protection backstop on the event picker).
    `recent_tweets` lists the last ~10 tweets we shipped with their text and
    the condition_ids each covered. Reject when the candidate tweet
    re-covers an event we already tweeted:
    - Any condition_id in chosen_alerts overlaps a condition_ids list in
      recent_tweets → reject ("rule 14b: condition_id <X> already covered
      in recent tweet at <ts>").
    - The candidate tweet describes the same broader story as a recent
      tweet — same event, same directional thesis, same wallet
      spotlight — even when the condition_id differs → reject. A genuinely
      different angle on the same event (a new wallet, a clearly different
      thesis, a fresh price move) is allowed; lean toward rejecting only
      on CLEAR overlap.

## Tier 3 — soft rejections (judgment; only flag CLEAR violations)

15. Passive scanner-caption opener. Reject ledes shaped like
    "The <SIDE> side just got bought…", "<TEAM> money just …",
    "<N>-wallet <SIDE> cluster…", "<N>x volume spike…" used as a
    noun-phrase opener with no clock, impact, or behavior.

16. Cumulative-as-just-now. If a $ figure exceeds facts_bundle.total_usd, the
    tweet must frame it cumulatively ("have built", "now sit at"), not as a
    fresh push ("just bought", "in the last hour", "minutes before X").

17. Spell-out-what-bet-is-on. Bare outcomes ("Under", "Over", "Yes", "No",
    "Yes for $40k") without naming what the bet is ON → reject. Required:
    "Under 7.5 runs", "Yes on Fed cuts in May", "buying No at 12c". Context
    can come earlier in the same tweet ("US-Iran peace-deal odds slid from
    79c to 62c… $19k of No" is fine — "No" is anchored).

18. Win-rate-with-count. A bare "wins 88% of the time" → reject. Must be
    anchored to a count: "88% across 50+ Polymarket bets" or a literal record
    like "178-20".

19. Lede priority. When facts_bundle.minutes_to_resolution is set and < 60
    AND the tweet does not lead with the clock → reject (timing beats
    everything). When facts_bundle.biggest_price_move shows |to-from| >= 0.03
    AND the tweet does not lead with the impact → reject (impact beats size).

20. Opener mimicry. If the tweet's first 3-4 words match the template/shape
    of any string in recent_openers → reject. Exact word match isn't
    required; the SHAPE must differ.

21. Stat budget. More than 3 distinct numerical STATS in the tweet body.
    URLs do not count. A "stat" is one fact (one signal), not one number
    — a single stat can contain multiple digits and still count as one.
    One stat each: a price flip ("34c → 29c", "79c to 62c") = the price
    move, a record ("178-20", "50-1"), a dollar figure ("$8k"), a
    multiplier ("12× usual"), a wallet/account count ("three accounts"),
    a wallet age ("31-day-old"), a clock ("147 minutes"), a percentage
    ("88%"). Count stats, not digits.

22. Rounding. Dollar figures must be rounded ("$78k" / "$2.8M"), not raw
    ("$78,131.61"). Win-rate records stay exact.

## Output (strict JSON only)
{
  "ok": true | false,
  "error": "<rule number and one short sentence naming what failed>" | null
}

When ok=false, error must be specific enough for the writer to fix on retry,
e.g. "rule 2: tweet says '103x' but volume_multiplier_x is 1.25" or
"rule 17: 'bought $9.6k of No' missing what the bet is ON".
"""


def llm_validate_tweet(llm_client, tweet: str, chosen_alerts: list[dict],
                       event_summary: str, bundle: dict, chart_pick: dict,
                       image_tiles: list[str] | None = None,
                       recent_openers: list[str] | None = None,
                       recent_tweets: list[dict] | None = None,
                       *, usage: dict | None = None) -> tuple[bool, str]:
    """LLM second-pass fact/style check. Returns (ok, error).

    Fails open on validator parse error — we don't want a flaky validator
    blocking an otherwise-good tweet.

    `recent_tweets` is the same list shown to the event picker (last ~10
    posted tweets with text + condition_ids). The validator uses it as a
    backstop for rule 14b — if the picker slipped a duplicate event
    through, the validator catches it here.
    """
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker, log
    payload = {
        "tweet": tweet,
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": [_compact_alert_for_picker(a) for a in chosen_alerts],
        "chart_type": chart_pick.get("chart_type"),
        "hook_anchor": chart_pick.get("hook_anchor"),
        "image_tiles": image_tiles or [],
        "recent_openers": recent_openers or [],
        "recent_tweets": recent_tweets or [],
    }
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_TWEET_VALIDATOR},
            {"role": "user", "content": json.dumps(payload, default=str, indent=2)},
        ],
        temperature=1,
        max_completion_tokens=3000,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        log("llm_validator_parse_error", error=str(exc))
        return True, ""
    if result.get("ok"):
        return True, ""
    return False, str(result.get("error") or "llm validator rejected tweet")


def _validate_combined(llm_client, tweet, chosen_alerts, event_summary, bundle,
                       chart_pick, image_tiles, recent_openers, recent_tweets,
                       usage) -> tuple[bool, str]:
    """Deterministic checks first (cheap, fail-fast), then LLM fact/style check.

    Order: text-shape check → chart-anchor check → LLM validator. The
    chart-anchor check is deterministic and cheap; running it before the
    LLM call avoids paying for an LLM validation on a tweet we already
    know is missing the chart's anchor fact.
    """
    ok, err = validate_tweet(tweet)
    if not ok:
        return False, err
    ok, err = validate_tweet_anchor(tweet, chart_pick, bundle)
    if not ok:
        return False, err
    return llm_validate_tweet(llm_client, tweet, chosen_alerts, event_summary,
                              bundle, chart_pick, image_tiles=image_tiles,
                              recent_openers=recent_openers,
                              recent_tweets=recent_tweets, usage=usage)


def write_tweet_with_retry(llm_client, chosen_alerts, event_summary, bundle,
                           chart_pick, *, image_tiles=None,
                           recent_openers=None,
                           recent_tweets=None,
                           usage=None,
                           candidate_count: int = 3,
                           ) -> tuple[dict, str | None, int]:
    """Generate N candidate tweets with diverse lede shapes, validate each,
    rerank, and return the best.

    Round 1: pick up to `candidate_count` lede shapes from the bundle, call
    the writer once per shape, run cheap deterministic checks (text-shape +
    chart-anchor) on each candidate. Of the candidates that pass, rank by
    `_score_candidate` and run the LLM fact/style validator on the winner.

    Round 2 (only on round-1 failure): single retry with the highest-priority
    shape hint and the round-1 error fed back. Same validation chain.

    Returns (final_decision_dict, error_or_None, attempts) — `attempts` is
    the number of ROUNDS (1 or 2), not individual writer calls.
    """
    from bot_utils import log

    shapes = _pick_candidate_shapes(bundle, n=candidate_count)

    candidates: list[tuple[str, dict]] = []  # (shape, decision_dict)
    last_det_error: str | None = None
    for shape in shapes:
        out = write_tweet(
            llm_client, chosen_alerts, event_summary, bundle, chart_pick,
            image_tiles=image_tiles, recent_openers=recent_openers,
            lede_shape_hint=shape, usage=usage,
        )
        if out.get("_parse_error"):
            last_det_error = out["_parse_error"]
            continue
        text = out.get("tweet", "")
        ok, err = validate_tweet(text)
        if not ok:
            last_det_error = err
            continue
        ok, err = validate_tweet_anchor(text, chart_pick, bundle)
        if not ok:
            last_det_error = err
            continue
        candidates.append((shape, out))

    if candidates:
        candidates.sort(
            key=lambda c: _score_candidate(c[1].get("tweet", ""), bundle, chart_pick),
            reverse=True,
        )
        winning_shape, winner = candidates[0]
        log("candidate_rerank",
            shapes=[s for s, _ in candidates],
            winner_shape=winning_shape,
            candidate_count=len(candidates),
            shapes_attempted=shapes)
        ok, err = llm_validate_tweet(
            llm_client, winner.get("tweet", ""), chosen_alerts, event_summary,
            bundle, chart_pick, image_tiles=image_tiles,
            recent_openers=recent_openers, recent_tweets=recent_tweets,
            usage=usage,
        )
        if ok:
            return winner, None, 1
        log("validation_retry", error=err, shape=winning_shape)
        retry_shape = winning_shape
        retry_error = err
    else:
        log("all_candidates_failed_deterministic",
            shapes_attempted=shapes, last_error=last_det_error)
        retry_shape = shapes[0]
        retry_error = last_det_error or "all candidates failed deterministic checks"

    # Round 2: single retry with the prior error fed back.
    retry_out = write_tweet(
        llm_client, chosen_alerts, event_summary, bundle, chart_pick,
        image_tiles=image_tiles, recent_openers=recent_openers,
        lede_shape_hint=retry_shape, prior_error=retry_error, usage=usage,
    )
    if retry_out.get("_parse_error"):
        return retry_out, retry_out["_parse_error"], 2
    ok, err = _validate_combined(
        llm_client, retry_out.get("tweet", ""), chosen_alerts, event_summary,
        bundle, chart_pick, image_tiles, recent_openers, recent_tweets, usage,
    )
    return retry_out, (None if ok else err), 2


def _select_chosen_alerts(alert_ids: list[int], seed_alerts: list[dict]) -> list[dict]:
    """Filter seed_alerts down to those whose id is in alert_ids.

    Preserves alert_ids order so chosen_alerts[i] corresponds to alert_ids[i]
    (matching the trades-loop ordering in fetch_data_bundle).
    """
    by_id = {int(a.get("id") or 0): a for a in seed_alerts}
    return [by_id[int(i)] for i in alert_ids if int(i) in by_id]


def _chart_target_alert_id(chart_type: str, alert_ids: list[int],
                           facts_bundle: dict) -> int:
    """Pick which chosen alert the chart should render against.

    fresh_wallet_card and wallet_record_card are wallet-bound — they must
    render against the alert whose wallet matches the chart's subject, which
    isn't always the cluster's primary alert. Other chart types fall back to
    the primary alert.

    The has_fresh_wallet / has_sharp_wallet entries always reference an
    alert in `chosen_alerts` (they're built from the same list), so the
    resolved id is guaranteed to be a member of `alert_ids`.
    """
    primary = int(alert_ids[0])
    if chart_type == "fresh_wallet_card":
        info = facts_bundle.get("has_fresh_wallet") or {}
        return int(info.get("alert_id") or primary)
    if chart_type == "wallet_record_card":
        info = facts_bundle.get("has_sharp_wallet") or {}
        return int(info.get("alert_id") or primary)
    return primary


def build_enriched_facts_bundle(
    chosen_alerts: list[dict],
) -> tuple[dict, list[dict]]:
    """Fetch trades for chosen_alerts, build a facts_bundle, and apply the
    volume_multiplier_x enrichment when has_volume_spike fires.

    Returns (facts_bundle, trades). Shared by twitter_pipeline.fetch_data_bundle
    and articlebot's chart-grid path so both bots produce the same bundle
    shape from the same alerts. Failures are absorbed — missing trades stay
    as [], the volume enrichment silently leaves volume_multiplier_x as None.
    """
    from tweet_utils import fetch_alert_trades
    from bot_utils import log

    trades: list[dict] = []
    for a in chosen_alerts:
        aid = a.get("id")
        if aid is None:
            continue
        try:
            trades.extend(fetch_alert_trades(int(aid)))
        except Exception as exc:
            log("alert_trades_fetch_error",
                alert_id=aid, error=f"{type(exc).__name__}: {exc}")

    facts_bundle = build_facts_bundle(chosen_alerts, trades)
    if facts_bundle["has_volume_spike"]:
        # Use the same fetchers volume_bar uses, on the condition_id of the
        # alert that actually fired pre_event_volume_spike — picking the
        # first cid in the cluster would describe the wrong market for
        # cross-market clusters. One gamma call + one sqlite read per tweet.
        spike_alert = next(
            (a for a in chosen_alerts
             if any(s.get("strategy") == "pre_event_volume_spike"
                    for s in (a.get("signals") or []))
             and a.get("condition_id")),
            None,
        )
        cid = spike_alert.get("condition_id") if spike_alert else None
        if cid:
            try:
                today = charts._fetch_gamma_volume24hr(cid)
                baseline = charts._fetch_baseline_avg_volume(cid)
                if today > 0 and baseline and baseline > 0:
                    facts_bundle["volume_multiplier_x"] = today / baseline
            except Exception as exc:
                log("volume_multiplier_fetch_error",
                    error=f"{type(exc).__name__}: {exc}")

    return facts_bundle, trades


def fetch_data_bundle(alert_ids: list[int], seed_alerts: list[dict]) -> dict:
    """Stage 2: fetch trades + Gamma tokens for chosen alerts, build facts_bundle.

    Returns: {chosen_alerts, trades, token_map, facts_bundle}.
    Failures are absorbed — missing trades become [], missing tokens become {}.
    """
    from tweet_utils import fetch_market_tokens

    chosen = _select_chosen_alerts(alert_ids, seed_alerts)
    facts_bundle, trades = build_enriched_facts_bundle(chosen)

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
        "facts_bundle": facts_bundle,
    }


def _dump_transcript(run_id: str, transcript: dict) -> None:
    """Write the full stage transcript to <output_dir>/twitter_pipeline_<run_id>.json.

    Output dir is `dry_runs/` when DRY_RUN, else `live_runs/`.
    """
    from bot_utils import log
    os.makedirs(_RUN_OUTPUT_DIR, exist_ok=True)
    path = os.path.join(_RUN_OUTPUT_DIR, f"twitter_pipeline_{run_id}.json")
    try:
        with open(path, "w") as f:
            json.dump(transcript, f, default=str, indent=2)
        log("transcript_saved", path=path)
    except OSError as exc:
        log("transcript_save_error", error=str(exc))


def main() -> int:
    from bot_utils import (
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, DATABASE_URL, log,
        fetch_seed_alerts,
    )
    from tweet_utils import (
        _build_twitter_api_v1, _build_twitter_client,
        fetch_recent_tweet_openers, fetch_recent_tweets,
        filter_posted_alerts, post_tweet, prepare_chart_grid, record_tweet,
        strip_polyspotter_url,
    )

    run_id = uuid.uuid4().hex[:8]
    log("run_start", run_id=run_id, dry_run=DRY_RUN, bot="twitter_pipeline")

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    usage_totals: dict = {}
    run_start_t = time.monotonic()
    transcript: dict = {"run_id": run_id, "stages": {}}

    # Seed
    t = time.monotonic()
    try:
        seed_alerts = fetch_seed_alerts()
    except Exception as exc:
        log("seed_fetch_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    log("seed_fetched", run_id=run_id, count=len(seed_alerts),
        elapsed_ms=int((time.monotonic() - t) * 1000))
    if not seed_alerts:
        log("skip", run_id=run_id, reason="no alerts in last 3 hours")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    pre = len(seed_alerts)
    try:
        seed_alerts = filter_posted_alerts(seed_alerts)
    except Exception as exc:
        log("dedup_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    log("dedup_filtered", run_id=run_id, before=pre, after=len(seed_alerts),
        dropped=pre - len(seed_alerts))
    if not seed_alerts:
        log("skip", run_id=run_id, reason="all seed alerts already tweeted")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    # Recent tweets — shown to the event picker (and validator) so we don't
    # re-cover an event we just tweeted. Pull this BEFORE stage 1 since the
    # picker needs it; the same list is reused by stage 4's validator.
    recent_tweets = fetch_recent_tweets(limit=10)
    log("recent_tweets_loaded", run_id=run_id, count=len(recent_tweets))

    # Stage 1
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=1)
    try:
        pick = pick_event(llm_client, seed_alerts,
                          recent_tweets=recent_tweets, usage=usage_totals)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, stage=1,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=1,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["1_event_picker"] = pick
    ok, err = validate_event_pick(pick, seed_alerts)
    if not ok:
        log("validation_error", run_id=run_id, stage=1, error=err, pick=pick)
        _dump_transcript(run_id, transcript)
        return 1
    if pick["decision"] == "skip":
        log("skip", run_id=run_id, reason=pick.get("reason"))
        _dump_transcript(run_id, transcript)
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0
    log("event_picked", run_id=run_id, alert_ids=pick["alert_ids"],
        event_summary=pick["event_summary"])

    # Stage 2
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=2)
    bundle = fetch_data_bundle(pick["alert_ids"], seed_alerts)
    log("stage_end", run_id=run_id, stage=2,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    log("data_fetched", run_id=run_id,
        trade_count=len(bundle["trades"]),
        token_keys=list(bundle["token_map"].keys()),
        facts_bundle_keys=list(bundle["facts_bundle"].keys()))
    transcript["stages"]["2_data_fetcher"] = {
        "trade_count": len(bundle["trades"]),
        "token_map": bundle["token_map"],
        "facts_bundle": bundle["facts_bundle"],
    }

    # Stage 3
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=3)
    try:
        chart_pick = pick_chart(llm_client, bundle["chosen_alerts"],
                                pick["event_summary"], bundle["facts_bundle"],
                                usage=usage_totals)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, stage=3,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=3,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["3_chart_picker"] = chart_pick
    ok, err = validate_chart_pick(chart_pick)
    if not ok:
        log("validation_error", run_id=run_id, stage=3, error=err, pick=chart_pick)
        _dump_transcript(run_id, transcript)
        return 1
    log("chart_picked", run_id=run_id, chart_type=chart_pick["chart_type"],
        hook_anchor=chart_pick["hook_anchor"])

    # Stage 4
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=4)
    image_tiles_kinds = [tile.kind for tile in chart_grid.select_tiles(
        chart_pick["chart_type"], bundle["facts_bundle"])]
    recent_openers = fetch_recent_tweet_openers(limit=5)
    log("recent_openers_loaded", run_id=run_id, count=len(recent_openers))
    try:
        decision, err, attempts = write_tweet_with_retry(
            llm_client, bundle["chosen_alerts"], pick["event_summary"],
            bundle["facts_bundle"], chart_pick,
            image_tiles=image_tiles_kinds,
            recent_openers=recent_openers,
            recent_tweets=recent_tweets,
            usage=usage_totals)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, stage=4,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=4, attempts=attempts,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["4_writer"] = {"decision": decision, "attempts": attempts}
    if err:
        log("validation_error", run_id=run_id, stage=4, attempts=attempts,
            error=err, decision=decision)
        _dump_transcript(run_id, transcript)
        return 1

    tweet = strip_polyspotter_url(decision["tweet"])
    log("tweet_drafted", run_id=run_id, attempts=attempts, length=len(tweet))
    log("llm_usage", run_id=run_id, **usage_totals)

    # Resolve chart png. Wallet-shaped charts must target the specific alert
    # whose wallet is the chart's subject (the fresh wallet for fresh_wallet_card,
    # the sharp wallet for wallet_record_card) — that alert isn't always the
    # primary one in the cluster. Other chart types use the primary alert.
    target_alert_id = _chart_target_alert_id(
        chart_pick["chart_type"], pick["alert_ids"], bundle["facts_bundle"])
    target_alert = next(
        (a for a in bundle["chosen_alerts"]
         if int(a.get("id") or 0) == target_alert_id),
        None,
    )
    chart_png = (prepare_chart_grid(chart_pick["chart_type"], target_alert,
                                    facts_bundle=bundle["facts_bundle"])
                 if target_alert else None)
    log("chart_selected", run_id=run_id, chart_type=chart_pick["chart_type"],
        rendered=chart_png is not None,
        bytes_len=(len(chart_png) if chart_png else 0))

    if chart_png is not None:
        os.makedirs(_RUN_OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(_RUN_OUTPUT_DIR, f"twitter_pipeline_{run_id}.png")
        try:
            with open(out_path, "wb") as f:
                f.write(chart_png)
            log("chart_saved", run_id=run_id, path=out_path)
        except OSError as exc:
            log("chart_save_error", run_id=run_id, error=str(exc))

    _dump_transcript(run_id, transcript)

    # Post
    try:
        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
        tweet_id = post_tweet(
            tweet, twitter_client=twitter_client, twitter_api_v1=twitter_api_v1,
            media_png=chart_png, dry_run=DRY_RUN,
        )
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    log("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=pick["alert_ids"],
        tweet_length=len(tweet))
    print(f"\n--- Tweet ({len(tweet)} chars) ---\n{tweet}\n", flush=True)

    if DRY_RUN:
        try:
            answer = input("\nPost this tweet for real? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
                elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
            return 0
        try:
            tweet_id = post_tweet(
                tweet, twitter_client=twitter_client, twitter_api_v1=twitter_api_v1,
                media_png=chart_png, dry_run=False,
            )
        except Exception as exc:
            log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
            return 1
        log("posted_after_confirm", run_id=run_id, tweet_id=tweet_id,
            alert_ids=pick["alert_ids"], tweet_length=len(tweet))

    try:
        record_tweet([int(i) for i in pick["alert_ids"]], tweet_id, tweet)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
