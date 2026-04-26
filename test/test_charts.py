"""Tests for storybot/charts.py — synthetic data, byte-level assertions."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# storybot directory on sys.path (matches how the bot is run in production)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))

import charts  # noqa: E402


def _png_dimensions(b: bytes) -> tuple[int, int]:
    img = Image.open(BytesIO(b))
    assert img.format == "PNG"
    return img.size


# --------- wallet_record_card ---------

def test_wallet_record_card_renders_png_at_canvas_size():
    data: charts.WalletRecordCardData = {
        "market_title": "Will Trump win 2024?",
        "record_str": "29-4",
        "win_pct": 0.879,
        "bet_count": 33,
        "wallet_age_days": 412,
        "bet_size_usd": 80_000,
        "outcome_side": "Yes",
    }
    png = charts.render_wallet_record_card(data)
    assert isinstance(png, bytes)
    assert len(png) > 1000  # not empty
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_wallet_record_card_handles_missing_age():
    data: charts.WalletRecordCardData = {
        "market_title": "Some market",
        "record_str": "12-2",
        "win_pct": 0.857,
        "bet_count": 14,
        "wallet_age_days": None,
        "bet_size_usd": 5_000,
        "outcome_side": "No",
    }
    png = charts.render_wallet_record_card(data)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


from unittest.mock import patch


def test_fetch_wallet_record_card_returns_none_for_unknown_wallet():
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        mock_cur.fetchone.return_value = None
        result = charts.fetch_wallet_record_card_data({"wallet": "0xabc"})
    assert result is None


def test_fetch_wallet_record_card_returns_none_for_too_few_bets():
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        # (wins, losses, win_rate, first_seen_at) — wins+losses=5+1=6 < 10
        mock_cur.fetchone.return_value = (5, 1, 0.833, None)
        result = charts.fetch_wallet_record_card_data({"wallet": "0xabc"})
    assert result is None


def test_fetch_wallet_record_card_returns_data_when_eligible():
    alert = {
        "wallet": "0xabc",
        "market_title": "Will Trump win 2024?",
        "total_usd": 80_000,
        "llm_copy_action": '{"outcome": "Yes"}',
    }
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        # (wins, losses, win_rate, first_seen_at) — 29+4=33 >= 10
        mock_cur.fetchone.return_value = (29, 4, 0.879, None)
        result = charts.fetch_wallet_record_card_data(alert)
    assert result is not None
    assert result["record_str"] == "29-4"
    assert result["bet_count"] == 33
    assert result["wallet_age_days"] is None


# --------- volume_bar ---------

def test_volume_bar_renders_png_at_canvas_size():
    data: charts.VolumeBarData = {
        "market_title": "Arsenal vs Newcastle",
        "today_volume_usd": 906_000,
        "baseline_avg_usd": 1_000,
        "multiplier": 906.0,
    }
    png = charts.render_volume_bar(data)
    assert isinstance(png, bytes)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_fetch_volume_bar_returns_none_when_today_too_small():
    with patch("charts._fetch_market_volume_window", return_value=500.0):
        result = charts.fetch_volume_bar_data({"condition_id": "0xabc"})
    assert result is None


def test_fetch_volume_bar_returns_none_when_multiplier_below_threshold():
    # 10000 / (14300 / 7) = 10000 / ~2042.86 = ~4.9x, below 5.0 threshold
    calls = iter([10_000.0, 14_300.0])
    with patch("charts._fetch_market_volume_window", side_effect=lambda *a, **k: next(calls)):
        result = charts.fetch_volume_bar_data({"condition_id": "0xabc"})
    assert result is None


def test_fetch_volume_bar_returns_data_for_real_spike():
    calls = iter([906_000.0, 7_000.0])  # today, baseline_total
    with patch("charts._fetch_market_volume_window", side_effect=lambda *a, **k: next(calls)):
        result = charts.fetch_volume_bar_data({
            "condition_id": "0xabc",
            "market_title": "Arsenal vs Newcastle",
        })
    assert result is not None
    assert result["multiplier"] > 800


# --------- cluster_card ---------

def test_cluster_card_renders_png_at_canvas_size():
    data: charts.ClusterCardData = {
        "market_title": "Arsenal vs Newcastle — Arsenal wins",
        "outcome_side": "Arsenal",
        "wallet_sizes": [
            ("Wallet_0xabcde", 180_000),
            ("Sharp_0x12345", 120_000),
            ("Trader_0x99887", 50_000),
            ("Whale_0xdeadb", 30_000),
            ("Wallet_0xfeedf", 14_000),
        ],
        "total_usd": 394_000,
        "shared_funder": "0xabc1234567890",
    }
    png = charts.render_cluster_card(data)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_wallet_pseudonym_format():
    # Mirrors frontend/src/lib/pseudonym.js:
    #   prefix = tier?.prefix || "Wallet"
    #   short  = address.startsWith("0x") ? address.slice(2, 7) : address.slice(0, 5)
    #   return `${prefix}_0x${short}`
    assert charts.wallet_pseudonym("0xabcdef1234567890") == "Wallet_0xabcde"
    # With explicit tier prefix
    assert charts.wallet_pseudonym("0xabcdef1234567890", {"prefix": "Sharp"}) == "Sharp_0xabcde"
    # No 0x prefix — uses first 5 chars
    assert charts.wallet_pseudonym("deadbeef1234") == "Wallet_0xdeadb"
    # Empty input
    assert charts.wallet_pseudonym("") == "Unknown"
    assert charts.wallet_pseudonym(None) == "Unknown"


def test_fetch_cluster_card_returns_none_for_single_wallet():
    alert = {"trades": [{"proxyWallet": "0xabc", "usdcSize": 1000}]}
    result = charts.fetch_cluster_card_data(alert)
    assert result is None


def test_fetch_cluster_card_returns_none_when_no_shared_funder():
    alert = {
        "trades": [
            {"proxyWallet": "0xabc", "usdcSize": 1000},
            {"proxyWallet": "0xdef", "usdcSize": 2000},
        ],
    }
    with patch("charts._shared_funder_for_wallets", return_value=None):
        result = charts.fetch_cluster_card_data(alert)
    assert result is None


def test_fetch_cluster_card_returns_data_when_shared_funder_present():
    alert = {
        "market_title": "Arsenal vs Newcastle — Arsenal wins",
        "total_usd": 3000,
        "llm_copy_action": {"outcome": "Arsenal"},
        "trades": [
            {"proxyWallet": "0xabcdef1234567890", "usdcSize": 1000},
            {"proxyWallet": "0xdeadbeef99887766", "usdcSize": 2000},
        ],
    }
    with patch("charts._shared_funder_for_wallets", return_value="0xfunder"):
        result = charts.fetch_cluster_card_data(alert)
    assert result is not None
    assert len(result["wallet_sizes"]) == 2
    assert result["shared_funder"] == "0xfunder"
    assert result["outcome_side"] == "Arsenal"
    # Pseudonyms applied — names should not equal raw addresses
    for name, _ in result["wallet_sizes"]:
        assert name.startswith("Wallet_0x")
