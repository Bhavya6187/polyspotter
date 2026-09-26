"""
The thesis-headline GPT call runs with reasoning.effort=none and records its
token usage (2026-09-26 cost review). The call ran 7x the alert-eval volume
and spent ~53 of its ~74 output tokens reasoning about a 3-6 word headline;
replaying at effort=none produced equivalent headlines at ~10 output tokens.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import db
import llm_filter
from seeder import _generate_thesis_headline


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "polybot.db"))
    monkeypatch.setattr(db, "_conn", None)
    yield
    if db._conn is not None:
        db._conn.close()


@pytest.fixture
def gpt(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_filter, "PROMPT_LOG_FILE", tmp_path / "llm_prompts.jsonl")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test/v1")
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-test")
    usage = MagicMock()
    usage.input_tokens = 80
    usage.input_tokens_details.cached_tokens = 0
    usage.output_tokens = 10
    usage.output_tokens_details.reasoning_tokens = 0
    client = MagicMock()
    client.responses.create.return_value = MagicMock(output_text="Iran talks will collapse", usage=usage)
    with patch("openai.OpenAI", return_value=client):
        yield client


def _thesis():
    return {
        "wallet": "0xabc",
        "event_slug": "iran-talks",
        "markets": [
            {"condition_id": "c1", "market_title": "Will talks collapse?", "side": "BUY", "outcome": "Yes"},
        ],
        "total_usd": 5000.0,
    }


def test_thesis_call_uses_no_reasoning(fresh_db, gpt):
    _generate_thesis_headline(_thesis())

    assert gpt.responses.create.call_args.kwargs["reasoning"] == {"effort": "none"}


def test_thesis_usage_is_recorded(fresh_db, gpt):
    _generate_thesis_headline(_thesis())

    rows = db.get_llm_usage_by_day(days=1)
    assert rows == [{
        "day": datetime.now(timezone.utc).date().isoformat(), "kind": "thesis_headline",
        "calls": 1, "prompt_tokens": 80, "cached_tokens": 0,
        "completion_tokens": 10, "reasoning_tokens": 0,
    }]
