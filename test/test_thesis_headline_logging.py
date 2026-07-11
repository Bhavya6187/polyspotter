"""
Tests that _generate_thesis_headline logs its prompt to the shared
llm_prompts.jsonl log — the same per-call log every other scanner GPT
call goes through (see llm_filter._log_prompt).
"""

import json
from unittest.mock import patch, MagicMock

import llm_filter
from seeder import _generate_thesis_headline


def _thesis():
    return {
        "wallet": "0xabc",
        "event_slug": "test-event",
        "markets": [
            {"market_title": "Will X happen?", "side": "BUY", "outcome": "Yes"},
        ],
        "total_usd": 12345.0,
    }


def _fake_openai_client():
    client = MagicMock()
    client.responses.create.return_value = MagicMock(output_text="X will happen")
    return client


def test_headline_call_is_logged(tmp_path, monkeypatch):
    log_file = tmp_path / "llm_prompts.jsonl"
    monkeypatch.setattr(llm_filter, "PROMPT_LOG_FILE", log_file)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test/v1")
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-test")

    with patch("openai.OpenAI", return_value=_fake_openai_client()):
        headline = _generate_thesis_headline(_thesis())

    assert headline == "X will happen"
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model"] == "gpt-test"
    assert entry["cache_key"] == "thesis:0xabc:test-event"
    assert "Will X happen?" in entry["messages"][-1]["content"]


def test_no_api_key_makes_no_call_and_no_log(tmp_path, monkeypatch):
    log_file = tmp_path / "llm_prompts.jsonl"
    monkeypatch.setattr(llm_filter, "PROMPT_LOG_FILE", log_file)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    assert _generate_thesis_headline(_thesis()) is None
    assert not log_file.exists()
