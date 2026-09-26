"""
Thesis headlines are cached in polybot.db (thesis_headlines table) keyed by
(wallet, event_slug, sorted condition_ids), so a thesis that has not changed
costs no GPT call on later scans and keeps a stable headline. Adding a market
to the thesis changes the key and triggers a fresh headline.
"""

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
    client = MagicMock()
    client.responses.create.side_effect = [
        MagicMock(output_text="Iran talks will collapse"),
        MagicMock(output_text="A different headline"),
    ]
    with patch("openai.OpenAI", return_value=client):
        yield client


def _thesis(cids):
    return {
        "wallet": "0xabc",
        "event_slug": "iran-talks",
        "markets": [
            {"condition_id": c, "market_title": f"Market {c}", "side": "BUY", "outcome": "Yes"}
            for c in cids
        ],
        "total_usd": 5000.0,
    }


def test_thesis_headline_cached_across_runs(fresh_db, gpt):
    first = _generate_thesis_headline(_thesis(["c2", "c1"]))
    # Same markets in a different order: same cache key.
    second = _generate_thesis_headline(_thesis(["c1", "c2"]))

    assert first == "Iran talks will collapse"
    assert second == first
    assert gpt.responses.create.call_count == 1


def test_thesis_headline_cache_key_changes_with_new_market(fresh_db, gpt):
    first = _generate_thesis_headline(_thesis(["c1", "c2"]))
    second = _generate_thesis_headline(_thesis(["c1", "c2", "c3"]))

    assert gpt.responses.create.call_count == 2
    assert first == "Iran talks will collapse"
    assert second == "A different headline"


def test_failed_headline_is_not_cached(fresh_db, gpt):
    gpt.responses.create.side_effect = [
        RuntimeError("azure down"),
        MagicMock(output_text="Iran talks will collapse"),
    ]
    assert _generate_thesis_headline(_thesis(["c1", "c2"])) is None
    assert _generate_thesis_headline(_thesis(["c1", "c2"])) == "Iran talks will collapse"
    assert gpt.responses.create.call_count == 2


def _thesis_with(side, outcome, wallet="0xabc"):
    t = _thesis(["c1", "c2"])
    t["wallet"] = wallet
    for m in t["markets"]:
        m["side"] = side
        m["outcome"] = outcome
    return t


def test_thesis_cache_key_changes_when_direction_flips(fresh_db, gpt):
    # Same wallet/event/markets but the trader flipped sides: the prompt
    # differs, so the cached headline must not be reused.
    first = _generate_thesis_headline(_thesis_with("BUY", "Yes"))
    second = _generate_thesis_headline(_thesis_with("BUY", "No"))

    assert gpt.responses.create.call_count == 2
    assert first == "Iran talks will collapse"
    assert second == "A different headline"


def test_thesis_cache_key_same_direction_still_hits(fresh_db, gpt):
    first = _generate_thesis_headline(_thesis_with("SELL", "No"))
    second = _generate_thesis_headline(_thesis_with("SELL", "No"))

    assert gpt.responses.create.call_count == 1
    assert second == first


def test_thesis_cache_key_is_wallet_case_insensitive(fresh_db, gpt):
    first = _generate_thesis_headline(_thesis_with("BUY", "Yes", wallet="0xABC"))
    second = _generate_thesis_headline(_thesis_with("BUY", "Yes", wallet="0xabc"))

    assert gpt.responses.create.call_count == 1
    assert second == first


def test_cache_read_error_is_treated_as_miss(fresh_db, gpt, monkeypatch):
    import sqlite3

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "get_thesis_headline", locked)
    assert _generate_thesis_headline(_thesis(["c1", "c2"])) == "Iran talks will collapse"
    assert gpt.responses.create.call_count == 1


def test_cache_write_error_still_returns_headline(fresh_db, gpt, monkeypatch):
    import sqlite3

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "save_thesis_headline", locked)
    assert _generate_thesis_headline(_thesis(["c1", "c2"])) == "Iran talks will collapse"
