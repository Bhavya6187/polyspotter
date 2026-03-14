"""Quick debug script to test the LLM filter with a mock alert."""

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

from llm_filter import SYSTEM_PROMPT, RESPONSE_SCHEMA, _build_prompt

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

print("=== Calling Claude (claude-haiku-4-5) with output_config ===")
response = client.messages.create(
    model="claude-sonnet-4-6",
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

print(f"Stop reason: {response.stop_reason}")
print(f"Content blocks: {len(response.content)}")
for i, block in enumerate(response.content):
    print(f"  Block {i}: type={block.type}")
    if hasattr(block, "text"):
        print(f"  Text: '{block.text}'")

print()
if response.content and hasattr(response.content[0], "text"):
    text = response.content[0].text
    print(f"=== Raw text (len={len(text)}) ===")
    print(repr(text))
    try:
        parsed = json.loads(text)
        print(f"\n=== Parsed JSON ===")
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError as e:
        print(f"\n=== JSON parse error: {e} ===")
