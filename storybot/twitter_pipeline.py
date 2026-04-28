"""
4-stage Twitter bot: event picker → deterministic data fetch → chart picker → writer.

Run via cron:
    python storybot/twitter_pipeline.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from charts import CHART_TYPES as _CHART_TYPES_TUPLE

import os
import sys
import time
import uuid

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")


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


def _extract_sharp_wallet(chosen_alerts: list[dict],
                          trades: list[dict]) -> dict | None:
    """Try llm_copy_action first; fall back to wallet_pnl summary if a
    win_rate_tracking signal exists. For cluster alerts (no top-level wallet),
    scan the cluster's trades and pick the highest-win-rate wallet meeting the
    min resolved-positions threshold — matching the chart fetcher's cluster
    path in storybot.charts.fetch_wallet_record_card_data."""
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
                "alert_id": int(a.get("id") or 0),
            }

    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any(s.get("strategy") == "win_rate_tracking" for s in signals):
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
        }
    return None


def _extract_fresh_wallet(chosen_alerts: list[dict],
                          trades: list[dict]) -> dict | None:
    """Surface a fresh-account bet if the cluster contains a new_wallet_large_bet
    signal. Returns {wallet, alert_id} for the first match, else None.

    Single-wallet alerts: trust the signal and skip the age check (the chart
    fetcher does it). Cluster alerts (no top-level wallet): scan the cluster's
    trades and pick the youngest wallet within FRESH_WALLET_MAX_DAYS — matching
    the chart fetcher's cluster path in storybot.charts.fetch_fresh_wallet_card_data.
    """
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any(s.get("strategy") == "new_wallet_large_bet" for s in signals):
            continue
        if a.get("wallet"):
            return {"wallet": a["wallet"], "alert_id": int(a.get("id") or 0)}
        candidates = _distinct_trade_wallets(trades)
        if not candidates:
            continue
        import charts
        best = charts.youngest_fresh_wallet(candidates)
        if best is None:
            continue
        wallet, _age_days = best
        return {"wallet": wallet, "alert_id": int(a.get("id") or 0)}
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
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts, trades),
        "has_fresh_wallet": _extract_fresh_wallet(chosen_alerts, trades),
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


SYSTEM_PROMPT_CHART_PICKER = """You pick a chart that proves the surprise the \
upcoming tweet will lead with. You also write the hook_anchor — one short \
phrase naming the surprising fact the chart visualizes.

You see:
- event_summary: a paragraph framing the story
- facts_bundle: precise numbers about the chosen event
- chosen_alerts: the compact alert rows that make up the cluster

## Available chart types
- "wallet_record_card" — one wallet's win record + their bet on this market.
  Pick this iff facts_bundle.has_sharp_wallet is non-null.
- "fresh_wallet_card" — one wallet's age + their bet on this market.
  Pick this iff facts_bundle.has_fresh_wallet is non-null AND
  facts_bundle.has_sharp_wallet is null. (A record beats an age when both
  apply — wallet_record_card wins the tiebreak.)
- "price_sparkline" — price over time on the dominant outcome.
  Pick this iff facts_bundle.biggest_price_move is non-null AND the move is
  meaningful. Polymarket prices are 0.0-1.0 probabilities; "3 cents" means a
  delta of 0.03. Threshold: |to - from| >= 0.03 OR
  |to - from| / max(from, to, 0.01) >= 0.10.
- "volume_bar" — volume bars showing a spike.
  Pick this iff facts_bundle.has_volume_spike is true OR
  peak_hour_volume_usd dwarfs other windows.
- "cluster_card" — multi-wallet cluster card.
  Pick this iff facts_bundle.cluster_size >= 3 AND no sharp_wallet record
  dominates (otherwise prefer wallet_record_card and mention the cluster
  in the tweet text).
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


_VALID_CHART_TYPES = frozenset(_CHART_TYPES_TUPLE)


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

Your job: write a tweet that fits in 280 characters (URLs count as 23 chars).

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
- Lead with the SINGLE most surprising fact in the story — not the structural
  setup, not a chart label. Identify the one thing that makes a reader stop
  scrolling, and put it in the first clause as natural English. The hook_anchor
  tells you which fact the chart proves; your job is to express that fact in
  human voice. The lede shape depends on what's actually surprising:
  - win_rate / sharp wallet → record-led: "An account that's gone 29-4 on
    Polymarket just…"
  - new_wallet_large_bet → age-led: "A 12-day-old account just dropped $80k…"
  - timing_relative_resolution → timing-led: "With 4 minutes left, someone bought…"
  - price_impact → impact-led: "One buy just flipped this market from 32c to 41c…"
  - low_activity_large_bet → size-led: "$50k just landed on a market that's
    seen $4k all week…"
  - wallet_clustering / concentrated_one_sided → cluster-led only if the
    cluster IS the surprising thing; if one of the cluster wallets has a
    strong record, lead with the record and bring in the cluster as
    supporting context. Even when cluster-led, write it as behavior
    ("Eight Polymarket accounts just bought…") not as a tile name
    ("8-wallet NO cluster…").
- Pacing: 2-3 short sentences beats one long clause-stack. Aim for ≤20 words
  per sentence. Punchy rhythm > polished prose.
- Round numbers for readability: "$78k" not "$78,131.61"; "$2.8M" not "$2,789,285.20".
  Win-rate records stay exact ("178-20"). Max 3 numbers.
- Refer to wallets by what makes them notable ("a 178-20 wallet", "a fresh account
  up $400k"), not by 0x address.
- The closing line earns its spot: a stake, a time pressure, or something concrete
  to watch. NOT vague chest-thumps like "Not random.", "Something's cooking.",
  "Worth a look.". If you don't have a real closer, end on the link.
- 0-1 emoji, only if it earns its spot. No hashtags. No @mentions.
- BANNED jargon: "deployed capital", "real size", "meaningful size", "conviction
  flow", "high-conviction", "scan window", "composite score", "alerted flow",
  "positioning", "near-resolution flag", "priced in", "coordinated burst",
  "pile-in", "counterpunch", "looked cleaner", "linked wallet(s)", "wallet trio",
  "wallet duo", "wallet squad", "informed flow", "smart money flow".
- Banned tile-talk lede shapes: "<N>-wallet <SIDE> cluster", "<N>x volume spike",
  "<wallet> sharp record" used as a noun-phrase opener. Restate as behavior.
- Banned CTAs: "in bio", "full breakdown", "link below", "more at", "link in bio".

## Worked example
BAD (jargon-heavy, no context, vague closer):
  "A linked wallet trio just slammed Red Sox/Orioles Under 7.5 for $32k.
  One buyer wins 88% of the time. Not random baseball action."
Why it's bad: "linked wallet trio" is insider lingo, "Under 7.5" omits the
unit (runs), "wins 88%" omits what (Polymarket bets), nothing tells the
reader this is a prediction market, and the closer adds no information.

OK (clear but buries the lede in a long opening clause):
  "Three Polymarket accounts sharing one funder just stacked $32k on
  Red Sox/Orioles staying under 7.5 runs tonight. One of them is 88%
  across 50+ prior bets on the site."
Why it's only OK: the strongest fact (the 88% record) shows up second,
and the opening sentence runs ~25 words.

GOOD (lead with the record, short sentences):
  "A Polymarket account with a 29-4 record just helped pile $65k on
  Red Sox/Orioles staying under 7.5 runs tonight. Two more accounts
  on the same funder rode along.
  https://polyspotter.com/alert/114781"

Tile-label trap (avoid):
  "7-wallet NO cluster against Finland winning Eurovision 2026: bettors
  bought about $20k of No on Polymarket. Volume hit 130x the market's
  usual pace."
Why it's bad: "7-wallet NO cluster against …" is a chart caption, not a
tweet opener. Restate as behavior.

Better:
  "Eight Polymarket accounts just bought $23k of No on Finland winning
  Eurovision 2026. The market's usual volume got blown out by an 82x
  surge, months before the final."

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
    """Length / banned-phrase / link presence checks. No JSON parsing."""
    from tweet_utils import (
        TWEET_MAX_CHARS, _BANNED_TWEET_PHRASES, _POLYSPOTTER_URL_RE, _tweet_length,
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
    if not _POLYSPOTTER_URL_RE.search(text):
        return False, "tweet must contain a polyspotter.com deep link"
    return True, ""


def _writer_user_message(chosen_alerts: list[dict], event_summary: str,
                         bundle: dict, chart_pick: dict) -> str:
    from bot_utils import _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
        "chart_type": chart_pick.get("chart_type"),
        "hook_anchor": chart_pick.get("hook_anchor"),
    }
    return json.dumps(payload, default=str, indent=2)


def write_tweet(llm_client, chosen_alerts: list[dict], event_summary: str,
                bundle: dict, chart_pick: dict, *,
                usage: dict | None = None,
                prior_error: str | None = None) -> dict:
    """Stage 4: compose the tweet. Caller invokes this twice if validation fails."""
    from bot_utils import MODEL, _accumulate_usage
    messages = [{"role": "system", "content": SYSTEM_PROMPT_WRITER}]
    user_payload = _writer_user_message(chosen_alerts, event_summary, bundle, chart_pick)
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


def write_tweet_with_retry(llm_client, chosen_alerts, event_summary, bundle,
                           chart_pick, *, usage=None) -> tuple[dict, str | None, int]:
    """Run stage 4 once; on validation failure, retry once with the error fed back.

    Returns (final_decision_dict, error_or_None, attempts).
    """
    from bot_utils import log
    attempt = 1
    out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                      usage=usage)
    if out.get("_parse_error"):
        log("validation_retry", error=out["_parse_error"])
        attempt = 2
        out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                          usage=usage, prior_error=out["_parse_error"])
        if out.get("_parse_error"):
            return out, out["_parse_error"], attempt
        ok, err = validate_tweet(out.get("tweet", ""))
        return (out, None, attempt) if ok else (out, err, attempt)

    ok, err = validate_tweet(out.get("tweet", ""))
    if ok:
        return out, None, attempt
    log("validation_retry", error=err)
    attempt = 2
    out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                      usage=usage, prior_error=err)
    if out.get("_parse_error"):
        return out, out["_parse_error"], attempt
    ok, err = validate_tweet(out.get("tweet", ""))
    return (out, None, attempt) if ok else (out, err, attempt)


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


def _dump_dry_run(run_id: str, transcript: dict) -> None:
    """Write the full stage transcript to dry_runs/twitter_pipeline_<run_id>.json."""
    from bot_utils import log
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"twitter_pipeline_{run_id}.json")
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
        filter_posted_alerts, post_tweet, prepare_chart, record_tweet,
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

    # Stage 1
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=1)
    try:
        pick = pick_event(llm_client, seed_alerts, usage=usage_totals)
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
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
        return 1
    if pick["decision"] == "skip":
        log("skip", run_id=run_id, reason=pick.get("reason"))
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
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
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
        return 1
    log("chart_picked", run_id=run_id, chart_type=chart_pick["chart_type"],
        hook_anchor=chart_pick["hook_anchor"])

    # Stage 4
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=4)
    try:
        decision, err, attempts = write_tweet_with_retry(
            llm_client, bundle["chosen_alerts"], pick["event_summary"],
            bundle["facts_bundle"], chart_pick, usage=usage_totals)
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
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
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
    chart_png = (prepare_chart(chart_pick["chart_type"], target_alert)
                 if target_alert else None)
    log("chart_selected", run_id=run_id, chart_type=chart_pick["chart_type"],
        rendered=chart_png is not None,
        bytes_len=(len(chart_png) if chart_png else 0))

    if DRY_RUN and chart_png is not None:
        os.makedirs(_DRY_RUN_DIR, exist_ok=True)
        out_path = os.path.join(_DRY_RUN_DIR, f"twitter_pipeline_{run_id}.png")
        try:
            with open(out_path, "wb") as f:
                f.write(chart_png)
            log("chart_saved_dryrun", run_id=run_id, path=out_path)
        except OSError as exc:
            log("chart_save_error", run_id=run_id, error=str(exc))

    if DRY_RUN:
        _dump_dry_run(run_id, transcript)

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
        log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

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
