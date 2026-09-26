"""Tests for storybot/publish_tweet.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


_TWEET_BODY = (
    "A 31-day-old wallet just dropped $80k at 12c on a coin-flip. "
    "Resolution hits in 14 hours."
)


def _write_fixture_files(tmp_path, run_id, *, tweet=_TWEET_BODY,
                         publish_meta=None, write_chart=True):
    """Lay out a draft .txt + transcript .json (+ optional chart .png) on
    disk under tmp_path and return the dir paths so the test can monkeypatch
    publish_tweet's constants to point here."""
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()

    (drafts_dir / f"{run_id}.txt").write_text(tweet)

    chart_path = None
    if write_chart:
        chart_path = str(live_dir / f"twitter_pipeline_{run_id}.png")
        Path(chart_path).write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")

    pm = publish_meta if publish_meta is not None else {
        "alert_ids": [42, 43],
        "chart_type": "fresh_wallet_card",
        "target_alert_id": 42,
        "chart_png_path": chart_path,
        "recent_openers": [],
        "recent_tweets": [],
    }
    transcript = {"run_id": run_id, "stages": {}, "publish_meta": pm}
    (live_dir / f"twitter_pipeline_{run_id}.json").write_text(json.dumps(transcript))

    return drafts_dir, live_dir


def _patch_publisher(monkeypatch, drafts_dir, live_dir):
    import publish_tweet as pt
    monkeypatch.setattr(pt, "TWITTER_DRAFTS_DIR", str(drafts_dir))
    monkeypatch.setattr(pt, "LIVE_RUNS_DIR", str(live_dir))
    return pt


def test_publish_tweet_happy_path_posts_and_records(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())

    posted = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        posted["text"] = text
        posted["media_png"] = media_png
        posted["dry_run"] = dry_run
        return "1234567890"
    monkeypatch.setattr(pt, "post_tweet", fake_post_tweet)

    recorded = {}
    def fake_record_tweet(alert_ids, tweet_id, tweet_text):
        recorded["alert_ids"] = alert_ids
        recorded["tweet_id"] = tweet_id
        recorded["tweet_text"] = tweet_text
    monkeypatch.setattr(pt, "record_tweet", fake_record_tweet)

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert posted["text"] == _TWEET_BODY
    assert posted["media_png"] == b"\x89PNG\r\n\x1a\nfakebytes"
    assert posted["dry_run"] is False
    assert recorded == {
        "alert_ids": [42, 43],
        "tweet_id": "1234567890",
        "tweet_text": _TWEET_BODY,
    }


def test_publish_tweet_missing_draft_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["nodraft9"])
    assert rc == 1


def test_publish_tweet_missing_transcript_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    (drafts_dir / "abc12345.txt").write_text(_TWEET_BODY)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["abc12345"])
    assert rc == 1


def test_publish_tweet_missing_publish_meta_returns_1(tmp_path, monkeypatch):
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    (drafts_dir / "abc12345.txt").write_text(_TWEET_BODY)
    (live_dir / "twitter_pipeline_abc12345.json").write_text(
        json.dumps({"run_id": "abc12345", "stages": {}})  # no publish_meta
    )
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    rc = pt.main(["abc12345"])
    assert rc == 1


def test_publish_tweet_publish_meta_missing_keys_returns_1(tmp_path, monkeypatch):
    # publish_meta present but missing a required key (chart_png_path)
    drafts_dir = tmp_path / "twitter_drafts"
    live_dir = tmp_path / "live_runs"
    drafts_dir.mkdir()
    live_dir.mkdir()
    (drafts_dir / "abc12345.txt").write_text(_TWEET_BODY)
    transcript = {
        "run_id": "abc12345",
        "stages": {},
        "publish_meta": {
            "alert_ids": [42],
            "chart_type": "fresh_wallet_card",
            "target_alert_id": 42,
            # chart_png_path intentionally omitted
        },
    }
    (live_dir / "twitter_pipeline_abc12345.json").write_text(json.dumps(transcript))
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)

    called = {"post": False}
    monkeypatch.setattr(pt, "post_tweet",
                        lambda *a, **kw: called.__setitem__("post", True) or "x")
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

    rc = pt.main(["abc12345"])
    assert rc == 1
    assert called["post"] is False


def test_publish_tweet_chart_png_missing_file_returns_1(tmp_path, monkeypatch):
    # publish_meta.chart_png_path points at a path that does not exist
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", write_chart=False,
    )
    transcript_path = live_dir / "twitter_pipeline_abc12345.json"
    transcript = json.loads(transcript_path.read_text())
    transcript["publish_meta"]["chart_png_path"] = str(tmp_path / "nowhere.png")
    transcript_path.write_text(json.dumps(transcript))

    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    called = {"post": False}
    monkeypatch.setattr(pt, "post_tweet",
                        lambda *a, **kw: called.__setitem__("post", True) or "x")
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock())

    rc = pt.main(["abc12345"])
    assert rc == 1
    assert called["post"] is False


def test_publish_tweet_validation_failure_does_not_post(tmp_path, monkeypatch):
    # Tweet over 280 chars — validate_tweet should reject.
    long_tweet = "x" * 281
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", tweet=long_tweet, write_chart=False,
    )
    # Update the transcript's chart_png_path to null since we didn't write one.
    transcript_path = live_dir / "twitter_pipeline_abc12345.json"
    transcript = json.loads(transcript_path.read_text())
    transcript["publish_meta"]["chart_png_path"] = None
    transcript_path.write_text(json.dumps(transcript))

    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    called = {"post": False}
    monkeypatch.setattr(pt, "post_tweet",
                        lambda *a, **kw: called.__setitem__("post", True) or "x")
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())

    rc = pt.main(["abc12345"])
    assert rc == 1
    assert called["post"] is False


def test_publish_tweet_no_chart_png_path_posts_without_media(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", write_chart=False,
    )
    transcript_path = live_dir / "twitter_pipeline_abc12345.json"
    transcript = json.loads(transcript_path.read_text())
    transcript["publish_meta"]["chart_png_path"] = None
    transcript_path.write_text(json.dumps(transcript))

    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    v1_built = {"built": False}
    def fake_v1():
        v1_built["built"] = True
        return MagicMock()
    monkeypatch.setattr(pt, "_build_twitter_api_v1", fake_v1)

    posted = {}
    def fake_post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run):
        posted["media_png"] = media_png
        posted["v1"] = twitter_api_v1
        return "1234567890"
    monkeypatch.setattr(pt, "post_tweet", fake_post_tweet)
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert posted["media_png"] is None
    assert posted["v1"] is None
    assert v1_built["built"] is False


def _patch_clients(monkeypatch, pt):
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())


def test_posted_sidecar_written_before_record(tmp_path, monkeypatch):
    # The tweet is live once post_tweet returns; if recording it fails the
    # draft must survive (with the tweet id) so a re-run records instead of
    # the loop deleting the draft and losing dedup/cadence state.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")

    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(pt, "record_tweet", boom)

    rc = pt.main(["abc12345"])
    assert rc != 0
    assert (drafts_dir / "abc12345.txt").exists()
    lines = (drafts_dir / "abc12345.txt.posted").read_text().splitlines()
    assert lines[0].strip() == "1234567890"
    # The sidecar also carries the alert ids, so a retry can record without
    # the transcript (live_runs entries are pruned after 30 days).
    assert json.loads(lines[1]) == [42, 43]


def test_rerun_with_posted_sidecar_does_not_repost(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    (drafts_dir / "abc12345.txt.posted").write_text("1234567890\n")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)

    def no_post(*a, **kw):
        raise AssertionError("must not post again")
    monkeypatch.setattr(pt, "post_tweet", no_post)
    recorded = {}
    monkeypatch.setattr(pt, "record_tweet",
                        lambda ids, tid, text: recorded.update(ids=ids, tid=tid, text=text))

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert recorded == {"ids": [42, 43], "tid": "1234567890", "text": _TWEET_BODY}
    assert not (drafts_dir / "abc12345.txt").exists()
    assert not (drafts_dir / "abc12345.txt.posted").exists()


def _no_post(*a, **kw):
    raise AssertionError("must not post again")


def test_posted_sidecar_records_without_transcript(tmp_path, monkeypatch):
    # The transcript was pruned (live_runs > 30 days): the .posted retry must
    # still record from the draft + sidecar alone, never post, and clean up.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345", write_chart=False)
    (drafts_dir / "abc12345.txt.posted").write_text("1234567890\n[42, 43]\n")
    import shutil
    shutil.rmtree(live_dir)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", _no_post)
    recorded = {}
    monkeypatch.setattr(pt, "record_tweet",
                        lambda ids, tid, text: recorded.update(ids=ids, tid=tid, text=text))

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert recorded == {"ids": [42, 43], "tid": "1234567890", "text": _TWEET_BODY}
    assert not (drafts_dir / "abc12345.txt").exists()
    assert not (drafts_dir / "abc12345.txt.posted").exists()


def test_truncated_posted_sidecar_without_transcript_records_degraded(tmp_path, monkeypatch):
    # A sidecar whose line 2 is corrupt or truncated holds only the tweet id.
    # With the transcript gone there are no alert ids to record: record_tweet
    # still runs (no rows), the draft is cleared, exit 0 instead of failing
    # forever. Zero alert rows means this tweet is invisible to the cadence
    # gate and dedup.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345", write_chart=False)
    (drafts_dir / "abc12345.txt.posted").write_text("1234567890\n")
    import shutil
    shutil.rmtree(live_dir)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", _no_post)
    recorded = {}
    monkeypatch.setattr(pt, "record_tweet",
                        lambda ids, tid, text: recorded.update(ids=ids, tid=tid, text=text))

    rc = pt.main(["abc12345"])
    assert rc == 0
    assert recorded == {"ids": [], "tid": "1234567890", "text": _TWEET_BODY}
    assert not (drafts_dir / "abc12345.txt").exists()
    assert not (drafts_dir / "abc12345.txt.posted").exists()


@pytest.mark.parametrize("make_exc", [
    lambda: __import__("http.client").client.RemoteDisconnected(
        "Remote end closed connection without response"),
    lambda: __import__("tweepy").errors.TwitterServerError(
        MagicMock(status_code=503, reason="Service Unavailable",
                  json=lambda: {}, text="")),
])
def test_ambiguous_post_error_marks_pending(tmp_path, monkeypatch, make_exc):
    # The request may have reached X: never treat it as "not posted".
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    exc = make_exc()

    def raise_it(*a, **kw):
        raise exc
    monkeypatch.setattr(pt, "post_tweet", raise_it)
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)

    rc = pt.main(["abc12345"])
    assert rc != 0
    assert (drafts_dir / "abc12345.txt").exists()
    assert (drafts_dir / "abc12345.txt.pending").exists()

    # A re-run must refuse to post while the marker exists.
    monkeypatch.setattr(pt, "post_tweet",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("reposted")))
    assert pt.main(["abc12345"]) != 0


def test_definite_post_error_is_not_pending(tmp_path, monkeypatch):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    import tweepy
    exc = tweepy.errors.Forbidden(MagicMock(status_code=403, reason="Forbidden",
                                            json=lambda: {}, text=""))

    def raise_it(*a, **kw):
        raise exc
    monkeypatch.setattr(pt, "post_tweet", raise_it)
    assert pt.main(["abc12345"]) == 1
    assert not (drafts_dir / "abc12345.txt.pending").exists()


def test_publish_tweet_bad_argv_returns_2(monkeypatch):
    import publish_tweet as pt
    assert pt.main([]) == 2
    assert pt.main(["a", "b"]) == 2


def test_publish_tweet_honors_dry_run(tmp_path, monkeypatch):
    """DRY_RUN=true must never post or record; the draft stays on disk.
    publish_article.py already behaves this way; publish_tweet hardcoded
    dry_run=False, so `DRY_RUN=true python storybot/publish_tweet.py <id>`
    posted for real."""
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setattr(pt, "_build_twitter_client", lambda: MagicMock())
    monkeypatch.setattr(pt, "_build_twitter_api_v1", lambda: MagicMock())

    posted = {}
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: posted.setdefault("called", True))
    recorded = {}
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: recorded.setdefault("called", True))

    rc = pt.main(["abc12345"])

    assert rc == 0
    assert posted == {}
    assert recorded == {}
    assert (drafts_dir / "abc12345.txt").exists()


def test_alert_ids_accept_numeric_strings(tmp_path, monkeypatch):
    # The picker LLM sometimes returns ids as strings; validate_event_pick
    # accepted "123" but publish_tweet rejected it after the paid edit step.
    import twitter_pipeline
    pick = {"decision": "post", "alert_ids": ["42", 43],
            "event_summary": "Informed flow on Yes."}
    ok, err = twitter_pipeline.validate_event_pick(pick, [{"id": 42}, {"id": 43}])
    assert ok, err
    assert pick["alert_ids"] == [42, 43]

    publish_meta = {"alert_ids": pick["alert_ids"], "chart_type": "none",
                    "target_alert_id": 42, "chart_png_path": None}
    drafts_dir, live_dir = _write_fixture_files(
        tmp_path, "abc12345", publish_meta=publish_meta, write_chart=False)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "999")
    recorded = {}
    monkeypatch.setattr(pt, "record_tweet", lambda ids, tid, text: recorded.update(ids=ids))
    assert pt.main(["abc12345"]) == 0
    assert recorded["ids"] == [42, 43]


def _fail_posted_write(monkeypatch, pt):
    """Make writing <draft>.posted raise OSError; every other open is real."""
    import builtins
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if str(path).endswith(".posted") and "w" in mode:
            raise OSError(28, "No space left on device")
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr(pt, "open", fake_open, raising=False)


def test_posted_write_failure_writes_pending_and_warns_not_to_rerun(
        tmp_path, monkeypatch, capsys):
    # Tweet is live, .posted cannot be written and record_tweet fails: with no
    # .posted marker a re-run WOULD post again, so a .pending marker must
    # block it and the message must not claim a re-run is safe.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")
    _fail_posted_write(monkeypatch, pt)

    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(pt, "record_tweet", boom)

    rc = pt.main(["abc12345"])
    err = capsys.readouterr().err
    assert rc != 0
    assert not (drafts_dir / "abc12345.txt.posted").exists()
    assert (drafts_dir / "abc12345.txt.pending").exists()
    assert "do NOT re-run" in err
    assert "1234567890" in err
    assert "will not re-post" not in err

    # And a re-run really does refuse to post.
    monkeypatch.setattr(pt, "post_tweet", _no_post)
    assert pt.main(["abc12345"]) != 0


def test_record_failure_with_posted_marker_says_rerun_records(
        tmp_path, monkeypatch, capsys):
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")

    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(pt, "record_tweet", boom)

    assert pt.main(["abc12345"]) != 0
    err = capsys.readouterr().err
    assert "records without posting" in err
    assert "do NOT re-run" not in err
    assert not (drafts_dir / "abc12345.txt.pending").exists()


@pytest.mark.parametrize("content", ["", "\n", "   \n[42, 43]\n"])
def test_posted_sidecar_with_empty_tweet_id_returns_1(tmp_path, monkeypatch, content):
    # An empty/truncated .posted must not record rows with an empty tweet id
    # and delete the draft; leave everything for an operator.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    (drafts_dir / "abc12345.txt.posted").write_text(content)
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", _no_post)

    calls = []
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: calls.append(a))

    assert pt.main(["abc12345"]) == 1
    assert calls == []  # never records rows with an empty tweet id
    assert (drafts_dir / "abc12345.txt").exists()
    assert (drafts_dir / "abc12345.txt.posted").exists()


def test_orphan_posted_marker_without_draft_is_cleared(tmp_path, monkeypatch):
    # A crash between deleting the draft and deleting .posted leaves an orphan
    # marker; the record already succeeded, so treat it as done.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    (drafts_dir / "abc12345.txt").unlink()
    (drafts_dir / "abc12345.txt.posted").write_text("1234567890\n[42, 43]\n")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", _no_post)

    def no_record(*a, **kw):
        raise AssertionError("must not record again")
    monkeypatch.setattr(pt, "record_tweet", no_record)

    assert pt.main(["abc12345"]) == 0
    assert not (drafts_dir / "abc12345.txt.posted").exists()


def test_posted_write_failure_then_record_success_leaves_no_markers(tmp_path, monkeypatch):
    # The fallback .pending only exists to block a re-post while the tweet is
    # unrecorded; once record_tweet succeeds it must go with the draft.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")
    _fail_posted_write(monkeypatch, pt)
    monkeypatch.setattr(pt, "record_tweet", lambda *a, **kw: None)

    assert pt.main(["abc12345"]) == 0
    assert sorted(p.name for p in drafts_dir.iterdir()) == []


def test_posted_and_pending_write_failure_message(tmp_path, monkeypatch, capsys):
    # If even the fallback .pending cannot be written, say so: nothing on disk
    # blocks a re-post.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")
    import builtins
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if str(path).endswith((".posted", ".pending")) and "w" in mode:
            raise OSError(28, "No space left on device")
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr(pt, "open", fake_open, raising=False)
    monkeypatch.setattr(pt, "record_tweet",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db down")))

    assert pt.main(["abc12345"]) != 0
    err = capsys.readouterr().err
    assert "do NOT re-run" in err
    assert ".pending marker was written" not in err
    assert "could not be written either" in err


def test_partial_posted_write_is_removed(tmp_path, monkeypatch, capsys):
    # open() succeeded but write() failed: a truncated .posted must not stay
    # behind claiming a re-run is safe.
    drafts_dir, live_dir = _write_fixture_files(tmp_path, "abc12345")
    pt = _patch_publisher(monkeypatch, drafts_dir, live_dir)
    _patch_clients(monkeypatch, pt)
    monkeypatch.setattr(pt, "post_tweet", lambda *a, **kw: "1234567890")
    import builtins
    real_open = builtins.open

    class Truncating:
        def __init__(self, f):
            self.f = f
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.f.close()
        def write(self, data):
            raise OSError(28, "No space left on device")

    def fake_open(path, mode="r", *a, **kw):
        if str(path).endswith(".posted") and "w" in mode:
            return Truncating(real_open(path, mode, *a, **kw))
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr(pt, "open", fake_open, raising=False)
    monkeypatch.setattr(pt, "record_tweet",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db down")))

    assert pt.main(["abc12345"]) != 0
    assert not (drafts_dir / "abc12345.txt.posted").exists()
    assert (drafts_dir / "abc12345.txt.pending").exists()
    assert "do NOT re-run" in capsys.readouterr().err
