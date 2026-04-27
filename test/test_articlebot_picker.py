"""Tests for articlebot's tournament picker."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_fetch_24h_event_summaries_returns_groups_filtered_by_gamma():
    """Gamma-settled events drop out; surviving rows are returned verbatim."""
    import articlebot

    candidates = [
        {"event_slug": "alive-event", "top_condition_id": "0xa1", "top_composite": 9.0,
         "alerts": [{"id": 1}], "alert_count": 1, "event_usd": 1000.0,
         "strategies_fired": ["wallet_clustering"], "first_alert_at": None,
         "last_alert_at": None},
        {"event_slug": "settled-event", "top_condition_id": "0xb2", "top_composite": 8.0,
         "alerts": [{"id": 2}], "alert_count": 1, "event_usd": 500.0,
         "strategies_fired": ["timing_relative_resolution"], "first_alert_at": None,
         "last_alert_at": None},
    ]
    statuses = {
        "0xa1": {"closed": False, "uma_status": "", "max_price": 0.5},
        "0xb2": {"closed": True,  "uma_status": "", "max_price": 1.0},
    }

    with patch.object(articlebot, "query_postgres", return_value=candidates), \
         patch.object(articlebot, "_gamma_status_for_markets", return_value=statuses):
        out = articlebot.fetch_24h_event_summaries()

    assert len(out) == 1
    assert out[0]["event_slug"] == "alive-event"


def test_fetch_24h_event_summaries_handles_empty():
    import articlebot

    with patch.object(articlebot, "query_postgres", return_value=[]):
        assert articlebot.fetch_24h_event_summaries() == []


def test_fetch_24h_event_summaries_preserves_alert_signals_field():
    """Each alert in the JSONB_AGG payload now embeds a `signals` array
    (per the LATERAL subquery). Verify the function passes that through."""
    import articlebot

    candidates = [{
        "event_slug": "ev1",
        "top_condition_id": "0xa1",
        "top_composite": 9.0,
        "event_usd": 1000.0,
        "alert_count": 1,
        "strategies_fired": ["wallet_clustering"],
        "alerts": [{
            "id": 11,
            "composite_score": 9.0,
            "signals": [
                {"strategy": "wallet_clustering", "severity": 7.5, "headline": "h1"},
                {"strategy": "concentrated_one_sided", "severity": 6.0, "headline": "h2"},
            ],
        }],
        "first_alert_at": None,
        "last_alert_at": None,
    }]
    statuses = {"0xa1": {"closed": False, "uma_status": "", "max_price": 0.4}}

    with patch.object(articlebot, "query_postgres", return_value=candidates), \
         patch.object(articlebot, "_gamma_status_for_markets", return_value=statuses):
        out = articlebot.fetch_24h_event_summaries()

    assert len(out) == 1
    assert out[0]["alerts"][0]["signals"][0]["strategy"] == "wallet_clustering"
    assert len(out[0]["alerts"][0]["signals"]) == 2
