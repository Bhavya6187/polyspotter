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


from types import SimpleNamespace


class _FakeCompletions:
    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        content = self._contents.pop(0) if self._contents else "{}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class _FakeClient:
    def __init__(self, contents):
        self.completions = _FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.completions)


def _ev(slug, score=5.0):
    return {
        "event_slug": slug, "top_composite": score, "event_usd": 1000.0,
        "alert_count": 1, "strategies_fired": ["new_wallet_large_bet"],
        "alerts": [{"id": 1, "composite_score": score, "market_title": slug,
                    "wallet": "0xabc", "total_usd": 1000.0,
                    "llm_headline": "headline " + slug}],
        "first_alert_at": None, "last_alert_at": None,
    }


def test_pick_finalists_chunk_returns_top_3():
    import articlebot
    chunk = [_ev(f"slug-{i}") for i in range(10)]
    client = _FakeClient(['{"finalists":["slug-0","slug-3","slug-7"],"reasoning":"r"}'])

    out = articlebot.pick_finalists_chunk(client, chunk)

    assert out == ["slug-0", "slug-3", "slug-7"]
    assert client.completions.calls == 1


def test_pick_finalists_chunk_drops_unknown_slugs():
    """If the model hallucinates a slug, drop it; keep the real ones."""
    import articlebot
    chunk = [_ev(f"slug-{i}") for i in range(5)]
    client = _FakeClient(['{"finalists":["slug-1","ghost-slug","slug-2"],"reasoning":"r"}'])

    out = articlebot.pick_finalists_chunk(client, chunk)
    assert out == ["slug-1", "slug-2"]


def test_pick_finalists_chunk_returns_empty_on_invalid_json():
    import articlebot
    chunk = [_ev("slug-0")]
    client = _FakeClient(["not json"])

    out = articlebot.pick_finalists_chunk(client, chunk)
    assert out == []
