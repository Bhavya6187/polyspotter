"""Tests for the deterministic facts_bundle builder in twitter_pipeline.py."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


def _trade(*, wallet="0xa", outcome="Yes", usd=100.0, price=0.5, ts=None):
    return {
        "wallet": wallet, "outcome": outcome, "side": "BUY",
        "usdcSize": usd, "size": 200.0, "price": price,
        "timestamp": float(ts if ts is not None else time.time()),
        "transaction_hash": "0xdead",
    }


def test_empty_inputs_produce_zeroed_bundle():
    b = twitter_pipeline.build_facts_bundle([], [])
    assert b["distinct_wallets"] == 0
    assert b["total_usd"] == 0
    assert b["trade_count"] == 0
    assert b["time_span_minutes"] == 0
    assert b["biggest_price_move"] is None
    assert b["peak_hour_volume_usd"] is None
    assert b["has_sharp_wallet"] is None
    assert b["cluster_size"] is None
    assert b["has_volume_spike"] is False
    assert b["minutes_to_resolution"] is None


def test_distinct_wallets_and_total_usd():
    trades = [
        _trade(wallet="0xa", usd=100),
        _trade(wallet="0xb", usd=200),
        _trade(wallet="0xa", usd=300),
    ]
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["distinct_wallets"] == 2
    assert b["total_usd"] == 600
    assert b["trade_count"] == 3


def test_biggest_price_move_uses_dominant_outcome():
    # 80% of USD is on "Yes" (price moves 0.32 → 0.41).
    # 20% on "No" (price moves wildly, but ignored).
    trades = [
        _trade(outcome="Yes", usd=400, price=0.32, ts=1000),
        _trade(outcome="Yes", usd=400, price=0.41, ts=2000),
        _trade(outcome="No", usd=200, price=0.10, ts=3000),
        _trade(outcome="No", usd=200, price=0.90, ts=4000),
    ]
    b = twitter_pipeline.build_facts_bundle([], trades)
    move = b["biggest_price_move"]
    assert move == {"from": 0.32, "to": 0.41}


def test_biggest_price_move_none_with_single_trade():
    trades = [_trade(outcome="Yes", usd=100, price=0.5, ts=1000)]
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["biggest_price_move"] is None


def test_peak_hour_volume_uses_60min_rolling_window():
    # Two clusters: 5 trades within 30 min totaling 5000, then a single
    # trade 2 hours later. Peak should be the 5000.
    base = 1_700_000_000
    trades = [_trade(usd=1000, ts=base + 60 * i) for i in range(5)]
    trades.append(_trade(usd=200, ts=base + 7200))
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["peak_hour_volume_usd"] == 5000


def test_volume_spike_signal_lifted_from_alerts():
    alerts = [{"signals": [{"strategy": "pre_event_volume_spike", "severity": 5}]}]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_volume_spike"] is True


def test_cluster_size_lifted_from_wallet_clustering_severity():
    alerts = [{
        "signals": [
            {"strategy": "wallet_clustering", "severity": 4},
            {"strategy": "concentrated_one_sided", "severity": 6},
        ]
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["cluster_size"] == 6


def test_sharp_wallet_from_llm_copy_action():
    alerts = [{
        "wallet": "0xfeed",
        "llm_copy_action": {"wallet_record": "29-4", "win_pct": 0.88},
        "signals": [],
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_sharp_wallet"] == {
        "wallet": "0xfeed", "record": "29-4", "win_pct": 0.88,
    }


def test_sharp_wallet_falls_back_to_wallet_pnl(monkeypatch):
    # No record in llm_copy_action; signals indicate win_rate_tracking;
    # query_sqlite returns a real row.
    alerts = [{
        "wallet": "0xfeed",
        "llm_copy_action": {},
        "signals": [{"strategy": "win_rate_tracking", "severity": 8}],
    }]
    captured = {}
    def fake_query(sql, params=()):
        captured["sql"] = sql
        captured["params"] = params
        return [{"wins": 178, "losses": 20, "win_rate": 0.899}]
    import bot_utils
    monkeypatch.setattr(bot_utils, "query_sqlite", fake_query)
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_sharp_wallet"]["record"] == "178-20"
    assert b["has_sharp_wallet"]["wallet"] == "0xfeed"
    assert b["has_sharp_wallet"]["win_pct"] == 0.899
    assert captured["params"] == ("0xfeed",)


def test_minutes_to_resolution_uses_nearest_future_time():
    in_30 = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    in_120 = (datetime.now(timezone.utc) + timedelta(minutes=120)).isoformat()
    alerts = [
        {"game_start_time": in_120},
        {"game_start_time": in_30},
    ]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert 28 <= b["minutes_to_resolution"] <= 31
