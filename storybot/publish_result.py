"""Publish a drafted result tweet (the settle half of the accountability loop).

Reads the artifact result_pipeline.py wrote, re-validates the (possibly
Claude-edited) draft, posts it with the scorecard PNG, and records a
result_tweets row. Mirrors publish_tweet.py.

Usage:
    python storybot/publish_result.py <original_tweet_id>

Exit codes:
    0  posted (or skipped as already-settled) — nothing left to do
    1  no artifact / validation failed / post raised
    2  posted but recording failed (manual dedup needed) / bad argv
       (exit 2 is overloaded: both the "posted-but-unrecorded" case and a
       bad argv land here — both mean "a human needs to look", so they
       share an exit code.)

NOTE: This pipeline's dedup relies on a `result_tweets` row existing after a
successful post. If post_tweet succeeds but record_result fails even after a
retry, publish_result returns 2 and the result_tweets row is absent — a
subsequent pipeline run will re-discover the unsettled tweet and could re-post
it (a duplicate public settle tweet). This window is accepted for Phase A; an
operator seeing `result_unrecorded_post` should manually insert the
result_tweets row (or accept the rare duplicate).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import result_store
from bot_utils import log
from twitter_pipeline import validate_tweet
from tweet_utils import _build_twitter_api_v1, _build_twitter_client, post_tweet

_STORYBOT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESULT_DRAFTS_DIR = os.path.join(_STORYBOT_DIR, "result_drafts")

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Mirror result_pipeline's dir logic so DRY_RUN end-to-end works: the pipeline
# writes the artifact + scorecard png into dry_runs/ when DRY_RUN, so we must
# read from the same place.
_LIVE_RUNS_DIR = os.path.join(_STORYBOT_DIR, "live_runs")
_DRY_RUN_DIR = os.path.join(_STORYBOT_DIR, "dry_runs")
_RUN_OUTPUT_DIR = _DRY_RUN_DIR if DRY_RUN else _LIVE_RUNS_DIR


def _artifact_path(original_tweet_id: str) -> str:
    return os.path.join(_RUN_OUTPUT_DIR, f"result_{original_tweet_id}.json")


def _load_draft_text(artifact: dict, original_tweet_id: str) -> str:
    """Prefer the on-disk draft (Claude may have edited it); fall back to the
    result_drafts dir, then to the artifact's composed result_tweet."""
    path = artifact.get("result_draft_path")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    fallback = os.path.join(_RESULT_DRAFTS_DIR, f"{original_tweet_id}.txt")
    if os.path.exists(fallback):
        with open(fallback) as f:
            return f.read().strip()
    return (artifact.get("result_tweet") or "").strip()


def publish(*, original_tweet_id: str, artifact: dict, dry_run: bool) -> int:
    if result_store.result_exists(original_tweet_id):
        log("result_skip", original_tweet_id=original_tweet_id,
            reason="already recorded")
        return 0

    text = _load_draft_text(artifact, original_tweet_id)
    ok, err = validate_tweet(text)
    if not ok:
        log("result_validation_failed", original_tweet_id=original_tweet_id,
            error=err)
        return 1

    png_path = artifact.get("scorecard_png_path")
    media_png = None
    if png_path and os.path.exists(png_path):
        with open(png_path, "rb") as f:
            media_png = f.read()

    try:
        client = None if dry_run else _build_twitter_client()
        api_v1 = None if dry_run else _build_twitter_api_v1()
        result_tweet_id = post_tweet(
            text, twitter_client=client, twitter_api_v1=api_v1,
            media_png=media_png, dry_run=dry_run)
    except Exception as exc:
        log("result_post_error", original_tweet_id=original_tweet_id,
            error=f"{type(exc).__name__}: {exc}")
        return 1

    agg = artifact.get("aggregate") or {}

    def _record() -> None:
        result_store.record_result(
            original_tweet_id=original_tweet_id,
            result_tweet_id=result_tweet_id,
            alert_ids=artifact.get("alert_ids") or [],
            condition_ids=artifact.get("condition_ids") or [],
            n_won=int(agg.get("n_won") or 0),
            n_lost=int(agg.get("n_lost") or 0),
            net_pl_usd=float(agg.get("net_pl_usd") or 0.0),
            total_invested_usd=float(agg.get("total_invested_usd") or 0.0),
            outcome=artifact.get("outcome") or "wash",
            event_label=artifact.get("event_label"),
        )

    # The tweet is already public. We MUST land the result_tweets row or the
    # next pipeline run re-discovers this tweet and re-posts it. Retry once —
    # a transient DB hiccup right after a successful post is the common case.
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            _record()
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            log("result_record_error", original_tweet_id=original_tweet_id,
                result_tweet_id=result_tweet_id,
                error=f"{type(exc).__name__}: {exc}")

    if last_exc is not None:
        # Posted but NOT recorded — dedup can't see this, so a later run could
        # re-post the same settle tweet. Surface loudly for manual dedup.
        log("result_unrecorded_post", original_tweet_id=original_tweet_id,
            result_tweet_id=result_tweet_id,
            error=f"{type(last_exc).__name__}: {last_exc}", level="critical")
        return 2

    log("result_posted", original_tweet_id=original_tweet_id,
        result_tweet_id=result_tweet_id)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python storybot/publish_result.py <original_tweet_id>",
              file=sys.stderr)
        return 2
    original_tweet_id = argv[1]
    path = _artifact_path(original_tweet_id)
    if not os.path.exists(path):
        log("result_no_artifact", original_tweet_id=original_tweet_id, path=path)
        return 1
    with open(path) as f:
        artifact = json.load(f)
    return publish(original_tweet_id=original_tweet_id, artifact=artifact,
                   dry_run=DRY_RUN)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
