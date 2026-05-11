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
