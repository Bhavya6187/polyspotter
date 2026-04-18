import json
from datetime import datetime, timezone
from signals import (
    bucket_rating,
    tier_for_wallet,
    color_for_wallet,
    return_pct,
    signal_from_row,
)

def test_rating_buckets():
    assert bucket_rating(30.0) == 5
    assert bucket_rating(25.0) == 5
    assert bucket_rating(24.9) == 4
    assert bucket_rating(18.0) == 4
    assert bucket_rating(12.0) == 3
    assert bucket_rating(11.99) == 2
    assert bucket_rating(7.0) == 2
    assert bucket_rating(6.9) == 1
    assert bucket_rating(0) == 1

def test_tier_legend_requires_both():
    assert tier_for_wallet(win_rate=0.92, pnl=500_000) == "legend"
    assert tier_for_wallet(win_rate=0.92, pnl=100_000) == "sharp"  # pnl too low
    assert tier_for_wallet(win_rate=0.75, pnl=500_000) == "sharp"  # winrate too low

def test_tier_sharp_and_prov():
    assert tier_for_wallet(win_rate=0.72, pnl=10_000) == "sharp"
    assert tier_for_wallet(win_rate=0.50, pnl=10_000) == "prov"
    assert tier_for_wallet(win_rate=None,  pnl=None)  == "prov"

def test_color_is_stable_per_address():
    c1 = color_for_wallet("0x7a3b4f21")
    c2 = color_for_wallet("0x7a3b4f21")
    c3 = color_for_wallet("0x1c4e8a09")
    assert c1 == c2
    assert c1 in {"#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"}
    assert c3 in {"#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"}

def test_color_is_case_insensitive():
    # Checksummed and lowercased forms of the same address must match.
    assert color_for_wallet("0xABCDef1234") == color_for_wallet("0xabcdef1234")

def test_return_pct_yes():
    # YES at 20¢: pays $1 if resolves YES; return = (1 - 0.20)/0.20 = 4.0 → 400%
    assert return_pct("YES", 0.20) == 400

def test_return_pct_no_at_80():
    # NO at 80¢: pays $1 if resolves NO; return = (1 - 0.80)/0.80 = 25%
    assert return_pct("NO", 0.80) == 25

def test_return_pct_no_at_20():
    assert return_pct("NO", 0.20) == 400

def test_return_pct_handles_edge_cases():
    assert return_pct(None, 0.5) == 0
    assert return_pct("YES", None) == 0
    assert return_pct("YES", 0) == 0
    assert return_pct("YES", 1.0) == 0

def _row(**over):
    base = {
        "id": 1,
        "composite_score": 18.2,
        "tags": '["Crypto"]',
        "market_title": "Ethereum above $4,200 on April 30",
        "condition_id": "0xcid",
        "event_slug": "ethereum-above-4200",
        "market_url": "https://polymarket.com/event/eth",
        "market_image": None,
        "market_description": None,
        "wallet": "0x1c4e8a09",
        "total_usd": 31_700,
        "trade_count": 1,
        "cluster_headline": None,
        "end_date": datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc),
        "llm_headline": "ETH cluster",
        "llm_summary": "Cluster of 4 linked wallets bet $112k combined on ETH > $4,200.",
        "llm_bullets": '["A", "B", "C"]',
        "llm_copy_action": '{}',
        "scanned_at": None,
        "created_at": datetime.now(timezone.utc),
        "win_rate": 0.84,
        "total_pnl": 218_000.0,
        "total_invested": 260_000.0,
    }
    base.update(over)
    return base

def test_signal_from_row_basic_shape():
    row = _row()
    s = signal_from_row(row, trades=[], live={"yes_price": 0.44, "price_change_24h": 0.12, "volume_24h": 1_180_000, "candles": [0.31,0.35,0.40,0.44]})
    assert s.id == "1"
    assert s.market.topic == "Crypto"
    assert s.market.icon == "Ξ"
    assert s.wallet.alias != ""
    assert s.wallet.tier == "sharp"
    assert s.stake_usd == 31_700
    assert s.score == 18.2
    assert s.rating == 4
    assert s.why.startswith("Cluster of 4")
    assert s.bullets == ["A", "B", "C"]
    assert s.market.yes_price == 0.44
    assert s.market.candles == [0.31,0.35,0.40,0.44]

def test_signal_from_row_fills_side_and_entry_from_trades():
    row = _row()
    trade = {"side": "BUY", "outcome": "YES", "price": 0.41, "trade_timestamp": datetime.now(timezone.utc), "usd_value": 31_700}
    s = signal_from_row(row, trades=[trade], live={"yes_price": 0.44})
    assert s.side == "YES"
    assert s.entry_price == 0.41
    assert s.price_at_alert == 0.41
    assert s.price_now == 0.44

def test_signal_from_row_pads_bullets_to_three():
    row = _row(llm_bullets='["one"]')
    s = signal_from_row(row, trades=[], live={})
    assert len(s.bullets) == 3
    assert s.bullets[0] == "one"

def test_signal_from_row_why_fallbacks():
    row = _row(llm_summary=None, cluster_headline="cluster")
    s = signal_from_row(row, trades=[], live={})
    assert s.why == "cluster"

    row2 = _row(llm_summary=None, cluster_headline=None, llm_headline="head")
    s2 = signal_from_row(row2, trades=[], live={})
    assert s2.why == "head"

def test_signal_from_row_no_trades_returns_null_side():
    s = signal_from_row(_row(), trades=[], live={})
    assert s.side is None
    assert s.entry_price is None
    assert s.return_pct == 0
