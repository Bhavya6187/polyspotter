"""Debug script to test LLM filter caching (both API prompt cache and SQLite cache)."""

import json
import os
import sys

from openai import OpenAI
from dotenv import load_dotenv

from llm_filter import SYSTEM_PROMPT, RESPONSE_SCHEMA, _build_prompt, MODEL
from db import get_llm_evaluation, save_llm_evaluation

load_dotenv()

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
if not AZURE_OPENAI_API_KEY:
    print("ERROR: AZURE_OPENAI_API_KEY not set")
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

client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)


def call_llm(prompt, label):
    """Make an API call and print cache token usage."""
    print(f"=== {label} ===")
    response = client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=300,
        messages=[
            {"role": "developer", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format=RESPONSE_SCHEMA,
    )

    usage = response.usage
    cached_tokens = 0
    if usage and usage.prompt_tokens_details:
        cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0

    print(f"  Prompt tokens:     {prompt_tokens}")
    print(f"  Completion tokens: {completion_tokens}")
    print(f"  Cached tokens:     {cached_tokens}")

    if cached_tokens:
        print(f"  -> PROMPT CACHE HIT ({cached_tokens}/{prompt_tokens} tokens from cache)")
    else:
        print(f"  -> NO CACHE HIT (0/{prompt_tokens} tokens cached)")

    text = response.choices[0].message.content
    result = json.loads(text)
    print(f"  Result: interesting={result['interesting']}, summary={result['summary']}")
    print()
    return result


# --- Test 1: OpenAI API prompt caching ---
print("=" * 60)
print("TEST 1: OpenAI API prompt caching (developer message)")
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
