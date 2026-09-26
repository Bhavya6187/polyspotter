"""Tests for the draft-writing helper in twitter_pipeline.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_write_draft_live_writes_to_twitter_drafts_dir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(tmp_path / "live"))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", False)

    tp._write_draft("abc12345", "Hello, world.\n")

    written = (tmp_path / "live" / "abc12345.txt").read_text()
    assert written == "Hello, world.\n"
    assert not (tmp_path / "dry" / "abc12345.txt").exists()


def test_write_draft_dry_run_writes_to_dry_runs_subdir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(tmp_path / "live"))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", True)

    tp._write_draft("abc12345", "Dry run tweet body")

    written = (tmp_path / "dry" / "abc12345.txt").read_text()
    assert written == "Dry run tweet body"
    assert not (tmp_path / "live" / "abc12345.txt").exists()


def test_write_draft_creates_parent_dir(tmp_path, monkeypatch):
    import twitter_pipeline as tp

    target = tmp_path / "nested" / "twitter_drafts"
    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(target))
    monkeypatch.setattr(tp, "_DRY_RUN_TWITTER_DRAFTS_DIR", str(tmp_path / "dry"))
    monkeypatch.setattr(tp, "DRY_RUN", False)

    tp._write_draft("xyz98765", "body")

    assert (target / "xyz98765.txt").read_text() == "body"


def test_writer_prompt_carries_real_event_title(monkeypatch):
    # Bare market titles ("Will France win on 2026-07-14?") name neither the
    # opponent nor the tournament; the writer must see the Gamma event title.
    import digestbot
    import tweet_utils
    import twitter_pipeline as tp

    seed = [{"id": 7, "event_slug": "fifwc-fra-esp-2026-07-14", "condition_id": "0xc",
             "market_title": "Will France win on 2026-07-14?"}]
    monkeypatch.setattr(tp, "build_enriched_facts_bundle",
                        lambda chosen: ({"has_sharp_wallet": None}, []))
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", lambda cid: {})
    monkeypatch.setattr(digestbot, "fetch_event_titles",
                        lambda slugs: {"fifwc-fra-esp-2026-07-14": "France vs. Spain"})

    bundle = tp.fetch_data_bundle([7], seed)
    msg = tp._writer_user_message(bundle["chosen_alerts"], "summary",
                                  bundle["facts_bundle"], {"chart_type": "none"})
    assert "France vs. Spain" in msg


def test_no_track_record_closer_in_draft(tmp_path, monkeypatch):
    # The "Recent flags: X-Y." closer read result_tweets, which nothing has
    # written since the results loop retired (2026-06-16). Even with a winning
    # record available, the drafted tweet must be exactly the writer's text.
    import types

    import bot_utils
    import tweet_utils
    import twitter_pipeline as tp

    fake_store = types.ModuleType("result_store")
    fake_store.recent_record = lambda *a, **kw: (11, 4)
    monkeypatch.setitem(sys.modules, "result_store", fake_store)

    body = "A wallet just put $80k on Yes with the line at 12c. Who blinks first?"
    seed = [{"id": 7, "event_slug": "e", "condition_id": "0xc", "market_title": "M?"}]
    monkeypatch.setattr(bot_utils, "DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(bot_utils, "AZURE_OPENAI_API_KEY", "fake")
    monkeypatch.setattr(bot_utils, "fetch_seed_alerts", lambda: seed)
    monkeypatch.setattr(tp, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(tp, "DRY_RUN", False)
    monkeypatch.setattr(tp, "_cadence_skip_reason", lambda now, recent: None)
    monkeypatch.setattr(tweet_utils, "fetch_recent_tweets", lambda limit=10: [])
    monkeypatch.setattr(tweet_utils, "fetch_recent_tweet_openers", lambda limit=5: [])
    monkeypatch.setattr(tweet_utils, "filter_posted_alerts", lambda alerts: alerts)
    monkeypatch.setattr(tweet_utils, "prepare_chart_grid", lambda *a, **kw: None)
    monkeypatch.setattr(tp, "_apply_quality_floor", lambda alerts: (alerts, {
        "dropped": 0, "total_usd": 0, "non_sports": 0, "win_rate": 0, "price_move": 0}))
    monkeypatch.setattr(tp, "pick_event", lambda *a, **kw: {
        "decision": "post", "alert_ids": [7], "event_summary": "s", "reason": "r"})
    monkeypatch.setattr(tp, "fetch_data_bundle", lambda ids, seeds: {
        "chosen_alerts": seed, "trades": [], "token_map": {},
        "facts_bundle": {"has_sharp_wallet": None}})
    monkeypatch.setattr(tp, "pick_chart", lambda *a, **kw: {
        "chart_type": "none", "hook_anchor": "x", "reason": "r"})
    monkeypatch.setattr(tp, "validate_chart_pick", lambda pick: (True, ""))
    monkeypatch.setattr(tp, "write_tweet_with_retry", lambda *a, **kw: ({"tweet": body}, None, 1))
    monkeypatch.setattr(tp, "_RUN_OUTPUT_DIR", str(tmp_path / "live_runs"))
    monkeypatch.setattr(tp, "_TWITTER_DRAFTS_DIR", str(tmp_path / "drafts"))
    monkeypatch.setattr(tp, "_dump_transcript", lambda run_id, transcript: None)

    assert tp.main() == 0
    drafts = list((tmp_path / "drafts").iterdir())
    assert len(drafts) == 1
    text = drafts[0].read_text()
    assert "Recent flags" not in text
    assert text.strip() == body
    assert not hasattr(tp, "_attach_track_record_closer")
    assert not hasattr(tweet_utils, "format_track_record_closer")
