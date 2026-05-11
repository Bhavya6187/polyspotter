#!/usr/bin/env bash
# Runs storybot/twitter_pipeline.py every 5 hours, then has Claude Code
# review/edit the draft, then publishes via storybot/publish_tweet.py.
# Five hours of wake-up gap yields ~4-5 wake-ups per day; with the picker
# skipping duplicate or weak-story windows, the actual ship rate lands in
# the 3-5 tweets/day target.
# Intended to be launched inside a screen/tmux session:
#     screen -S twitter
#     ./storybot/run_twitter_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r twitter
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline. Note
# that DRY_RUN drafts land in storybot/dry_runs/twitter_drafts/ and are
# NOT picked up by publish_tweet.py — the chain stops after drafting.

set -u

INTERVAL_SECONDS="${INTERVAL_SECONDS:-18000}"  # 5 hours

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
    {
        echo ""
        echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    } | tee -a "$LOG_FILE"

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    # `output` captures stdout so we can grep the draft run_id marker.
    output=$(stdbuf -oL -eL python storybot/twitter_pipeline.py 2>&1 | tee -a "$LOG_FILE")
    pipeline_status="${PIPESTATUS[0]}"

    if [[ "$pipeline_status" -ne 0 ]]; then
        echo "[loop] twitter_pipeline.py exited $pipeline_status — skipping this iteration" | tee -a "$LOG_FILE"
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

            if claude -p "$prompt" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
                if python storybot/publish_tweet.py "$run_id" 2>&1 | tee -a "$LOG_FILE"; then
                    # remove draft after success — enforces idempotency.
                    # See the NOTE comment in storybot/publish_tweet.py.
                    rm -f "storybot/twitter_drafts/$run_id.txt"
                    echo "[loop] published run_id=$run_id" | tee -a "$LOG_FILE"
                else
                    echo "[loop] publish_tweet failed for run_id=$run_id — draft preserved on disk" | tee -a "$LOG_FILE"
                fi
            else
                echo "[loop] claude edit failed for run_id=$run_id — not publishing. Draft remains on disk." | tee -a "$LOG_FILE"
            fi
        fi
    fi

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (pipeline_exit=$pipeline_status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    sleep "$INTERVAL_SECONDS"
done
