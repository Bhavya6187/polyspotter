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
