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


def test_pick_final_event_returns_chosen_event_and_alert_ids():
    import articlebot
    finalists = [_ev("slug-a"), _ev("slug-b")]
    finalists[0]["alerts"] = [
        {"id": 11, "composite_score": 9.0, "market_title": "M", "wallet": "0x1",
         "total_usd": 5000.0, "llm_headline": "hi"},
        {"id": 12, "composite_score": 8.0, "market_title": "M", "wallet": "0x2",
         "total_usd": 2000.0, "llm_headline": "hey"},
    ]
    finalists[1]["alerts"] = [
        {"id": 21, "composite_score": 7.0, "market_title": "N", "wallet": "0x3",
         "total_usd": 1000.0, "llm_headline": "ho"},
    ]
    client = _FakeClient([
        '{"decision":"post","event_slug":"slug-a","alert_ids":[11,12],"reason":"r"}'
    ])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "post"
    assert out["event_slug"] == "slug-a"
    assert out["alert_ids"] == [11, 12]


def test_pick_final_event_returns_skip():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(['{"decision":"skip","event_slug":null,"alert_ids":null,"reason":"weak"}'])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"
    assert out["alert_ids"] is None


def test_pick_final_event_passes_recent_slugs_to_prompt():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(['{"decision":"skip","event_slug":null,"alert_ids":null,"reason":"r"}'])

    articlebot.pick_final_event(client, finalists,
                                recent_event_slugs=["already-covered"])

    user_msg = client.completions.last_kwargs["messages"][1]["content"]
    assert "already-covered" in user_msg


def test_pick_final_event_invalid_json_returns_skip():
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient(["not json"])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"
    assert "invalid JSON" in out["reason"]


def test_pick_final_event_drops_unknown_slug():
    """Defense in depth: if the model returns a slug not in the finalists,
    treat as skip."""
    import articlebot
    finalists = [_ev("slug-a")]
    client = _FakeClient([
        '{"decision":"post","event_slug":"ghost","alert_ids":[1],"reason":"r"}'
    ])

    out = articlebot.pick_final_event(client, finalists, recent_event_slugs=[])

    assert out["decision"] == "skip"


def test_pick_article_story_orchestrates_stages():
    """Stage 0 returns 60 events → 2 stage-1 chunks → 6 finalists → stage 2
    picks one. Verifies the orchestrator threads inputs/outputs correctly."""
    import articlebot

    events = [_ev(f"slug-{i}", score=10 - i) for i in range(60)]

    # Stage-1 chunk responses: each chunk picks 3 finalists.
    stage1_responses = [
        '{"finalists":["slug-0","slug-1","slug-2"],"reasoning":"r"}',
        '{"finalists":["slug-40","slug-41","slug-42"],"reasoning":"r"}',
    ]
    # Stage-2 picks slug-0 with its alert_id.
    stage2_response = (
        '{"decision":"post","event_slug":"slug-0",'
        '"alert_ids":[1],"reason":"sharp"}'
    )
    client = _FakeClient(stage1_responses + [stage2_response])

    with patch.object(articlebot, "fetch_24h_event_summaries", return_value=events), \
         patch.object(articlebot, "fetch_recent_article_slugs", return_value=[]):
        out = articlebot.pick_article_story(client)

    assert out["decision"] == "post"
    assert out["event_slug"] == "slug-0"
    assert out["alert_ids"] == [1]
    # 2 stage-1 calls + 1 stage-2 call = 3
    assert client.completions.calls == 3


def test_pick_article_story_skips_when_no_events():
    import articlebot
    client = _FakeClient([])
    with patch.object(articlebot, "fetch_24h_event_summaries", return_value=[]):
        out = articlebot.pick_article_story(client)
    assert out["decision"] == "skip"
    assert "no events" in out["reason"]


def test_fetch_recent_article_slugs_excludes_skipped_and_old():
    import articlebot
    rows = [
        {"event_slug": "covered-1"},
        {"event_slug": "covered-2"},
    ]
    with patch.object(articlebot, "query_postgres", return_value=rows) as q:
        out = articlebot.fetch_recent_article_slugs()
    assert out == ["covered-1", "covered-2"]
    sql = q.call_args.args[0]
    assert "status != 'skipped'" in sql
    assert "INTERVAL '7 days'" in sql


def test_run_agent_does_not_double_prefetch_when_kickoff_message_provided():
    """When run_agent receives a non-None kickoff_message, it must NOT call
    prefetch_bundle itself — the caller already ran it while building the
    kickoff.  (Issue 3 regression guard.)"""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import storybot

    chosen_alerts = [{
        "id": 1, "composite_score": 5.0, "alert_type": "composite",
        "market_title": "Test market", "wallet": "0xabc",
        "total_usd": 1000.0, "llm_headline": "test", "event_slug": "test-event",
        "condition_id": "0xc1234567",
    }]

    final_json = '{"decision":"skip","reason":"test","tweets":null,"alert_ids":null}'

    def _fake_response():
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=final_json, tool_calls=None),
            )],
            usage=SimpleNamespace(
                prompt_tokens=5, completion_tokens=5, total_tokens=10,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )

    fake_completions = MagicMock()
    fake_completions.create.return_value = _fake_response()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

    mock_prefetch = MagicMock(return_value={})
    with patch.object(storybot, "prefetch_bundle", mock_prefetch):
        storybot.run_agent(
            fake_client,
            chosen_alerts=chosen_alerts,
            kickoff_message="pre-built kickoff — no prefetch needed",
        )

    assert mock_prefetch.call_count == 0, (
        "prefetch_bundle should not be called when kickoff_message is supplied"
    )
