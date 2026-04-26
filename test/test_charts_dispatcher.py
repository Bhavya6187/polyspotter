"""Dispatcher behavior + fallback ladder tests for storybot/charts.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def test_render_chart_returns_none_for_unknown_chart_type():
    result = charts.render_chart_for_alert("not_a_real_type", {})
    assert result is None


def test_render_chart_returns_none_for_none():
    result = charts.render_chart_for_alert("none", {})
    assert result is None


def test_render_chart_returns_bytes_when_primary_succeeds():
    fake_data = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    # Patch the function in the registry by patching the module's reference
    with patch.dict(
        "charts._CHART_REGISTRY",
        {"wallet_record_card": (lambda alert: fake_data, charts.render_wallet_record_card)},
    ):
        result = charts.render_chart_for_alert("wallet_record_card", {"wallet": "0xabc"})
    assert isinstance(result, bytes)
    assert len(result) > 1000


def test_render_chart_falls_back_to_wallet_record_when_primary_fails():
    fake_wallet = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    # Patch volume_bar to fail, fallback to wallet_record
    with patch.dict(
        "charts._CHART_REGISTRY",
        {
            "volume_bar": (lambda alert: None, charts.render_volume_bar),
            "wallet_record_card": (lambda alert: fake_wallet, charts.render_wallet_record_card),
        },
    ):
        result = charts.render_chart_for_alert("volume_bar", {"wallet": "0xabc"})
    assert isinstance(result, bytes)


def test_render_chart_returns_none_when_primary_and_fallback_fail():
    with patch("charts.fetch_volume_bar_data", return_value=None), \
         patch("charts.fetch_wallet_record_card_data", return_value=None):
        result = charts.render_chart_for_alert("volume_bar", {"wallet": "0xabc"})
    assert result is None


def test_render_chart_returns_none_on_render_exception():
    fake_data = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    # When the chart_type is wallet_record_card AND the render fails, the
    # dispatcher should return None (no further fallback — primary IS the fallback).
    with patch("charts.fetch_wallet_record_card_data", return_value=fake_data), \
         patch("charts.render_wallet_record_card", side_effect=RuntimeError("boom")):
        result = charts.render_chart_for_alert("wallet_record_card", {"wallet": "0xabc"})
    assert result is None
