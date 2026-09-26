"""Publish a drafted twitter_pipeline tweet.

Reads the draft .txt that twitter_pipeline.py left on disk, re-runs
validate_tweet (defensive — claude may have edited it), then posts the
tweet (with chart png if present) and records it in tweeted_alerts.

Usage:
    python storybot/publish_tweet.py <run_id>

Exit codes:
    0  posted and recorded in tweeted_alerts; draft and sidecars removed
    1  no draft / no transcript / missing publish_meta / validation failed /
       post raised / post outcome unknown (.pending) / posted but not recorded
       (.posted)
    2  bad argv

Sidecars next to the draft (<run_id>.txt):
    <run_id>.txt.posted   the tweet is live but record_tweet failed. Line 1 is
                          the tweet id, line 2 the alert ids as a JSON list. A
                          re-run records it without posting again and without
                          needing the transcript (live_runs is pruned after 30
                          days); alert ids come from the transcript when it is
                          still there, else from line 2, else none are
                          recorded (a legacy one-line sidecar).
    <run_id>.txt.pending  the post call failed ambiguously (5xx, dropped
                          connection, timeout) — the tweet may be live. Every
                          run refuses to post until an operator checks X and
                          deletes the marker (and the draft, if it posted).
"""
from __future__ import annotations

import http.client
import json
import os
import sys

import requests
import tweepy

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


def _valid_alert_ids(alert_ids) -> bool:
    return (isinstance(alert_ids, list) and bool(alert_ids)
            and all(isinstance(i, int) for i in alert_ids))


def _read_posted_marker(path: str) -> tuple[str, list | None]:
    """Return (tweet_id, alert_ids) from a .posted sidecar. alert_ids is None
    when the sidecar predates line 2 or line 2 is unreadable."""
    with open(path) as f:
        lines = f.read().splitlines()
    tweet_id = lines[0].strip() if lines else ""
    alert_ids = None
    if len(lines) > 1:
        try:
            parsed = json.loads(lines[1])
        except ValueError:
            parsed = None
        if _valid_alert_ids(parsed):
            alert_ids = parsed
    return tweet_id, alert_ids


def _transcript_alert_ids(run_id: str) -> list | None:
    """publish_meta.alert_ids from the transcript, or None if the transcript
    is gone or does not hold valid ids."""
    try:
        with open(_transcript_path(run_id)) as f:
            pm = json.load(f).get("publish_meta")
    except (OSError, ValueError, AttributeError):
        return None
    ids = pm.get("alert_ids") if isinstance(pm, dict) else None
    return ids if _valid_alert_ids(ids) else None


def _is_ambiguous_post_error(exc: BaseException) -> bool:
    """True when the post request may have reached X even though it raised:
    a 5xx, a dropped connection, or a read timeout. Walks the cause chain
    (tweepy/requests wrap the underlying socket error)."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, requests.exceptions.ConnectTimeout):
            return False  # never connected, so nothing was sent
        if isinstance(e, (tweepy.errors.TwitterServerError,
                          http.client.RemoteDisconnected, ConnectionResetError,
                          TimeoutError, requests.exceptions.ConnectionError,
                          requests.exceptions.Timeout)):
            return True
        e = e.__cause__ or e.__context__
    return False


def _record_and_clean_up(run_id: str, draft_path: str, alert_ids: list,
                         tweet_id: str, tweet_text: str) -> int:
    """Record a live tweet in tweeted_alerts, then drop the draft and its
    .posted sidecar. On a record failure everything stays on disk and the run
    exits 1, so the loop/operator retries the record (never the post)."""
    posted_url = f"https://x.com/i/web/status/{tweet_id}"
    try:
        record_tweet([int(i) for i in alert_ids], tweet_id, tweet_text)
    except Exception as exc:
        log("publish_tweet_record_error",
            run_id=run_id, tweet_id=tweet_id, error=f"{type(exc).__name__}: {exc}")
        print(
            f"error: tweet_id={tweet_id} is live but record_tweet raised "
            f"{type(exc).__name__}: {exc}. Draft and {draft_path}.posted kept; "
            f"re-run publish_tweet.py {run_id} to record it (it will not re-post).",
            file=sys.stderr,
        )
        print(f"    tweet: {posted_url}", file=sys.stderr)
        return 1
    for path in (draft_path, draft_path + ".posted"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    log("publish_tweet_done",
        run_id=run_id, tweet_id=tweet_id, recorded=True, posted_url=posted_url)
    print(f"[publish_tweet] published run_id={run_id} tweet_id={tweet_id}")
    print(f"    tweet: {posted_url}")
    return 0


# Idempotency: the post is the only irreversible step. A tweet id is written
# to <draft>.posted before recording, so a re-run records instead of
# re-posting; an ambiguous post failure writes <draft>.pending, which blocks
# every re-run until an operator has checked X. After a recorded publish the
# draft is removed, so a re-run fails the "no draft found" check.
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
    if os.path.exists(draft_path + ".pending"):
        print(
            f"error: {draft_path}.pending exists — an earlier post attempt failed "
            f"ambiguously and the tweet may be live. Check X; if it posted, delete "
            f"the draft and marker; if not, delete the marker and re-run.",
            file=sys.stderr,
        )
        log("publish_tweet_pending_marker", run_id=run_id, path=draft_path + ".pending")
        return 1
    with open(draft_path) as f:
        tweet_text = f.read().rstrip("\n")

    # Retry of a live-but-unrecorded tweet. Independent of the transcript,
    # which may have been pruned from live_runs by now.
    posted_marker = draft_path + ".posted"
    if os.path.exists(posted_marker):
        tweet_id, sidecar_ids = _read_posted_marker(posted_marker)
        alert_ids = _transcript_alert_ids(run_id) or sidecar_ids or []
        log("publish_tweet_already_posted", run_id=run_id, tweet_id=tweet_id,
            alert_ids=alert_ids)
        if not alert_ids:
            print(
                f"warning: no alert ids for already-posted tweet_id={tweet_id} "
                f"(transcript gone, sidecar has none); recording no "
                f"tweeted_alerts rows and clearing the draft.",
                file=sys.stderr,
            )
        if os.environ.get("DRY_RUN", "").strip().lower() == "true":
            print(f"[publish_tweet] DRY_RUN=true — tweet_id={tweet_id} already posted; not recording.")
            return 0
        return _record_and_clean_up(run_id, draft_path, alert_ids, tweet_id, tweet_text)

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
    if not _valid_alert_ids(alert_ids):
        print(
            f"error: publish_meta.alert_ids is malformed: {alert_ids!r}",
            file=sys.stderr,
        )
        log("publish_tweet_alert_ids_malformed",
            run_id=run_id, alert_ids=alert_ids)
        return 1
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

    # Honor DRY_RUN like publish_article.py does: validate, print, never post.
    # (post_tweet was hardcoded dry_run=False, so `DRY_RUN=true python
    # storybot/publish_tweet.py <id>` used to post for real.)
    if os.environ.get("DRY_RUN", "").strip().lower() == "true":
        log("publish_tweet_dry_run", run_id=run_id, alert_ids=alert_ids,
            tweet_length=len(tweet_text), has_media=chart_png is not None)
        print(f"[publish_tweet] DRY_RUN=true — not posting run_id={run_id}. Tweet would be:\n{tweet_text}")
        return 0

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
        ambiguous = _is_ambiguous_post_error(exc)
        log("publish_tweet_post_error", run_id=run_id, ambiguous=ambiguous,
            error=f"{type(exc).__name__}: {exc}")
        print(
            f"error: post_tweet raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        if ambiguous:
            with open(draft_path + ".pending", "w") as f:
                f.write(f"{type(exc).__name__}: {exc}\n")
            print(
                f"error: the tweet may have posted — wrote {draft_path}.pending. "
                f"Check X before deleting the marker.",
                file=sys.stderr,
            )
        return 1

    log("publish_tweet_posted",
        run_id=run_id, tweet_id=tweet_id, alert_ids=alert_ids,
        tweet_length=len(tweet_text))

    # Persist the fact that the tweet is live before anything else can fail.
    try:
        with open(posted_marker, "w") as f:
            f.write(f"{tweet_id}\n{json.dumps(alert_ids)}\n")
    except OSError as exc:
        log("publish_tweet_posted_marker_error",
            run_id=run_id, tweet_id=tweet_id, error=str(exc))
    return _record_and_clean_up(run_id, draft_path, alert_ids, tweet_id, tweet_text)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
