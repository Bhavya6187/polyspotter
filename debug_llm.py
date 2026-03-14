"""Debug script to test LLM filter caching (both API prompt cache and SQLite cache)."""

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

from llm_filter import SYSTEM_PROMPT, RESPONSE_SCHEMA, _build_prompt, MODEL
from db import get_llm_evaluation, save_llm_evaluation

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set")
    sys.exit(1)

mock_alert = {
    "market_title": "Will Bitcoin exceed $100k by end of March 2026?",
    "alert_type": "individual",
    "composite_score": 7.5,
    "total_usd": 15000.00,
    "trade_count": 3,
    "wallet": "0xabc123fake",
    "dedup_key": "debug-test",
    "signals": [
        {"severity": 3.5, "strategy": "new_wallet_large_bet", "headline": "Wallet <7d old, $15k bet"},
        {"severity": 4.0, "strategy": "win_rate_tracking", "headline": "85% win rate on 12 bets, edge +22%"},
    ],
    "trades": [
        {"side": "BUY", "outcome": "Yes", "usd_value": 5000, "price": 0.42},
        {"side": "BUY", "outcome": "Yes", "usd_value": 5000, "price": 0.43},
        {"side": "BUY", "outcome": "Yes", "usd_value": 5000, "price": 0.44},
    ],
}

prompt = _build_prompt(mock_alert)
print("=== PROMPT ===")
print(prompt)
print()

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_llm(prompt, label):
    """Make an API call and print cache token usage."""
    print(f"=== {label} ===")
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
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
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0

    print(f"  Input tokens:  {input_tokens}")
    print(f"  Output tokens: {output_tokens}")
    print(f"  Cache create:  {cache_create}")
    print(f"  Cache read:    {cache_read}")

    if cache_read:
        print(f"  -> PROMPT CACHE HIT ({cache_read} tokens from cache)")
    elif cache_create:
        print(f"  -> PROMPT CACHE MISS ({cache_create} tokens written to cache)")
    else:
        print(f"  -> NO CACHE ACTIVITY (tokens below minimum for caching?)")

    text = response.content[0].text
    result = json.loads(text)
    print(f"  Result: interesting={result['interesting']}, summary={result['summary']}")
    print()
    return result


# --- Test 1: Anthropic API prompt caching ---
print("=" * 60)
print("TEST 1: Anthropic API prompt caching (system prompt)")
print("  Two back-to-back calls — second should get a cache hit")
print("=" * 60)
print()

result1 = call_llm(prompt, "Call 1 (expect cache miss / cache create)")
result2 = call_llm(prompt, "Call 2 (expect cache hit)")

# --- Test 2: SQLite cache ---
print("=" * 60)
print("TEST 2: SQLite cache (llm_evaluations table)")
print("=" * 60)
print()

dedup_key = "debug-test-cache-check"

# Check if already cached
cached = get_llm_evaluation(dedup_key)
print(f"  Before save: cached={cached}")

# Save
save_llm_evaluation(dedup_key, interesting=True, summary="test cache entry")
cached = get_llm_evaluation(dedup_key)
print(f"  After save:  cached={cached}")

if cached and cached["interesting"] and cached["summary"] == "test cache entry":
    print("  -> SQLite CACHE WORKING")
else:
    print("  -> SQLite CACHE BROKEN")
