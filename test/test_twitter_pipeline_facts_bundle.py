"""Tests for the deterministic facts_bundle builder in twitter_pipeline.py."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

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
    assert b["volume_multiplier_x"] is None


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


def test_cluster_size_parsed_from_headline_not_severity():
    # Severity for these strategies is log-scaled and saturates at 8.0, so it
    # can't be used as cluster size. The real count lives in the headline.
    alerts = [{
        "signals": [
            {"strategy": "wallet_clustering", "severity": 8.0,
             "headline": "18 wallets share funder 0xabc...def, $25,000 total (+17 from prior runs)"},
            {"strategy": "concentrated_one_sided", "severity": 8.0,
             "headline": "37 wallets, same direction (Hawks/BUY), $564,695 — 8 share funder (linked)"},
        ]
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["cluster_size"] == 37  # max across signals


def test_cluster_size_handles_known_sybil_form():
    alerts = [{
        "signals": [
            {"strategy": "wallet_clustering", "severity": 6.0,
             "headline": "Known linked funder 0xabc...def: 2 wallet(s) active, 18 total known, $3,000"},
        ]
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["cluster_size"] == 18  # uses "total known", not "wallet(s) active"


def test_cluster_size_none_when_headline_unparseable():
    alerts = [{
        "signals": [
            {"strategy": "wallet_clustering", "severity": 8.0, "headline": "garbage"},
        ]
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["cluster_size"] is None


def test_sharp_wallet_bet_usd_sums_only_that_wallets_trades(monkeypatch):
    """bet_usd must isolate the sharp wallet's contribution from the cluster
    total — otherwise the writer can't tell them apart."""
    trades = [
        _trade(wallet="0xfeed", usd=1_000),    # the sharp wallet
        _trade(wallet="0xfeed", usd=500),      # same wallet, second trade
        _trade(wallet="0xother", usd=22_000),  # a different cluster wallet
    ]
    alerts = [{
        "id": 4242,
        "wallet": "0xfeed",
        "signals": [{"strategy": "win_rate_tracking", "severity": 8}],
    }]
    import db
    monkeypatch.setattr(db, "get_wallet_pnl_summary",
                        lambda w: {"closed_positions": 197, "wins": 184, "losses": 13})
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    sharp = b["has_sharp_wallet"]
    assert sharp["wallet"] == "0xfeed"
    assert sharp["record"] == "184-13"
    assert sharp["bet_usd"] == 1_500.0
    # Total sums all trades, not just the sharp's.
    assert b["total_usd"] == 23_500.0


def test_sharp_wallet_falls_back_to_wallet_pnl_summary(monkeypatch):
    # signals indicate win_rate_tracking; db.get_wallet_pnl_summary
    # returns aggregated stats for the wallet.
    alerts = [{
        "id": 4242,
        "wallet": "0xfeed",
        "signals": [{"strategy": "win_rate_tracking", "severity": 8}],
    }]
    captured = {}
    def fake_summary(wallet):
        captured["wallet"] = wallet
        return {"closed_positions": 198, "wins": 178, "losses": 20}
    import db
    monkeypatch.setattr(db, "get_wallet_pnl_summary", fake_summary)
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_sharp_wallet"]["record"] == "178-20"
    assert b["has_sharp_wallet"]["wallet"] == "0xfeed"
    assert abs(b["has_sharp_wallet"]["win_pct"] - 178 / 198) < 1e-6
    assert b["has_sharp_wallet"]["alert_id"] == 4242
    assert captured["wallet"] == "0xfeed"


def test_sharp_wallet_triggers_on_correlated_cross_market_signal(monkeypatch):
    # correlated_cross_market alerts also imply the wallet's record is the
    # load-bearing fact — the bundle should look it up so the chart picker
    # can pick wallet_record_card.
    alerts = [{
        "id": 131876,
        "wallet": "0xfeed",
        "signals": [{"strategy": "correlated_cross_market", "severity": 5}],
    }]
    import db
    monkeypatch.setattr(db, "get_wallet_pnl_summary",
                        lambda w: {"closed_positions": 104, "wins": 76, "losses": 28})
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    sharp = b["has_sharp_wallet"]
    assert sharp is not None
    assert sharp["wallet"] == "0xfeed"
    assert sharp["record"] == "76-28"
    assert sharp["alert_id"] == 131876


def test_sharp_wallet_finds_best_wallet_in_cluster(monkeypatch):
    # Cluster alert (alert.wallet is None) with 3 wallets in trades. Only
    # one of them clears MIN_RESOLVED_BETS and has the best win rate. The
    # extractor must scan trades, look each wallet up via
    # get_wallet_pnl_summary, and return that best wallet.
    trades = [
        _trade(wallet="0xaaa", usd=1000),
        _trade(wallet="0xbbb", usd=2000),
        _trade(wallet="0xccc", usd=500),
    ]
    alerts = [{
        "id": 121743,
        "wallet": None,
        "signals": [{"strategy": "win_rate_tracking", "severity": 4}],
        "trades": trades,
    }]
    summaries = {
        "0xaaa": {"closed_positions": 50, "wins": 30, "losses": 20},   # 60%
        "0xbbb": {"closed_positions": 226, "wins": 215, "losses": 11}, # 95%
        "0xccc": {"closed_positions": 5, "wins": 5, "losses": 0},      # below min
    }
    import db
    monkeypatch.setattr(db, "get_wallet_pnl_summary",
                        lambda w: summaries.get(w, {"closed_positions": 0, "wins": 0, "losses": 0}))
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    sharp = b["has_sharp_wallet"]
    assert sharp is not None
    assert sharp["wallet"] == "0xbbb"
    assert sharp["record"] == "215-11"
    assert abs(sharp["win_pct"] - 215 / 226) < 1e-6
    assert sharp["alert_id"] == 121743


def test_sharp_wallet_returns_none_when_cluster_has_no_qualifying_wallet(monkeypatch):
    # Cluster wallets all have too few resolved positions — no story.
    trades = [_trade(wallet="0xaaa", usd=100), _trade(wallet="0xbbb", usd=200)]
    alerts = [{
        "id": 99,
        "wallet": None,
        "signals": [{"strategy": "win_rate_tracking", "severity": 4}],
        "trades": trades,
    }]
    import db
    monkeypatch.setattr(db, "get_wallet_pnl_summary",
                        lambda w: {"closed_positions": 5, "wins": 5, "losses": 0})
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    assert b["has_sharp_wallet"] is None


def test_fresh_wallet_returns_wallet_for_single_wallet_alert(monkeypatch):
    # Single-wallet alert with new_wallet_large_bet signal: surface wallet,
    # alert_id, and wallet_age_days computed from _fetch_wallet_created_at.
    alerts = [{
        "id": 999,
        "wallet": "0xfeed",
        "signals": [{"strategy": "new_wallet_large_bet", "severity": 4}],
    }]
    now = datetime.now(timezone.utc)
    import charts
    monkeypatch.setattr(charts, "_fetch_wallet_created_at",
                        lambda w: now - timedelta(days=7))
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    fw = b["has_fresh_wallet"]
    assert fw["wallet"] == "0xfeed"
    assert fw["alert_id"] == 999
    assert fw["wallet_age_days"] == 7


def test_fresh_wallet_finds_youngest_in_cluster(monkeypatch):
    # Cluster alert: scan trade wallets, pick the youngest within
    # FRESH_WALLET_MAX_DAYS based on Gamma createdAt.
    trades = [
        _trade(wallet="0xaaa", usd=1000),
        _trade(wallet="0xbbb", usd=2000),
        _trade(wallet="0xccc", usd=500),
    ]
    alerts = [{
        "id": 121967,
        "wallet": None,
        "signals": [{"strategy": "new_wallet_large_bet", "severity": 5}],
    }]
    now = datetime.now(timezone.utc)
    ages = {
        "0xaaa": now - timedelta(days=200),  # too old
        "0xbbb": now - timedelta(days=12),   # qualifying
        "0xccc": now - timedelta(days=3),    # youngest qualifying
    }
    import charts
    monkeypatch.setattr(charts, "_fetch_wallet_created_at",
                        lambda w: ages.get(w))
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    fw = b["has_fresh_wallet"]
    assert fw["wallet"] == "0xccc"
    assert fw["alert_id"] == 121967
    assert fw["wallet_age_days"] == 3


def test_fresh_wallet_returns_none_when_cluster_has_no_fresh_wallet(monkeypatch):
    trades = [_trade(wallet="0xaaa"), _trade(wallet="0xbbb")]
    alerts = [{
        "id": 99,
        "wallet": None,
        "signals": [{"strategy": "new_wallet_large_bet", "severity": 4}],
    }]
    now = datetime.now(timezone.utc)
    import charts
    monkeypatch.setattr(charts, "_fetch_wallet_created_at",
                        lambda w: now - timedelta(days=200))
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    assert b["has_fresh_wallet"] is None


def test_fresh_wallet_requires_signal_for_cluster(monkeypatch):
    # Cluster has a fresh wallet but no new_wallet_large_bet signal —
    # don't surface a story we weren't told about and don't even hit Gamma.
    trades = [_trade(wallet="0xaaa")]
    alerts = [{
        "id": 99,
        "wallet": None,
        "signals": [{"strategy": "concentrated_one_sided", "severity": 5}],
    }]
    import charts
    called = {"n": 0}
    def fake(w):
        called["n"] += 1
        return datetime.now(timezone.utc) - timedelta(days=2)
    monkeypatch.setattr(charts, "_fetch_wallet_created_at", fake)
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    assert b["has_fresh_wallet"] is None
    assert called["n"] == 0


def test_sharp_wallet_requires_win_rate_signal_for_cluster(monkeypatch):
    # Cluster has sharp wallets in trades, but no win_rate_tracking signal.
    # Don't surface a record we weren't told to surface.
    trades = [_trade(wallet="0xaaa", usd=100)]
    alerts = [{
        "id": 99,
        "wallet": None,
        "signals": [{"strategy": "concentrated_one_sided", "severity": 5}],
        "trades": trades,
    }]
    import db
    called = {"n": 0}
    def fake_summary(_w):
        called["n"] += 1
        return {"closed_positions": 226, "wins": 215, "losses": 11}
    monkeypatch.setattr(db, "get_wallet_pnl_summary", fake_summary)
    b = twitter_pipeline.build_facts_bundle(alerts, trades)
    assert b["has_sharp_wallet"] is None
    assert called["n"] == 0  # don't even hit the DB without the gating signal


def test_minutes_to_resolution_uses_nearest_future_time():
    in_30 = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    in_120 = (datetime.now(timezone.utc) + timedelta(minutes=120)).isoformat()
    alerts = [
        {"game_start_time": in_120},
        {"game_start_time": in_30},
    ]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert 28 <= b["minutes_to_resolution"] <= 31


def test_fetch_data_bundle_collects_trades_per_alert(monkeypatch):
    seed = [
        {"id": 1, "condition_id": "0xabc"},
        {"id": 2, "condition_id": "0xabc"},  # same market — token fetch should dedup
        {"id": 3, "condition_id": "0xdef"},
    ]
    calls_trades = []
    calls_tokens = []
    def fake_trades(aid):
        calls_trades.append(int(aid))
        return [_trade(wallet=f"0x{aid:02x}", usd=100)]
    def fake_tokens(cid):
        calls_tokens.append(cid)
        return {"Yes": f"tok-{cid}-yes"}

    import tweet_utils
    monkeypatch.setattr(tweet_utils, "fetch_alert_trades", fake_trades)
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", fake_tokens)

    bundle = twitter_pipeline.fetch_data_bundle([1, 2, 3], seed)

    assert calls_trades == [1, 2, 3]
    assert sorted(calls_tokens) == sorted(["0xabc", "0xdef"])  # deduped
    assert len(bundle["chosen_alerts"]) == 3
    assert len(bundle["trades"]) == 3
    assert "Yes" in bundle["token_map"]
    assert "facts_bundle" in bundle
    assert bundle["facts_bundle"]["distinct_wallets"] == 3


def test_chart_target_alert_id_uses_fresh_wallet_alert():
    # primary alert is the sharp/serial wallet; fresh wallet is on a secondary
    # alert in the cluster — fresh_wallet_card must route to that one.
    facts_bundle = {
        "has_fresh_wallet": {"wallet": "0xnew", "alert_id": 120672},
        "has_sharp_wallet": None,
    }
    target = twitter_pipeline._chart_target_alert_id(
        "fresh_wallet_card", [120845, 120672], facts_bundle)
    assert target == 120672


def test_chart_target_alert_id_uses_sharp_wallet_alert():
    facts_bundle = {
        "has_fresh_wallet": None,
        "has_sharp_wallet": {"wallet": "0xpro", "record": "71-0",
                             "win_pct": 1.0, "alert_id": 999},
    }
    target = twitter_pipeline._chart_target_alert_id(
        "wallet_record_card", [120, 999], facts_bundle)
    assert target == 999


def test_chart_target_alert_id_falls_back_to_primary_for_other_charts():
    # price_sparkline / volume_bar / cluster_card aren't bound to a specific
    # wallet — they render against the primary alert in the cluster.
    facts_bundle = {
        "has_fresh_wallet": {"wallet": "0xnew", "alert_id": 999},
        "has_sharp_wallet": None,
    }
    for chart_type in ("price_sparkline", "volume_bar", "cluster_card", "none"):
        target = twitter_pipeline._chart_target_alert_id(
            chart_type, [120845, 999], facts_bundle)
        assert target == 120845, chart_type


def test_chart_target_alert_id_falls_back_when_bundle_missing_alert():
    # Defensive: if the bundle's wallet entry is missing alert_id (older
    # transcripts or partial data), fall back to the primary alert rather
    # than crashing or pointing nowhere.
    facts_bundle = {
        "has_fresh_wallet": {"wallet": "0xnew"},  # no alert_id
        "has_sharp_wallet": None,
    }
    target = twitter_pipeline._chart_target_alert_id(
        "fresh_wallet_card", [120845, 120672], facts_bundle)
    assert target == 120845


def test_volume_multiplier_x_set_when_volume_spike_and_baseline_known(monkeypatch):
    """When has_volume_spike is True, fetch_data_bundle enriches the bundle
    with volume_multiplier_x using gamma 24h volume / sqlite 7-day baseline."""
    import twitter_pipeline
    import charts

    # Stub the two fetchers volume_bar already uses.
    monkeypatch.setattr(charts, "_fetch_gamma_volume24hr",
                        lambda cid: 120_000.0)
    monkeypatch.setattr(charts, "_fetch_baseline_avg_volume",
                        lambda cid: 10_000.0)
    # Stub trade-fetch + token-fetch — irrelevant to this test.
    # fetch_data_bundle imports these locally, so a monkeypatch on the
    # tweet_utils module attribute is picked up on the next call.
    import tweet_utils
    monkeypatch.setattr(tweet_utils, "fetch_alert_trades", lambda aid: [])
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", lambda cid: {})

    chosen_alert = {
        "id": 1,
        "condition_id": "0xabc",
        "signals": [{"strategy": "pre_event_volume_spike", "headline": "x"}],
    }
    bundle = twitter_pipeline.fetch_data_bundle([1], [chosen_alert])
    fb = bundle["facts_bundle"]
    assert fb["has_volume_spike"] is True
    assert fb["volume_multiplier_x"] == pytest.approx(12.0)


def test_volume_multiplier_x_uses_cid_from_spike_alert_in_cross_market_cluster(monkeypatch):
    """In a cross-market cluster, pick the cid of the alert that actually
    fired pre_event_volume_spike — not just the first cid in the cluster."""
    import twitter_pipeline
    import charts

    seen_cids = []
    def fake_volume(cid):
        seen_cids.append(cid)
        return 120_000.0
    monkeypatch.setattr(charts, "_fetch_gamma_volume24hr", fake_volume)
    monkeypatch.setattr(charts, "_fetch_baseline_avg_volume",
                        lambda cid: 10_000.0)
    import tweet_utils
    monkeypatch.setattr(tweet_utils, "fetch_alert_trades", lambda aid: [])
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", lambda cid: {})

    # First alert: cross-market correlation, no spike. Second alert: spike.
    alerts = [
        {"id": 1, "condition_id": "0x_no_spike",
         "signals": [{"strategy": "correlated_cross_market", "headline": "x"}]},
        {"id": 2, "condition_id": "0x_spike",
         "signals": [{"strategy": "pre_event_volume_spike", "headline": "x"}]},
    ]
    bundle = twitter_pipeline.fetch_data_bundle([1, 2], alerts)
    assert bundle["facts_bundle"]["volume_multiplier_x"] == pytest.approx(12.0)
    assert "0x_spike" in seen_cids
    assert "0x_no_spike" not in seen_cids


def test_volume_multiplier_x_none_when_no_volume_spike():
    import twitter_pipeline
    bundle = twitter_pipeline.build_facts_bundle([], [])
    assert bundle["has_volume_spike"] is False
    assert bundle["volume_multiplier_x"] is None
