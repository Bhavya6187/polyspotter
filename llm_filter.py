"""
LLM filter — passes each alert through GPT to decide if the trade is
worth surfacing (copy-worthy, informed edge, or notable pattern).

Uses a local SQLite cache (llm_evaluations table in polybot.db) to avoid
re-evaluating the same alert across runs.

Returns a short explanation string if interesting, or None to discard.
"""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

from db import get_llm_evaluation, get_wallet_market_positions, get_wallet_pnl_summary, save_llm_evaluation
from gamma_cache import get_market_by_condition, invalidate_market

load_dotenv()

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
MODEL = os.environ.get("AZURE_OPENAI_MODEL", "")
PROMPT_LOG_FILE = Path(__file__).parent / "llm_prompts.jsonl"
FAILURE_LOG_FILE = Path(__file__).parent / "llm_failures.jsonl"

# Serializes appends to the JSONL log files. Large prompt payloads exceed
# PIPE_BUF, so concurrent appends from worker threads can interleave bytes
# and corrupt lines without this lock.
_LOG_LOCK = threading.Lock()


def _log_prompt(messages: list[dict], model: str, cache_key: str) -> None:
    """Append a prompt to the JSONL log file for later analysis."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": model,
        "cache_key": cache_key,
        "messages": messages,
    }
    with _LOG_LOCK, open(PROMPT_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _log_failure(
    cache_key: str,
    alert_text: str,
    finish_reason: str | None,
    raw_text: str | None,
    usage: dict,
    error: str,
) -> None:
    """Dump a failed LLM evaluation for offline debugging.

    Captures the prompt, token-usage breakdown (reasoning vs output), raw
    response text, and the failure mode so we can inspect patterns later.
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": MODEL,
        "cache_key": cache_key,
        "error": error,
        "finish_reason": finish_reason,
        "usage": usage,
        "raw_text": raw_text,
        "alert_text": alert_text,
    }
    with _LOG_LOCK, open(FAILURE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


SYSTEM_PROMPT = (
    "You are a Polymarket trade analyst. You receive alerts about notable trades "
    "flagged by 9 automated detection strategies. Your job: decide if this alert "
    "represents a genuinely interesting trade worth surfacing — something a user "
    "would want to copy-trade, follow, or study.\n\n"

    "## Your purpose\n"
    "Polybot surfaces interesting trades on Polymarket. 'Interesting' means the "
    "trader appears to have an edge — whether that's a sharp sports bettor with "
    "a proven track record, an informed trader positioning ahead of news, a "
    "whale making a confident concentrated bet, or coordinated wallets moving "
    "together on a thesis. The goal is NOT to catch bad actors — it's to find "
    "trades worth paying attention to and potentially copying.\n\n"

    "## Alert structure\n"
    "Each alert has a composite_score (sum of signal severities), total USD value, "
    "trade count, and a list of detection signals. Alerts are either:\n"
    "- **individual**: a single wallet's trades on a market, with per-trade signals\n"
    "- **cluster**: multiple wallets betting the same direction on a market (from "
    "concentrated_one_sided), with shared + per-trade signals\n\n"

    "Each alert also includes **market context** from the Gamma API: a description "
    "with resolution criteria, category, current odds, order book state (bid/ask/spread), "
    "volume (total and 24h), liquidity depth, price momentum (1d/1w changes), and "
    "the scheduled end date. Use this context to assess:\n"
    "- Whether the market topic makes informed trading plausible (politics, sports, "
    "crypto events vs. trivial/meme markets)\n"
    "- How thin/thick the market is (low liquidity + large bet = higher conviction signal)\n"
    "- Whether recent price movement corroborates the detected signals\n"
    "- How close the market is to resolution (bets near expiry with edge are stronger)\n"
    "- Whether the trader is buying at a price that implies they see significant mispricing\n\n"

    "## Detection strategies and what their signals mean\n\n"

    "**win_rate_tracking** (severity 1.0-6.0): Tracks wallet P&L history. Fires when "
    "a wallet has >=75% win rate on 10+ resolved bets AND beats implied odds by 15%+ "
    "(edge-adjusted). A wallet winning 90% at avg odds of 40% has extraordinary edge. "
    "A wallet winning 90% on 90% favorites is unremarkable. Higher severity = larger "
    "edge and confirmed profitability. These are sharp bettors worth following.\n\n"

    "**new_wallet_large_bet** (severity 1.0-7.0): Flags wallets <30 days old making "
    "large bets ($3k+). Severity scales with wallet youth (<7d = 3.5, <14d = 2.5, "
    "<30d = 1.5). Repeat bettors get escalated (+0.5 per flag, up to +2.0). "
    "Cross-referenced with P&L: a new wallet that already has many positions or "
    "is profitable gets boosted. New wallets betting big with early profitability "
    "suggest informed conviction.\n\n"

    "**timing_relative_resolution** (severity 1.0-8.0): Flags bets placed within 60 "
    "minutes of a market's resolution time. Severity scales continuously (5.0 at 0min, "
    "~2.5 at 10min, ~1.0 at 60min). Short-duration markets (<2h lifespan like 5-min "
    "BTC binary options) are excluded. 'SERIAL TIMER' wallets that repeatedly bet near "
    "resolution across multiple long-duration markets are heavily escalated, especially "
    "if also profitable — they may have a real-time information edge.\n\n"

    "**low_activity_large_bet** (severity 0.5-4.0): Flags large bets on thinly-traded "
    "markets (<$5k 24h volume) or where a single bet is >=50% of 24h volume. Thin "
    "orderbooks and wide spreads boost severity. Suppressed if bet is <5% of market "
    "liquidity. Short-lived markets (<6h) are excluded. Large confident bets on "
    "quiet markets suggest the trader knows something others don't.\n\n"

    "**pre_event_volume_spike** (severity 1.0-4.0): Batch strategy. Flags markets where "
    "scan window volume is >=10x the normalized average AND >= $10k absolute. Uses "
    "historical volume baselines when available (multi-run). A sudden flood of money "
    "into a normally quiet market suggests informed traders are positioning.\n\n"

    "**wallet_clustering** (severity 5.0-8.0): Linked-wallet detection. Traces wallet "
    "funding sources via Etherscan to find multiple wallets funded by the same address. "
    "Severity scales logarithmically with cluster size (2 wallets = 5.0, 4 = 6.0, "
    "8 = 7.0). Known linked funders from prior runs get +1.0 boost. Linked wallets "
    "betting together signal high conviction from a single actor deploying "
    "significant capital.\n\n"

    "**concentrated_one_sided** (severity 3.5-8.0): Flags when >=3 distinct wallets "
    "all bet the same direction on the same market outcome within the scan window, "
    "totaling >= $5k. Volume boosts at $50k+ and $100k+. Cross-referenced with "
    "wallet_clustering: if wallets in the cluster share a funder, severity jumps +1.5. "
    "Coordinated one-sided flow is a strong directional signal worth following.\n\n"

    "**price_impact** (severity 1.0-5.0): Detects significant price shifts. Three modes: "
    "(1) within-window shift >=15 percentage points, (2) breakout >=25pp beyond "
    "historical price range from prior runs, (3) rapid velocity (>=10pp in 5 minutes). "
    "Thin orderbooks boost severity. Large price moves driven by specific trades "
    "suggest informed actors moving the market with conviction.\n\n"

    "**correlated_cross_market** (severity 1.5-4.0): Flags wallets betting across "
    "multiple markets within the same event (same eventSlug). Mixed directions across "
    "markets (e.g., buying 'resign' + selling 'win election') suggest a hedged thesis "
    "(severity 3.0); consistent views suggest a directional thesis (severity 1.5). "
    "Historical cross-run detection catches positioning over days/weeks. Serial "
    "cross-market traders (>=3 events) get escalated to 4.0.\n\n"

    "## Position history context\n\n"
    "Alerts may include 'Prior positions on this market' showing the wallet's existing "
    "positions. Use this to distinguish:\n"
    "- **Profit-taking**: wallet already holds shares and is selling near max value — "
    "this is routine position management, NOT a new contrarian bet. Heavily discount "
    "the signal.\n"
    "- **New position**: no prior position on this market — the trade represents fresh "
    "conviction.\n"
    "- **Adding to position**: wallet already holds shares in the same direction and is "
    "sizing up — this signals increased conviction.\n\n"

    "## How to evaluate\n\n"
    "INTERESTING (surface to users):\n"
    "- Sharp bettors: wallets with proven win rates and meaningful edge, especially on "
    "sports, politics, or crypto — these are copy-trade candidates\n"
    "- Sharp wallet override: if any wallet in the alert has >=75% win rate on 10+ "
    "resolved bets AND meaningfully positive lifetime P&L, surface the alert even when "
    "the firing detection signal is weak (e.g. low_activity 1.0, price_impact 1.5, "
    "single cross-market severity 2.0). The wallet IS the signal — copy-trading their "
    "bets is the value, not the strategy that flagged it. A 10-bet sample is already "
    "gated by the win_rate_tracking strategy; do not invent a higher threshold.\n"
    "- Informed new wallets: new wallets betting big with early profitability (conviction + edge)\n"
    "- Coordinated flow: multiple wallets or linked wallets all positioning the same "
    "direction on a market (strong directional signal)\n"
    "- Volume surges combined with price movement on a market (momentum)\n"
    "- Serial timers with profitability — wallets that consistently bet near resolution "
    "and win (real-time information edge)\n"
    "- High composite scores (>=6.0) from diverse signal sources\n"
    "- Large confident bets on quiet markets (someone knows something)\n\n"

    "NOT interesting (discard):\n"
    "- A single weak signal in isolation (e.g., just low_activity severity <1.5)\n"
    "- Composite score <3.0 with no compelling signal combination\n"
    "- Large bets on highly liquid markets where the ONLY signal is bet size AND the "
    "wallet has no proven edge (no win_rate_tracking hit, no cluster membership, no "
    "timing pattern). If a sharp wallet (per the override above) is buying, do NOT "
    "discard purely on market liquidity.\n"
    "- Consistent cross-market views with only 2 markets (severity 1.5 — very common)\n"
    "- Timing signals on markets resolving in minutes with no other supporting evidence\n"
    "- Low-edge win rate signals (barely above the 15% edge threshold)\n"
    "- Linked wallets (wallet_clustering) as the ONLY signal with just 2 wallets and "
    "no other corroborating evidence — common for users with multiple accounts\n\n"

    "## Output format\n\n"
    "You MUST return JSON with these fields:\n"
    "- interesting (bool): whether to surface this alert\n"
    "- summary (string): 1 sentence reason (used internally for filtering log)\n"
    "- bullets (array of 2-3 strings): plain-English insights for the end user. "
    "Each bullet should be one short sentence. Lead with the most compelling "
    "reason to copy this trade.\n"
    "- headline (string): ultra-short label (under 10 words) describing the bettor or "
    "pattern — used as a compact row label in the UI. Focus on WHO is betting and WHY "
    "they stand out (e.g. '19-wallet funded cluster', 'Serial timer with 91%% win rate', "
    "'New whale scaling into NO'). Do not repeat the market name.\n"
    "- copy_action (object or null): what the user should do to copy the trade. "
    "Set to JSON null ONLY for multi-outcome SELL trades where no defensible single "
    "outcome to BUY exists. Otherwise an object with fields:\n"
    "  - outcome (string, e.g. 'Utah' or 'Yes')\n"
    "  - side (string, ALWAYS 'BUY')\n"
    "  - entry_price (number, the effective entry price on 0-1 scale)\n"
    "  - max_price (number, suggested ceiling to still enter). Compute as "
    "entry_price + 0.10 — i.e. ten PERCENTAGE POINTS above entry, additive, NOT "
    "10%% relative. Constraints: max_price - entry_price >= 0.05 and max_price <= 0.95. "
    "If entry_price >= 0.90, set max_price = 0.95. Examples: entry 0.16 → max 0.26; "
    "entry 0.41 → max 0.51; entry 0.65 → max 0.75; entry 0.88 → max 0.95.\n"
    "IMPORTANT: side must ALWAYS be 'BUY'. Users can only buy outcomes, not sell "
    "shares they don't hold. Convert sell trades to equivalent buys:\n"
    "  - Binary markets (Yes/No): Sell Yes at X¢ → BUY No at (1-X)¢. "
    "Sell No at X¢ → BUY Yes at (1-X)¢.\n"
    "  - Multi-outcome markets: If the original trade is a SELL with no clear "
    "single outcome to BUY, set copy_action to null (the JSON null literal, not "
    "an empty object).\n\n"

    "## Bullet style rules\n\n"
    "- Use plain English anyone can understand. Say 'a bettor who wins 90%% of "
    "their bets' not '90%% win rate edge-adjusted'.\n"
    "- Lead with WHY this trader is worth copying: track record, conviction, "
    "pattern, timing.\n"
    "- Include 1-2 key stats per bullet (win rate, profit, cluster size, "
    "timing).\n"
    "- Never start with 'Interesting' or similar preamble.\n"
    "- Never address the reader directly.\n"
    "- Do NOT use words like 'suspicious', 'manipulation', or 'insider trading'.\n\n"

    "Good bullet examples:\n"
    "- 'This bettor wins 87%% of their trades and is up $1.2M lifetime'\n"
    "- '14 linked wallets are all betting the same way on this market'\n"
    "- 'Placed right before resolution — this wallet has a pattern of "
    "last-minute bets that hit'\n"
    "- 'Entry at 41¢ implies they see this as a ~2.4x opportunity'"
)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "alert_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "interesting": {"type": "boolean"},
            "summary": {
                "type": "string",
                "description": "1 sentence internal summary for filtering log.",
            },
            "headline": {
                "type": "string",
                "description": "Ultra-short label (under 10 words) describing the bettor or pattern for compact UI display.",
            },
            "bullets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 short plain-English bullet points explaining why this trade is interesting. Empty array if not interesting.",
            },
            "copy_action": {
                "type": ["object", "null"],
                "properties": {
                    "outcome": {
                        "type": "string",
                        "description": "The outcome to bet on, e.g. 'Utah' or 'Yes'.",
                    },
                    "side": {
                        "type": "string",
                        "description": "Always 'BUY'. Sells must be converted to equivalent buys.",
                    },
                    "entry_price": {
                        "type": "number",
                        "description": "The trader's entry price (0-1 scale).",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Ceiling to still enter. Compute as entry_price + 0.10 (ten percentage points, additive — NOT 10% relative). Must satisfy max_price - entry_price >= 0.05 and max_price <= 0.95. If entry_price >= 0.90, set max_price = 0.95. Null entire copy_action for multi-outcome SELLs with no defensible BUY.",
                    },
                },
                "required": ["outcome", "side", "entry_price", "max_price"],
                "additionalProperties": False,
            },
        },
        "required": ["interesting", "summary", "headline", "bullets", "copy_action"],
        "additionalProperties": False,
    },
}


def _format_trade_line(t: dict, current_prices: dict[str, float]) -> str:
    """Format a single trade line with timestamp and entry-vs-current price."""
    side = t.get("side", "?")
    outcome = t.get("outcome", "?")
    usd = t.get("usd_value", 0)
    price = t.get("price", 0)
    wallet = t.get("wallet", "")
    short_wallet = f"{wallet[:8]}...{wallet[-6:]}" if len(wallet) > 14 else wallet

    # Timestamp
    ts_str = ""
    ts_raw = t.get("trade_timestamp")
    if ts_raw:
        try:
            dt = datetime.fromisoformat(ts_raw)
            ts_str = f" at {dt.strftime('%H:%M:%S UTC')}"
        except (ValueError, TypeError):
            pass

    # Entry vs current price comparison
    price_ctx = ""
    cur = current_prices.get(outcome)
    if cur is not None and price > 0:
        diff = cur - price
        if abs(diff) >= 0.02:  # only show if meaningful (2%+)
            price_ctx = f" (entry {price:.0%}, now {cur:.0%})"

    return f"  - ${usd:,.2f} {side} {outcome} @ {price:.2f}{ts_str} [{short_wallet}]{price_ctx}"


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

    # Market metadata from Gamma API
    # Invalidate cache to get fresh prices — the cached entry may predate
    # the trades in this alert, causing the LLM to see stale prices.
    condition_id = alert.get("condition_id")
    current_prices: dict[str, float] = {}  # outcome -> current price (reused for trade lines)
    if condition_id:
        invalidate_market(condition_id)
        mkt = get_market_by_condition(condition_id)
        if mkt:
            parts.append("\nMarket context:")
            if mkt.get("description"):
                desc = mkt["description"]
                # Truncate long descriptions to keep prompt reasonable
                if len(desc) > 500:
                    desc = desc[:500] + "..."
                parts.append(f"  Description: {desc}")
            if mkt.get("category"):
                parts.append(f"  Category: {mkt['category']}")
            if mkt.get("endDate"):
                parts.append(f"  End date: {mkt['endDate']}")
            # Current prices (implied probabilities)
            try:
                prices = json.loads(mkt.get("outcomePrices", "[]"))
                outcomes = json.loads(mkt.get("outcomes", "[]"))
                if prices and outcomes:
                    price_strs = [f"{o}: {float(p):.0%}" for o, p in zip(outcomes, prices)]
                    parts.append(f"  Current odds: {', '.join(price_strs)}")
                    for o, p in zip(outcomes, prices):
                        current_prices[o] = float(p)
            except (json.JSONDecodeError, ValueError):
                pass
            # Order book state
            spread = mkt.get("spread")
            if spread is not None:
                best_bid = mkt.get("bestBid")
                best_ask = mkt.get("bestAsk")
                if best_bid is not None and best_ask is not None:
                    parts.append(f"  Best bid/ask: {best_bid:.2f} / {best_ask:.2f} (spread: {spread:.2f})")
                else:
                    parts.append(f"  Spread: {spread:.2f}")
            # Volume & liquidity
            vol_total = mkt.get("volumeNum")
            vol_24h = mkt.get("volume24hr")
            liquidity = mkt.get("liquidityNum")
            vol_parts = []
            if vol_total is not None:
                vol_parts.append(f"total ${vol_total:,.0f}")
            if vol_24h is not None:
                vol_parts.append(f"24h ${vol_24h:,.0f}")
            if vol_parts:
                parts.append(f"  Volume: {', '.join(vol_parts)}")
            if liquidity is not None:
                parts.append(f"  Liquidity: ${liquidity:,.0f}")
            # Price momentum
            momentum = []
            day_change = mkt.get("oneDayPriceChange")
            week_change = mkt.get("oneWeekPriceChange")
            if day_change is not None and day_change != 0:
                momentum.append(f"1d: {day_change:+.1%}")
            if week_change is not None and week_change != 0:
                momentum.append(f"1w: {week_change:+.1%}")
            if momentum:
                parts.append(f"  Price change: {', '.join(momentum)}")

    # Signals
    signals = alert.get("signals", [])
    if signals:
        parts.append("\nDetection signals:")
        for sig in signals:
            parts.append(f"  - [{sig['severity']:.1f}] {sig['strategy']}: {sig['headline']}")

    # Trades — with timestamps and entry-vs-current comparison
    trades = alert.get("trades", [])
    if trades:
        # For cluster alerts, group trades by direction (outcome/side)
        if alert.get("alert_type") == "cluster" and len(trades) > 1:
            direction_groups: dict[str, list[dict]] = defaultdict(list)
            for t in trades:
                direction = f"{t.get('outcome', '?')}/{t.get('side', '?')}"
                direction_groups[direction].append(t)

            parts.append(f"\nTrades ({len(trades)}):")
            for direction, group in sorted(direction_groups.items(), key=lambda x: -len(x[1])):
                group_usd = sum(t.get("usd_value", 0) for t in group)
                parts.append(f"  {direction} — {len(group)} trades, ${group_usd:,.2f} total:")
                for t in sorted(group, key=lambda x: -x.get("usd_value", 0))[:8]:
                    parts.append(_format_trade_line(t, current_prices))
        else:
            parts.append(f"\nTrades ({len(trades)}):")
            for t in trades[:10]:  # cap at 10 to keep prompt short
                parts.append(_format_trade_line(t, current_prices))

    # Wallet P&L profiles — collect unique wallets from the alert
    wallets: set[str] = set()
    if alert.get("wallet"):
        wallets.add(alert["wallet"].lower())
    for t in alert.get("trades", []):
        w = t.get("wallet", "")
        if w:
            wallets.add(w.lower())

    if wallets:
        profile_lines = []
        for w in sorted(wallets)[:10]:  # cap to keep prompt reasonable
            pnl = get_wallet_pnl_summary(w)
            closed = pnl.get("closed_positions", 0)
            if closed == 0:
                profile_lines.append(f"  - {w[:8]}...{w[-6:]}: no resolved positions")
                continue
            wins = pnl.get("wins", 0)
            losses = pnl.get("losses", 0)
            win_rate = wins / closed
            total_pnl = pnl.get("total_pnl") or 0
            total_invested = pnl.get("total_invested") or 0
            avg_win_price = pnl.get("avg_win_price")
            line = (
                f"  - {w[:8]}...{w[-6:]}: {win_rate:.0%} win rate "
                f"({wins}W/{losses}L on {closed} resolved), "
                f"P&L ${total_pnl:+,.0f} on ${total_invested:,.0f} invested"
            )
            if avg_win_price is not None:
                line += f", avg win price {avg_win_price:.2f}"
            profile_lines.append(line)

        if profile_lines:
            parts.append("\nWallet profiles:")
            parts.extend(profile_lines)

    # Prior positions on THIS market — helps distinguish profit-taking from new bets
    if condition_id and wallets:
        position_lines = []
        for w in sorted(wallets)[:10]:
            positions = get_wallet_market_positions(w, condition_id)
            if not positions:
                continue
            short = f"{w[:8]}...{w[-6:]}"
            for pos in positions:
                outcome = pos["outcome"] or "?"
                avg_price = pos["avg_price"] or 0
                total = pos["total_bought"] or 0
                ptype = pos["position_type"] or "?"
                line = f"  - {short}: {ptype} {outcome} position, avg entry {avg_price:.2f}, ${total:,.0f} invested"
                if pos["cur_price"] is not None:
                    line += f", current price {pos['cur_price']:.2f}"
                position_lines.append(line)
        if position_lines:
            parts.append("\nPrior positions on this market:")
            parts.extend(position_lines)

    return "\n".join(parts)


def evaluate_alert(alert: dict, alert_text: str | None = None) -> dict:
    """Call GPT to evaluate whether an alert is interesting.

    If `alert_text` is provided, it is used directly (skipping `_build_prompt`).
    This lets callers build the prompt on a thread that owns the SQLite
    connection while running the LLM call from a worker thread.

    Returns a dict with keys: interesting, summary, bullets, copy_action.
    """
    if not AZURE_OPENAI_API_KEY:
        return {"interesting": False, "summary": "", "bullets": [], "copy_action": {}}

    client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    if alert_text is None:
        alert_text = _build_prompt(alert)

    # Logged in chat-style for compatibility with the existing JSONL log
    # consumers; the API itself receives instructions + input separately.
    messages = [
        {"role": "developer", "content": SYSTEM_PROMPT},
        {"role": "user", "content": alert_text},
    ]

    cache_key = alert.get("llm_cache_key") or alert.get("dedup_key", "")
    _log_prompt(messages, MODEL, cache_key)

    response = client.responses.create(
        model=MODEL,
        max_output_tokens=16000,
        instructions=SYSTEM_PROMPT,
        input=alert_text,
        text={"format": RESPONSE_FORMAT},
    )

    usage = response.usage
    cached_tokens = 0
    if usage and usage.input_tokens_details:
        cached_tokens = getattr(usage.input_tokens_details, "cached_tokens", 0) or 0
    prompt_tokens = usage.input_tokens if usage else 0
    completion_tokens = usage.output_tokens if usage else 0
    reasoning_tokens = 0
    if usage and getattr(usage, "output_tokens_details", None):
        reasoning_tokens = getattr(usage.output_tokens_details, "reasoning_tokens", 0) or 0

    if cached_tokens:
        print(f"[llm_filter] Cache hit: {cached_tokens}/{prompt_tokens} prompt tokens from cache")
    else:
        print(f"[llm_filter] Cache miss: {prompt_tokens} prompt tokens (none cached)")

    usage_dict = {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
    }

    inconclusive = {
        "interesting": False,
        "summary": "LLM evaluation inconclusive — discarded by default.",
        "bullets": [],
        "copy_action": {},
    }

    text = response.output_text
    status = response.status
    incomplete_reason = (
        response.incomplete_details.reason if response.incomplete_details else None
    )

    if status == "incomplete" or not text:
        print(
            f"[llm_filter] WARNING: empty response (status={status}, "
            f"incomplete_reason={incomplete_reason}, "
            f"completion_tokens={completion_tokens}, reasoning_tokens={reasoning_tokens}) — "
            f"likely hit max_output_tokens"
        )
        _log_failure(
            cache_key, alert_text, incomplete_reason or status, text, usage_dict,
            error="empty_or_truncated",
        )
        return inconclusive

    try:
        result = json.loads(text)
        return {
            "interesting": bool(result.get("interesting")),
            "summary": result.get("summary", ""),
            "headline": result.get("headline"),
            "bullets": result.get("bullets", []),
            "copy_action": result.get("copy_action") or {},
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[llm_filter] WARNING: Failed to parse LLM response: {e}")
        _log_failure(cache_key, alert_text, finish_reason, text, usage_dict, error=f"parse_error: {e}")
        return inconclusive


LLM_PARALLELISM = 5


def filter_alerts(alerts: list[dict]) -> list[dict]:
    """Filter a list of alert dicts through the LLM.

    Checks the local SQLite cache first — only calls the LLM for alerts
    that haven't been evaluated before. Both interesting and not-interesting
    verdicts are cached so discarded alerts are never re-evaluated.

    Runs in four phases:
      1. cache lookups for every alert (sequential local SQLite reads),
      2. parallel LLM calls for cache misses (ThreadPoolExecutor, LLM_PARALLELISM workers),
      3. assembly of the kept list in original input order on the main thread,
      4. cache writes flushed sequentially at the end.

    Returns only the alerts the LLM considers interesting, with an
    'llm_summary' field added to each.
    """
    if not AZURE_OPENAI_API_KEY:
        print("[llm_filter] No AZURE_OPENAI_API_KEY set — skipping LLM filter, pushing all alerts.")
        return alerts

    total = len(alerts)

    # Phase 1: cache lookups. Use content-sensitive llm_cache_key when
    # available (clusters include trade_count + score so the LLM re-evaluates
    # when the cluster grows). Falls back to dedup_key for non-cluster alerts.
    cache_keys: list[str] = [
        a.get("llm_cache_key") or a.get("dedup_key", "") for a in alerts
    ]
    cached_evals: list[dict | None] = [
        get_llm_evaluation(k) if k else None for k in cache_keys
    ]

    # Phase 2: parallel LLM calls for the cache misses.
    # Build prompts up front on the main thread — `_build_prompt` reads from
    # SQLite (wallet PnL, positions), and the connection is bound to the
    # thread that opened it. Workers only do the OpenAI call.
    miss_indices = [i for i, ce in enumerate(cached_evals) if ce is None]
    prebuilt_prompts: dict[int, str] = {idx: _build_prompt(alerts[idx]) for idx in miss_indices}

    def _eval(idx: int) -> tuple[int, dict | None, Exception | None]:
        try:
            return (idx, evaluate_alert(alerts[idx], prebuilt_prompts[idx]), None)
        except Exception as e:
            return (idx, None, e)

    llm_results: dict[int, tuple[dict | None, Exception | None]] = {}
    if miss_indices:
        with ThreadPoolExecutor(max_workers=LLM_PARALLELISM) as executor:
            for idx, result, error in executor.map(_eval, miss_indices):
                llm_results[idx] = (result, error)

    # Phase 3: assemble kept list in original order on the main thread,
    # collect pending cache writes.
    kept: list[dict] = []
    discarded = 0
    cached = 0
    pending_saves: list[tuple[str, bool, str]] = []

    for i, alert in enumerate(alerts):
        title = alert.get("market_title", "?")
        score = alert.get("composite_score", 0)
        prefix = f"  [{i + 1}/{total}] Evaluating: [{score:.1f}] {title}..."
        cache_key = cache_keys[i]
        cached_eval = cached_evals[i]

        if cached_eval is not None:
            cached += 1
            if cached_eval["interesting"]:
                alert["llm_summary"] = cached_eval["summary"]
                try:
                    extra = json.loads(cached_eval["summary"])
                    alert["llm_summary"] = extra.get("summary", cached_eval["summary"])
                    alert["llm_headline"] = extra.get("headline")
                    alert["llm_bullets"] = extra.get("bullets", [])
                    alert["llm_copy_action"] = extra.get("copy_action") or {}
                except (json.JSONDecodeError, TypeError):
                    alert["llm_bullets"] = []
                    alert["llm_copy_action"] = {}
                kept.append(alert)
            else:
                discarded += 1
            continue

        result, error = llm_results[i]
        if error is not None:
            print(f"{prefix} ERROR ({error}) — discarding alert")
            discarded += 1
            continue

        interesting = result["interesting"]
        summary = result["summary"]
        verdict = "INTERESTING" if interesting else "DISCARDED"
        print(f"{prefix} {verdict}\n    Model: {summary}")

        if interesting:
            alert["llm_summary"] = summary
            alert["llm_headline"] = result.get("headline")
            alert["llm_bullets"] = result.get("bullets", [])
            alert["llm_copy_action"] = result.get("copy_action") or {}
            kept.append(alert)
            if cache_key:
                cache_data = json.dumps({
                    "summary": summary,
                    "headline": result.get("headline"),
                    "bullets": result.get("bullets", []),
                    "copy_action": result.get("copy_action", {}),
                })
                pending_saves.append((cache_key, True, cache_data))
        else:
            discarded += 1
            if cache_key:
                pending_saves.append((cache_key, False, summary))

    # Phase 4: flush cache writes.
    for cache_key, interesting, summary in pending_saves:
        save_llm_evaluation(cache_key, interesting=interesting, summary=summary)

    if cached:
        print(f"[llm_filter] {cached} alert(s) resolved from cache.")
    print(f"[llm_filter] Kept {len(kept)}, discarded {discarded} of {total} alerts.")
    return kept
