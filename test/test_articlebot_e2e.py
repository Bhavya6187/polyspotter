"""End-to-end smoke test for articlebot.main()."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def _make_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=None),
        )],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            prompt_tokens_details=None, completion_tokens_details=None,
        ),
    )


_VALID_BODY = (
    "Opening paragraph that hooks the reader with stakes baked in.\n\n"
    "## The wallet\n\n" + " ".join(["w"] * 200) + "\n\n"
    "## The bet\n\n" + " ".join(["w"] * 200) + "\n\n"
    "## What to watch\n\n" + " ".join(["w"] * 150) + "\n\n"
    "Watch [the market](https://polyspotter.com/market/foo)."
)


_FINAL_DECISION_JSON = json.dumps({
    "decision": "post",
    "reason": "sharp wallet at the buzzer",
    "article": {
        "headline": "A sharp wallet just bought into a forgotten market",
        "subhead": "An account up $2M lifetime is dropping size on a coin-flip",
        "body_markdown": _VALID_BODY,
        "cover_alt_text": "wallet record card",
    },
    "alert_ids": [42],
    "cover_chart_spec": {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}},
})


_PICK_STAGE1 = '{"finalists":["alive-event"],"reasoning":"r"}'
_PICK_STAGE2 = '{"decision":"post","event_slug":"alive-event","alert_ids":[42],"reason":"r"}'


def test_articlebot_main_e2e_post(tmp_path, monkeypatch):
    """End-to-end: tournament picker → agent → validation → persistence.

    All LLM, Postgres, and chart calls are stubbed. The test asserts:
    - The .md file exists with the right content.
    - persist_article was called.
    - The exit code is 0.
    """
    import articlebot
    import articlebot_storage as st

    # Stub event summaries (skips the SQL + Gamma calls)
    events = [{
        "event_slug": "alive-event",
        "top_composite": 9.0, "event_usd": 5000.0, "alert_count": 1,
        "strategies_fired": ["win_rate_tracking"],
        "alerts": [{
            "id": 42, "composite_score": 9.0, "alert_type": "composite",
            "market_title": "Will X happen", "wallet": "0xabc",
            "total_usd": 5000.0, "llm_headline": "sharp wallet on No",
            "condition_id": "0xc1234567",
        }],
        "first_alert_at": None, "last_alert_at": None,
        "top_condition_id": "0xc1234567",
    }]

    monkeypatch.setattr(articlebot, "fetch_24h_event_summaries", lambda: events)
    monkeypatch.setattr(articlebot, "fetch_recent_article_slugs", lambda: [])

    # Stub the LLM: stage-1 → stage-2 → research-agent (returns final JSON, no tool calls)
    llm_responses = iter([
        _make_llm_response(_PICK_STAGE1),
        _make_llm_response(_PICK_STAGE2),
        _make_llm_response(_FINAL_DECISION_JSON),
    ])
    fake_completions = MagicMock()
    fake_completions.create = lambda **_kw: next(llm_responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
    monkeypatch.setattr(articlebot, "OpenAI", lambda **_kw: fake_client)

    # Stub storybot's prefetch + dispatcher (no real Postgres / Gamma during agent)
    import storybot
    monkeypatch.setattr(storybot, "prefetch_bundle", lambda scope: {})

    # Stub chart render to drop a fake PNG
    def _fake_render(chart_type, alert):
        return b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _fake_render)

    # Redirect storage to tmp_path
    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    # Required env vars
    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("DRY_RUN", "false")

    # Also patch the module-level attribute directly (env var may have been read at import time)
    monkeypatch.setattr(articlebot, "DRY_RUN", False)

    rc = articlebot.main()

    assert rc == 0, "main should return 0 on success"

    # The .md file landed in tmp_path
    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    md_text = md_files[0].read_text()
    assert "# A sharp wallet just bought into a forgotten market" in md_text
    assert "polyspotter.com/market/foo" in md_text

    # The PNG landed
    png_files = list(tmp_path.glob("*.png"))
    assert len(png_files) == 1

    # Postgres INSERT was issued
    fake_cur.execute.assert_called()
    insert_sqls = [c.args[0] for c in fake_cur.execute.call_args_list
                   if "INSERT INTO articles" in c.args[0]]
    assert insert_sqls, "expected an INSERT INTO articles call"


# ---------------------------------------------------------------------------
# Validation-retry tests
# ---------------------------------------------------------------------------

# A decision whose body is too short (fails word-count validation)
_SHORT_BODY = (
    "Opening paragraph.\n\n"
    "## Section\n\n" + " ".join(["w"] * 50) + "\n\n"
    "Watch [the market](https://polyspotter.com/market/foo)."
)

_INVALID_DECISION_JSON = json.dumps({
    "decision": "post",
    "reason": "sharp wallet",
    "article": {
        "headline": "A sharp wallet just bought into a forgotten market",
        "subhead": "An account up $2M lifetime is dropping size on a coin-flip",
        "body_markdown": _SHORT_BODY,
        "cover_alt_text": "wallet record card",
    },
    "alert_ids": [42],
    "cover_chart_spec": {"chart_type": "wallet_record_card", "alert_id": 42, "params": {}},
})


def _make_validation_retry_harness(monkeypatch, tmp_path, agent_response, retry_response):
    """Shared fixture setup for validation-retry tests."""
    import articlebot
    import articlebot_storage as st
    import storybot

    events = [{
        "event_slug": "alive-event",
        "top_composite": 9.0, "event_usd": 5000.0, "alert_count": 1,
        "strategies_fired": ["win_rate_tracking"],
        "alerts": [{
            "id": 42, "composite_score": 9.0, "alert_type": "composite",
            "market_title": "Will X happen", "wallet": "0xabc",
            "total_usd": 5000.0, "llm_headline": "sharp wallet on No",
            "condition_id": "0xc1234567",
        }],
        "first_alert_at": None, "last_alert_at": None,
        "top_condition_id": "0xc1234567",
    }]

    monkeypatch.setattr(articlebot, "fetch_24h_event_summaries", lambda: events)
    monkeypatch.setattr(articlebot, "fetch_recent_article_slugs", lambda: [])

    # Stage 1 and 2 (picker) responses, then the agent response, then the retry
    llm_responses = iter([
        _make_llm_response(_PICK_STAGE1),
        _make_llm_response(_PICK_STAGE2),
        _make_llm_response(agent_response),
        _make_llm_response(retry_response),
    ])
    fake_completions = MagicMock()
    fake_completions.create = lambda **_kw: next(llm_responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
    monkeypatch.setattr(articlebot, "OpenAI", lambda **_kw: fake_client)

    monkeypatch.setattr(storybot, "prefetch_bundle", lambda scope: {})

    def _fake_render(chart_type, alert):
        return b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(articlebot, "_dispatch_chart_render", _fake_render)

    monkeypatch.setattr(st, "ARTICLES_DIR", str(tmp_path))
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    monkeypatch.setattr(st, "_get_conn", lambda: fake_conn)

    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(articlebot, "DRY_RUN", False)

    return fake_cur


def test_articlebot_validation_retry_succeeds(tmp_path, monkeypatch):
    """First agent call returns an article with a body that's too short
    (fails word-count validation); second call (the retry) returns a valid
    ~600-word body. main() must return 0 and the .md file must land."""
    import articlebot

    fake_cur = _make_validation_retry_harness(
        monkeypatch, tmp_path,
        agent_response=_INVALID_DECISION_JSON,  # fails validation
        retry_response=_FINAL_DECISION_JSON,    # passes validation
    )

    rc = articlebot.main()

    assert rc == 0, "main should return 0 when the retry succeeds"

    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    md_text = md_files[0].read_text()
    assert "A sharp wallet just bought into a forgotten market" in md_text

    insert_sqls = [c.args[0] for c in fake_cur.execute.call_args_list
                   if "INSERT INTO articles" in c.args[0]]
    assert insert_sqls, "expected an INSERT INTO articles call"


def test_articlebot_validation_retry_still_fails(tmp_path, monkeypatch):
    """Both the agent call and the retry return an article with a body that's
    too short. main() must return 1 and record a skipped row with 'validation:'
    in the reason."""
    import articlebot

    fake_cur = _make_validation_retry_harness(
        monkeypatch, tmp_path,
        agent_response=_INVALID_DECISION_JSON,   # fails validation
        retry_response=_INVALID_DECISION_JSON,   # still fails
    )

    rc = articlebot.main()

    assert rc == 1, "main should return 1 when both attempts fail validation"

    # A skipped row with 'validation:' in the reason must be recorded.
    # record_skipped_run stores the reason in the subhead column (params[4]).
    all_execute_args = [c.args for c in fake_cur.execute.call_args_list]
    insert_calls = [
        args for args in all_execute_args
        if args and "INSERT INTO articles" in args[0]
    ]
    assert insert_calls, "expected an INSERT INTO articles call for the skipped row"
    reason_found = any(
        "validation:" in str(v)
        for args in insert_calls
        for v in (args[1] if len(args) > 1 else [])
    )
    assert reason_found, "expected 'validation:' in the skipped row's reason/subhead"
