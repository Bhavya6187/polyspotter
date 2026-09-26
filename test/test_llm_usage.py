"""
Per-call GPT token usage is persisted in polybot.db (llm_usage table) so
spend can be tracked by call type and day. Before the 2026-09-26 cost
review only failed calls (llm_failures.jsonl) recorded token counts; every
cost figure had to be reconstructed by replaying prompts.
"""

from datetime import datetime, timedelta, timezone

import pytest

import db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "polybot.db"))
    monkeypatch.setattr(db, "_conn", None)
    yield
    if db._conn is not None:
        db._conn.close()


USAGE = {"prompt_tokens": 3000, "cached_tokens": 2700, "completion_tokens": 600, "reasoning_tokens": 300}


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def test_usage_is_summed_per_day_and_kind(fresh_db):
    db.record_llm_usage("alert_eval", "gpt-test", "k1", USAGE)
    db.record_llm_usage("alert_eval", "gpt-test", "k2", USAGE)
    db.record_llm_usage("thesis_headline", "gpt-test", "t1",
                        {"prompt_tokens": 80, "cached_tokens": 0, "completion_tokens": 10, "reasoning_tokens": 0})

    rows = db.get_llm_usage_by_day(days=7)

    assert rows == [
        {"day": _today(), "kind": "alert_eval", "calls": 2, "prompt_tokens": 6000,
         "cached_tokens": 5400, "completion_tokens": 1200, "reasoning_tokens": 600},
        {"day": _today(), "kind": "thesis_headline", "calls": 1, "prompt_tokens": 80,
         "cached_tokens": 0, "completion_tokens": 10, "reasoning_tokens": 0},
    ]


def test_summary_window_excludes_older_rows(fresh_db):
    db.record_llm_usage("alert_eval", "gpt-test", "k-new", USAGE)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    db.get_db().execute(
        """INSERT INTO llm_usage (ts, kind, model, cache_key, prompt_tokens, cached_tokens,
                                  completion_tokens, reasoning_tokens)
           VALUES (?, 'alert_eval', 'gpt-test', 'k-old', 1, 1, 1, 1)""",
        (old_ts,),
    )
    db.get_db().commit()

    rows = db.get_llm_usage_by_day(days=7)

    assert [r["calls"] for r in rows] == [1]
    assert len(db.get_llm_usage_by_day(days=30)) == 2


def test_missing_usage_fields_default_to_zero(fresh_db):
    db.record_llm_usage("alert_eval", "gpt-test", "k1", {})

    rows = db.get_llm_usage_by_day(days=1)

    assert rows[0]["calls"] == 1
    assert rows[0]["prompt_tokens"] == 0
    assert rows[0]["completion_tokens"] == 0
