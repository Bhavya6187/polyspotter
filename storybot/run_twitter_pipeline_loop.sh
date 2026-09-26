#!/usr/bin/env bash
# Runs storybot/twitter_pipeline.py hourly, then has Claude Code review/edit
# the draft, then publishes via storybot/publish_tweet.py.
# The pipeline self-gates on a cadence window (see _cadence_skip_reason in
# storybot/twitter_pipeline.py): it only drafts inside peak ET windows, at
# most once per window and twice per ET day. Most hourly wake-ups skip
# immediately, before any LLM call; the ship rate lands at ~1-2 tweets/day.
# Intended to be launched inside a screen/tmux session:
#     screen -S twitter
#     ./storybot/run_twitter_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r twitter
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline. Note
# that DRY_RUN drafts land in storybot/dry_runs/twitter_drafts/ and are
# NOT picked up by publish_tweet.py — the chain stops after drafting.

set -u
set -o pipefail

INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"  # 1 hour
CLAUDE_TIMEOUT_SECONDS="${CLAUDE_TIMEOUT_SECONDS:-900}"   # hard cap on the headless edit step
MAX_CONSECUTIVE_EDIT_FAILURES="${MAX_CONSECUTIVE_EDIT_FAILURES:-3}"
consecutive_edit_failures=0

# The headless `claude -p` edit step fails outright when the CLI's OAuth
# session has expired (Sep 2026: every run for 11 days, no tweet published,
# nothing alarmed because the loop just kept sleeping). Check before editing
# so the log says why.
claude_logged_in() {
    claude auth status 2>/dev/null | grep -q '"loggedIn": *true'
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/storybot/logs"
LOG_FILE="$LOG_DIR/twitter_pipeline.log"

mkdir -p "$LOG_DIR"

# shellcheck disable=SC1091
source "$PROJECT_ROOT/venv/bin/activate"

cd "$PROJECT_ROOT"

# Make Ctrl-C terminate the loop cleanly instead of just the current python run.
trap 'echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] loop interrupted, exiting" | tee -a "$LOG_FILE"; exit 0' INT TERM

while true; do
    # Keep storybot/logs and storybot/live_runs bounded (scripts/rotate_logs.sh).
    bash "$PROJECT_ROOT/scripts/rotate_logs.sh" || true

    {
        echo ""
        echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    } | tee -a "$LOG_FILE"

    # Leftover drafts from earlier runs (sidecars: see storybot/publish_tweet.py).
    # .posted = live on X but not recorded -> retry the record (never re-posts).
    # .pending = post outcome unknown -> never touch it; a human must check X.
    for marker in storybot/twitter_drafts/*.txt.posted; do
        [[ -e "$marker" ]] || continue
        stale_id=$(basename "$marker" .txt.posted)
        echo "[loop] run_id=$stale_id is live but unrecorded — retrying the record" | tee -a "$LOG_FILE"
        python storybot/publish_tweet.py "$stale_id" 2>&1 | tee -a "$LOG_FILE" || true
    done
    for marker in storybot/twitter_drafts/*.txt.pending; do
        [[ -e "$marker" ]] || continue
        stale_id=$(basename "$marker" .txt.pending)
        echo "[loop] WARNING: skipping run_id=$stale_id — its post failed ambiguously and may be live. Check X before deleting $marker (if it posted, delete the draft too; if not, delete the marker and run publish_tweet.py $stale_id by hand)." | tee -a "$LOG_FILE"
    done

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    # `output` captures stdout so we can grep the draft run_id marker.
    output=$(stdbuf -oL -eL python storybot/twitter_pipeline.py 2>&1 | tee -a "$LOG_FILE")
    pipeline_status="${PIPESTATUS[0]}"

    if [[ "$pipeline_status" -ne 0 ]]; then
        echo "[loop] twitter_pipeline.py exited $pipeline_status — skipping this iteration" | tee -a "$LOG_FILE"
    elif [[ "${DRY_RUN:-false}" == "true" ]]; then
        # Dry-run drafts land in storybot/dry_runs/ and must never reach the
        # edit/publish chain (publish_tweet.py also refuses under DRY_RUN).
        echo "[loop] DRY_RUN=true — draft (if any) left in dry_runs/, not editing or publishing" | tee -a "$LOG_FILE"
    else
        run_id=$(echo "$output" \
            | grep -oP '\[twitter_pipeline\] draft run_id=\K[a-f0-9]+' || true)
        if [[ -z "$run_id" ]]; then
            echo "[loop] no draft produced (pipeline skipped). Sleeping." | tee -a "$LOG_FILE"
        else
            echo "[loop] draft run_id=$run_id — invoking claude to edit" | tee -a "$LOG_FILE"

            prompt="Review and edit the twitter pipeline draft with run_id=$run_id.

The draft tweet is at @storybot/twitter_drafts/$run_id.txt — edit this file directly. Keep it postable: the workflow runs @storybot/publish_tweet.py right after you finish and will re-validate before posting. If the draft is fine, leave it alone; if it has problems, fix them.

The full transcript with every stage's input and output (event picker, data bundle, facts bundle, chart picker, writer attempts, recent tweets the picker saw) is at @storybot/live_runs/twitter_pipeline_$run_id.json — open it whenever you need to verify a claim in the tweet.

The chart that will be attached is at @storybot/live_runs/twitter_pipeline_$run_id.png — open it to confirm the tweet's hook actually anchors to what the image shows.

Fix these before finishing:

1. FACT FIDELITY. Every concrete number in the tweet (dollar amounts, win-loss tuples like 'X-Y', percentages, ROI %, cents prices, cluster sizes, minutes-to-resolution) must be reachable in the transcript's facts_bundle, trades, or chosen_alerts. The bot has a known habit of inflating wallet records and inventing cluster sizes. If you can't verify a number in the transcript, either replace it with the actual value from there or rewrite the line to drop the specific stat.

2. CHART ANCHOR. The tweet's lede must match the chart that will be attached. transcript.stages.3_chart_picker.hook_anchor tells you what the chart was chosen to anchor — the tweet's opening must reference the same subject (the specific wallet, the specific price move, the specific cluster). Don't open with an unrelated angle.

3. LENGTH AND BANNED PHRASES. publish_tweet.py re-runs validate_tweet, which rejects: tweet length > TWEET_MAX_CHARS (twitter-counted, not raw len) and any banned phrase from _BANNED_TWEET_PHRASES (see @storybot/tweet_utils.py for the exact list). Stay under length and avoid the banned phrasing.

4. OPENER FRESHNESS. The transcript's publish_meta.recent_openers field has the last 5 tweet openers we've shipped. The first ~6 words of this tweet must not be a near-paraphrase of any of them — we don't want a feed that all sounds the same.

Refer to validate_tweet and validate_tweet_anchor in @storybot/twitter_pipeline.py for the exact validator rules if anything is unclear. publish_tweet.py runs immediately after you finish, so the tweet must be in a postable state."

            # --model is pinned explicitly: this loop runs headless with no TTY,
            # so an unpinned `claude -p` rides whatever the ambient default model
            # resolves to. In Jun 2026 that default flipped to a model this account
            # can't access (claude-fable-5), the edit step exited non-zero, and the
            # loop silently stopped publishing for days. Pin a model we always have.
            if ! claude_logged_in; then
                echo "[loop] ERROR: claude CLI is not logged in (run: claude auth login) — not editing or publishing run_id=$run_id" | tee -a "$LOG_FILE"
                edit_ok=1
            elif timeout "$CLAUDE_TIMEOUT_SECONDS" claude -p "$prompt" --model claude-opus-4-8 --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
                edit_ok=0
            else
                edit_ok=1
            fi

            if [[ "$edit_ok" -eq 0 ]]; then
                consecutive_edit_failures=0
                if python storybot/publish_tweet.py "$run_id" 2>&1 | tee -a "$LOG_FILE"; then
                    # publish_tweet removes the draft once the tweet is posted
                    # AND recorded; the rm is belt-and-braces. See the
                    # idempotency note in storybot/publish_tweet.py.
                    rm -f "storybot/twitter_drafts/$run_id.txt"
                    echo "[loop] published run_id=$run_id" | tee -a "$LOG_FILE"
                elif [[ -e "storybot/twitter_drafts/$run_id.txt.pending" ]]; then
                    echo "[loop] publish_tweet for run_id=$run_id failed ambiguously — the tweet may be live. Check X before deleting storybot/twitter_drafts/$run_id.txt.pending" | tee -a "$LOG_FILE"
                elif [[ -e "storybot/twitter_drafts/$run_id.txt.posted" ]]; then
                    echo "[loop] run_id=$run_id posted but not recorded — the next iteration retries the record" | tee -a "$LOG_FILE"
                else
                    echo "[loop] publish_tweet failed for run_id=$run_id — draft preserved on disk" | tee -a "$LOG_FILE"
                fi
            else
                consecutive_edit_failures=$((consecutive_edit_failures + 1))
                echo "[loop] claude edit failed for run_id=$run_id (${consecutive_edit_failures}/${MAX_CONSECUTIVE_EDIT_FAILURES} consecutive) — not publishing. Draft remains on disk." | tee -a "$LOG_FILE"
                if (( consecutive_edit_failures >= MAX_CONSECUTIVE_EDIT_FAILURES )); then
                    # Die loudly instead of sleeping forever: under start_bots.sh's
                    # zombie mode the window stays open showing this message.
                    echo "[loop] FATAL: ${consecutive_edit_failures} consecutive claude edit failures — exiting so the outage is visible. Fix auth (claude auth login) and press r to relaunch." | tee -a "$LOG_FILE"
                    exit 1
                fi
            fi
        fi
    fi

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (pipeline_exit=$pipeline_status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    sleep "$INTERVAL_SECONDS"
done
