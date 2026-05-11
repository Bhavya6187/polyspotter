"""Publish a drafted twitter_pipeline tweet.

Reads the draft .txt that twitter_pipeline.py left on disk, re-runs
validate_tweet (defensive — claude may have edited it), then posts the
tweet (with chart png if present) and records it in tweeted_alerts.

Usage:
    python storybot/publish_tweet.py <run_id>

Exit codes:
    0  posted (record may have soft-failed but tweet is live)
    1  no draft / no transcript / missing publish_meta / validation failed /
       post raised
    2  bad argv
"""
from __future__ import annotations

import json
import os
import sys

# Make project root importable so `import db` and friends work when this
# script runs directly via cron / the loop shell.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


_STORYBOT_DIR = os.path.dirname(os.path.abspath(__file__))
TWITTER_DRAFTS_DIR = os.path.join(_STORYBOT_DIR, "twitter_drafts")
LIVE_RUNS_DIR = os.path.join(_STORYBOT_DIR, "live_runs")

_REQUIRED_PUBLISH_META_KEYS = (
    "alert_ids", "chart_type", "target_alert_id", "chart_png_path",
)


# Imported at module level (not inside main) so tests can monkeypatch these.
from bot_utils import log
from twitter_pipeline import validate_tweet
from tweet_utils import (
    _build_twitter_api_v1, _build_twitter_client, post_tweet, record_tweet,
)


def _draft_path(run_id: str) -> str:
    return os.path.join(TWITTER_DRAFTS_DIR, f"{run_id}.txt")


def _transcript_path(run_id: str) -> str:
    return os.path.join(LIVE_RUNS_DIR, f"twitter_pipeline_{run_id}.json")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: publish_tweet.py <run_id>", file=sys.stderr)
        return 2
    run_id = argv[0]

    log("publish_tweet_start", run_id=run_id)

    draft_path = _draft_path(run_id)
    if not os.path.exists(draft_path):
        print(f"error: no draft found at {draft_path}", file=sys.stderr)
        log("publish_tweet_no_draft", run_id=run_id, path=draft_path)
        return 1
    with open(draft_path) as f:
        tweet_text = f.read().rstrip("\n")

    transcript_path = _transcript_path(run_id)
    if not os.path.exists(transcript_path):
        print(f"error: no transcript at {transcript_path}", file=sys.stderr)
        log("publish_tweet_no_transcript", run_id=run_id, path=transcript_path)
        return 1
    with open(transcript_path) as f:
        transcript = json.load(f)

    pm = transcript.get("publish_meta")
    if not isinstance(pm, dict):
        print("error: transcript missing publish_meta block", file=sys.stderr)
        log("publish_tweet_no_publish_meta", run_id=run_id)
        return 1
    missing = [k for k in _REQUIRED_PUBLISH_META_KEYS if k not in pm]
    if missing:
        print(f"error: publish_meta missing keys: {missing}", file=sys.stderr)
        log("publish_tweet_publish_meta_missing_keys",
            run_id=run_id, missing=missing)
        return 1
    alert_ids = pm["alert_ids"]
    chart_png_path = pm["chart_png_path"]

    chart_png: bytes | None = None
    if chart_png_path:
        if not os.path.exists(chart_png_path):
            print(
                f"error: chart_png_path in publish_meta does not exist: "
                f"{chart_png_path}",
                file=sys.stderr,
            )
            log("publish_tweet_chart_png_missing",
                run_id=run_id, path=chart_png_path)
            return 1
        with open(chart_png_path, "rb") as f:
            chart_png = f.read()

    ok, err = validate_tweet(tweet_text)
    if not ok:
        print(f"error: validate_tweet failed: {err}", file=sys.stderr)
        log("publish_tweet_validation_error", run_id=run_id, error=err)
        return 1

    twitter_client = _build_twitter_client()
    twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
    try:
        tweet_id = post_tweet(
            tweet_text,
            twitter_client=twitter_client,
            twitter_api_v1=twitter_api_v1,
            media_png=chart_png,
            dry_run=False,
        )
    except Exception as exc:
        log("publish_tweet_post_error",
            run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        print(
            f"error: post_tweet raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    log("publish_tweet_posted",
        run_id=run_id, tweet_id=tweet_id, alert_ids=alert_ids,
        tweet_length=len(tweet_text))

    try:
        record_tweet([int(i) for i in alert_ids], tweet_id, tweet_text)
    except Exception as exc:
        # Tweet is already live; failing to record is a soft fail so the
        # shell loop doesn't treat this as a publish failure.
        log("publish_tweet_record_error",
            run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("publish_tweet_done",
            run_id=run_id, tweet_id=tweet_id, recorded=False)
        print(
            f"[publish_tweet] posted tweet_id={tweet_id} but record_tweet "
            f"raised — dedup may miss this on the next run.",
            file=sys.stderr,
        )
        return 0

    log("publish_tweet_done",
        run_id=run_id, tweet_id=tweet_id, recorded=True)
    print(f"[publish_tweet] published run_id={run_id} tweet_id={tweet_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
