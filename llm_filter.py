"""
LLM filter — passes each alert through Claude to decide if it's truly interesting.

Uses a local SQLite cache (llm_evaluations table in polybot.db) to avoid
re-evaluating the same alert across runs.

Returns a short explanation string if interesting, or None to discard.
"""

from __future__ import annotations

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

from db import get_llm_evaluation, save_llm_evaluation

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You are a Polymarket unusual activity analyst. You receive alerts about "
    "suspicious trades flagged by 9 automated detection strategies. Your job: "
    "decide if this alert represents genuinely interesting or suspicious trading "
    "activity that a human analyst should review.\n\n"

    "## Alert structure\n"
    "Each alert has a composite_score (sum of signal severities), total USD value, "
    "trade count, and a list of detection signals. Alerts are either:\n"
    "- **individual**: a single wallet's trades on a market, with per-trade signals\n"
    "- **cluster**: multiple wallets betting the same direction on a market (from "
    "concentrated_one_sided), with shared + per-trade signals\n\n"

    "## Detection strategies and what their signals mean\n\n"

    "**win_rate_tracking** (severity 1.0-6.0): Tracks wallet P&L history. Fires when "
    "a wallet has >=75% win rate on 10+ resolved bets AND beats implied odds by 15%+ "
    "(edge-adjusted). A wallet winning 90% at avg odds of 40% has extraordinary edge. "
    "A wallet winning 90% on 90% favorites is unremarkable. Higher severity = larger "
    "edge and confirmed profitability.\n\n"

    "**new_wallet_large_bet** (severity 1.0-7.0): Flags wallets <30 days old making "
    "large bets ($3k+). Severity scales with wallet youth (<7d = 3.5, <14d = 2.5, "
    "<30d = 1.5). Repeat offenders get escalated (+0.5 per flag, up to +2.0). "
    "Cross-referenced with P&L: a 'new' wallet that already has many positions or "
    "is profitable gets boosted. This is a core insider trading indicator.\n\n"

    "**timing_relative_resolution** (severity 1.0-8.0): Flags bets placed within 60 "
    "minutes of a market's resolution time. Severity scales continuously (5.0 at 0min, "
    "~2.5 at 10min, ~1.0 at 60min). Short-duration markets (<2h lifespan like 5-min "
    "BTC binary options) are excluded. 'SERIAL TIMER' wallets that repeatedly bet near "
    "resolution across multiple long-duration markets are heavily escalated, especially "
    "if also profitable.\n\n"

    "**low_activity_large_bet** (severity 0.5-4.0): Flags large bets on thinly-traded "
    "markets (<$5k 24h volume) or where a single bet is >=50% of 24h volume. Thin "
    "orderbooks and wide spreads boost severity. Suppressed if bet is <5% of market "
    "liquidity. Short-lived markets (<6h) are excluded. Insider tip-offs on obscure "
    "markets are the concern here.\n\n"

    "**pre_event_volume_spike** (severity 1.0-4.0): Batch strategy. Flags markets where "
    "scan window volume is >=10x the normalized average AND >= $10k absolute. Uses "
    "historical volume baselines when available (multi-run). A sudden flood of money "
    "into a normally quiet market suggests coordinated informed trading.\n\n"

    "**wallet_clustering** (severity 5.0-8.0): Sybil detection. Traces wallet funding "
    "sources via Etherscan to find multiple wallets funded by the same address. "
    "Severity scales logarithmically with cluster size (2 wallets = 5.0, 4 = 6.0, "
    "8 = 7.0). Known Sybil funders from prior runs get +1.0 boost. This is a strong "
    "manipulation indicator — one actor splitting bets across wallets to avoid detection.\n\n"

    "**concentrated_one_sided** (severity 3.5-8.0): Flags when >=3 distinct wallets "
    "all bet the same direction on the same market outcome within the scan window, "
    "totaling >= $5k. Volume boosts at $50k+ and $100k+. Cross-referenced with "
    "wallet_clustering: if wallets in the cluster share a funder, severity jumps +1.5 "
    "with a Sybil flag. This catches coordinated betting rings.\n\n"

    "**price_impact** (severity 1.0-5.0): Detects significant price shifts. Three modes: "
    "(1) within-window shift >=15 percentage points, (2) breakout >=25pp beyond "
    "historical price range from prior runs, (3) rapid velocity (>=10pp in 5 minutes). "
    "Thin orderbooks boost severity. Large sudden price moves driven by specific trades "
    "suggest informed actors moving markets.\n\n"

    "**correlated_cross_market** (severity 1.5-4.0): Flags wallets betting across "
    "multiple markets within the same event (same eventSlug). Mixed directions across "
    "markets (e.g., buying 'resign' + selling 'win election') are more suspicious "
    "(severity 3.0) than consistent views (severity 1.5). Historical cross-run "
    "detection catches positioning over days/weeks. Serial cross-market traders "
    "(>=3 events) get escalated to 4.0.\n\n"

    "## How to evaluate\n\n"
    "INTERESTING alerts (keep for human review):\n"
    "- Multiple strong signals compounding (e.g., new wallet + high win rate + near resolution)\n"
    "- Sybil clusters (wallet_clustering) — almost always worth reviewing\n"
    "- New wallets that are also profitable or repeat offenders\n"
    "- Serial timers with profitability (timing + win_rate)\n"
    "- High composite scores (>=6.0) from diverse signal sources\n"
    "- Concentrated one-sided betting with shared funders\n"
    "- Volume spikes on markets with simultaneous price impact\n\n"

    "NOT interesting (discard):\n"
    "- A single weak signal in isolation (e.g., just low_activity severity <1.5)\n"
    "- Composite score <3.0 with no compelling signal combination\n"
    "- Large bets on highly liquid markets with no other flags (normal whale activity)\n"
    "- Consistent cross-market views with only 2 markets (severity 1.5 — very common)\n"
    "- Timing signals on markets resolving in minutes with no other supporting evidence\n"
    "- Low-edge win rate signals (barely above the 15% edge threshold)\n\n"

    "Evaluate the alert and decide: is this interesting enough for human review?"
)

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "interesting": {"type": "boolean"},
            "summary": {
                "type": "string",
                "description": "1-2 sentence explanation. If interesting, explain why. If not interesting, explain why it was discarded.",
            },
        },
        "required": ["interesting", "summary"],
        "additionalProperties": False,
    },
}


def _build_prompt(alert: dict) -> str:
    """Build a prompt describing the alert for the LLM to evaluate."""
    parts = [
        f"Market: {alert.get('market_title', 'Unknown')}",
        f"Alert type: {alert.get('alert_type', 'composite')}",
        f"Composite score: {alert.get('composite_score', 0):.1f}",
        f"Total USD: ${alert.get('total_usd', 0):,.2f}",
        f"Trade count: {alert.get('trade_count', 0)}",
    ]

    if alert.get("cluster_headline"):
        parts.append(f"Cluster: {alert['cluster_headline']}")

    if alert.get("wallet"):
        parts.append(f"Wallet: {alert['wallet']}")

    # Signals
    signals = alert.get("signals", [])
    if signals:
        parts.append("\nDetection signals:")
        for sig in signals:
            parts.append(f"  - [{sig['severity']:.1f}] {sig['strategy']}: {sig['headline']}")

    # Trades
    trades = alert.get("trades", [])
    if trades:
        parts.append(f"\nTrades ({len(trades)}):")
        for t in trades[:10]:  # cap at 10 to keep prompt short
            side = t.get("side", "?")
            outcome = t.get("outcome", "?")
            usd = t.get("usd_value", 0)
            price = t.get("price", 0)
            parts.append(f"  - ${usd:,.2f} {side} {outcome} @ {price:.2f}")

    return "\n".join(parts)


def evaluate_alert(alert: dict) -> tuple[bool, str]:
    """Call Claude to evaluate whether an alert is interesting.

    Returns (interesting, summary) — summary is always provided.
    """
    if not ANTHROPIC_API_KEY:
        return False, ""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    alert_text = _build_prompt(alert)

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": alert_text,
            }
        ],
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        output_config={"format": RESPONSE_SCHEMA},
    )

    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    if cache_read:
        print(f"[llm_filter] Cache hit: {cache_read} tokens read from cache", file=sys.stderr)
    elif cache_create:
        print(f"[llm_filter] Cache miss: {cache_create} tokens written to cache", file=sys.stderr)

    try:
        text = response.content[0].text
        result = json.loads(text)
        interesting = bool(result.get("interesting"))
        summary = result.get("summary", "")
        return interesting, summary
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"[llm_filter] WARNING: Failed to parse LLM response: {e}", file=sys.stderr)
        return True, "LLM evaluation inconclusive — kept for manual review."


def filter_alerts(alerts: list[dict]) -> list[dict]:
    """Filter a list of alert dicts through the LLM.

    Checks the local SQLite cache first — only calls the LLM for alerts
    that haven't been evaluated before. Both interesting and not-interesting
    verdicts are cached so discarded alerts are never re-evaluated.

    Returns only the alerts the LLM considers interesting, with an
    'llm_summary' field added to each.
    """
    if not ANTHROPIC_API_KEY:
        print("[llm_filter] No ANTHROPIC_API_KEY set — skipping LLM filter, pushing all alerts.")
        return alerts

    kept = []
    discarded = 0
    cached = 0

    for i, alert in enumerate(alerts, 1):
        title = alert.get("market_title", "?")
        score = alert.get("composite_score", 0)
        dedup_key = alert.get("dedup_key", "")

        # Check local cache first
        if dedup_key:
            cached_eval = get_llm_evaluation(dedup_key)
            if cached_eval is not None:
                if cached_eval["interesting"]:
                    alert["llm_summary"] = cached_eval["summary"]
                    kept.append(alert)
                else:
                    discarded += 1
                cached += 1
                continue

        print(f"  [{i}/{len(alerts)}] Evaluating: [{score:.1f}] {title}...", end=" ", flush=True)

        try:
            interesting, summary = evaluate_alert(alert)
        except Exception as e:
            print(f"ERROR ({e}) — keeping alert")
            alert["llm_summary"] = "LLM evaluation failed — kept for manual review."
            kept.append(alert)
            continue

        if interesting:
            print("INTERESTING")
            alert["llm_summary"] = summary
            kept.append(alert)
            if dedup_key:
                save_llm_evaluation(dedup_key, interesting=True, summary=summary)
        else:
            print(f"discarded — {summary}")
            discarded += 1
            if dedup_key:
                save_llm_evaluation(dedup_key, interesting=False, summary=summary)

    if cached:
        print(f"[llm_filter] {cached} alert(s) resolved from cache.")
    print(f"[llm_filter] Kept {len(kept)}, discarded {discarded} of {len(alerts)} alerts.")
    return kept
