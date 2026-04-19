"""
Tests for backend/twitter_bot.py.

Uses injected fakes for the HTTP client, LLM client, Twitter client, and DB
connection. No real network or DB calls.

Run: cd backend && pytest test_twitter_bot.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# The bot reads env vars at import time for config — set harmless defaults.
import os
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nope")
os.environ.setdefault("POLYSPOTTER_API_URL", "https://api.example.test")

import twitter_bot as tb


# ------------------------------------------------------------------ fixtures --

def _alert(**overrides):
    """Build an AlertOut-shaped dict with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": 1,
        "composite_score": 8.0,
        "market_title": "Will X happen?",
        "condition_id": "0xcond1",
        "wallet": "0xwallet1",
        "total_usd": 25_000.0,
        "trade_count": 1,
        "llm_headline": "Whale loads up on X",
        "llm_summary": "Wallet with 82% win rate dropped $25k.",
        "win_rate": 0.82,
        "total_pnl": 340_000.0,
        "tags": ["Politics"],
        "created_at": now,
    }
    defaults.update(overrides)
    return defaults


class FakeHTTP:
    """Stand-in for the `requests` module. Records calls, returns a canned body."""

    def __init__(self, body):
        self._body = body
        self.last_url = None
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        resp = SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: self._body
        resp.raise_for_status = lambda: None
        return resp


# ------------------------------------------------------- fetch_recent_alerts --

def test_fetch_recent_alerts_filters_to_lookback_window():
    recent = _alert(id=1, created_at=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
    old = _alert(id=2, created_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat())
    fake = FakeHTTP({"alerts": [recent, old], "total": 2, "page": 1, "per_page": 100})

    result = tb.fetch_recent_alerts(
        api_url="https://api.example.test",
        min_score=5.0,
        http=fake,
    )

    ids = [a["id"] for a in result]
    assert ids == [1]
    assert fake.last_url == "https://api.example.test/api/alerts"
    assert fake.last_params == {"per_page": 100, "min_score": 5.0}


def test_fetch_recent_alerts_returns_empty_on_no_alerts():
    fake = FakeHTTP({"alerts": [], "total": 0, "page": 1, "per_page": 100})

    result = tb.fetch_recent_alerts(
        api_url="https://api.example.test",
        min_score=5.0,
        http=fake,
    )

    assert result == []
