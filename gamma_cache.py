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

# Tag ID that Polymarket uses for all sports markets.
SPORTS_TAG_ID = "1"

# Single shared cache: conditionId -> market dict
_market_cache: dict[str, dict] = {}

# Event tag cache: event_id (str) -> list of tag dicts (with id, label, slug)
_event_tags_cache: dict[str, list[dict]] = {}


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


def _get_event_id(market: dict) -> str | None:
    """Extract event ID from a market's nested events array."""
    events = market.get("events")
    if events and isinstance(events, list) and len(events) > 0:
        return str(events[0].get("id", ""))
    return None


def _fetch_event_tags(event_id: str) -> list[dict]:
    """Fetch tags for an event from the Gamma API.
    The nested event inside a market response doesn't include tags,
    so we fetch the event directly by ID.
    Returns list of tag dicts (each has 'id', 'label', 'slug')."""
    if event_id in _event_tags_cache:
        return _event_tags_cache[event_id]

    time.sleep(MARKET_LOOKUP_DELAY)
    try:
        resp = requests.get(
            f"{GAMMA_API}/events/{event_id}",
            timeout=10,
        )
        resp.raise_for_status()
        event = resp.json()
        tags = [t for t in event.get("tags", []) if isinstance(t, dict)]
        _event_tags_cache[event_id] = tags
        return tags
    except requests.RequestException as e:
        print(f"[WARN] Event tag lookup failed for event {event_id}: {e}", file=sys.stderr)
    return []


# Top-level category tags — these are broad categories used by Polymarket.
# The first matching tag label (by lowest ID = oldest/broadest) is used as
# the category.  More specific tags like "Premier League" are skipped.
_TOP_LEVEL_TAG_IDS = {
    "1",        # Sports
    "3",        # Politics
    "100639",   # Games
    "4",        # Crypto
    "6",        # Pop Culture
    "7",        # Business
    "8",        # Science
}


def get_market_category(condition_id: str) -> str | None:
    """Resolve the primary category for a market from its event tags.

    Looks up the market by conditionId, finds the parent event, fetches
    its tags, and returns the label of the first top-level category tag.
    Falls back to the first tag label if no top-level tag matches."""
    market = get_market_by_condition(condition_id)
    if not market:
        return None
    event_id = _get_event_id(market)
    if not event_id:
        return None
    tags = _fetch_event_tags(event_id)
    if not tags:
        return None

    # Prefer a known top-level category
    for tag in tags:
        if str(tag.get("id", "")) in _TOP_LEVEL_TAG_IDS:
            return tag.get("label")

    # Fall back to first tag
    return tags[0].get("label") if tags else None


def is_sport_market(market: dict) -> bool:
    """Check whether a market belongs to a sports event via Gamma API tags.

    Uses the event's tag list from the Gamma API — tag ID '1' is the
    canonical 'Sports' tag that Polymarket applies to all sports events.
    Results are cached per event ID.
    """
    event_id = _get_event_id(market)
    if not event_id:
        return False
    tags = _fetch_event_tags(event_id)
    return any(str(t.get("id", "")) == SPORTS_TAG_ID for t in tags)
