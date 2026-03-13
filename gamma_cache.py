"""
Shared Gamma API market cache used by multiple detection strategies.

Avoids duplicate API calls when several strategies need the same market
metadata for the same conditionId.
"""

from __future__ import annotations

import sys
import time

import requests

GAMMA_API = "https://gamma-api.polymarket.com"
MARKET_LOOKUP_DELAY = 0.15

# Single shared cache: conditionId -> market dict
_market_cache: dict[str, dict] = {}


def get_market_by_condition(condition_id: str) -> dict | None:
    """Fetch market metadata from Gamma API by conditionId.
    Results are cached so repeated calls across strategies are free."""
    if condition_id in _market_cache:
        return _market_cache[condition_id]

    time.sleep(MARKET_LOOKUP_DELAY)
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"condition_ids": condition_id},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
        if markets:
            _market_cache[condition_id] = markets[0]
            return markets[0]
    except requests.RequestException as e:
        print(f"[WARN] Market lookup failed for condition {condition_id}: {e}", file=sys.stderr)
    return None
