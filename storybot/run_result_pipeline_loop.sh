#!/usr/bin/env bash
# Runs storybot/result_pipeline.py every hour, then has Claude Code
# review/edit each drafted result tweet, then publishes it via
# storybot/publish_result.py. result_pipeline.py drafts the settle-half
# tweets (scorecard + composed text) and prints a marker line per draft;
# this loop picks those up, lets Claude verify the numbers, and posts.
#
# Intended to be launched inside a screen/tmux session:
#     screen -S results
#     ./storybot/run_result_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r results
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline. Note
# that DRY_RUN never posts to X (post_tweet returns a dryrun id).
#
# Results are intentionally NOT peak-window gated (unlike the twitter loop)
# because they post on market resolution and are volume-capped at
# RESULT_DAILY_CAP/day in result_pipeline.py.

set -u
set -o pipefail

INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"  # 1 hour

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/storybot/logs"
LOG_FILE="$LOG_DIR/result_pipeline.log"

mkdir -p "$LOG_DIR"

# shellcheck disable=SC1091
source "$PROJECT_ROOT/venv/bin/activate"

cd "$PROJECT_ROOT"

trap 'echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] loop interrupted, exiting" | tee -a "$LOG_FILE"; exit 0' INT TERM

while true; do
    {
        echo ""
        echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    } | tee -a "$LOG_FILE"

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    # `output` captures stdout so we can grep the draft marker lines.
    output=$(stdbuf -oL -eL python storybot/result_pipeline.py 2>&1 | tee -a "$LOG_FILE")
    status="${PIPESTATUS[0]}"

    if [[ "$status" -ne 0 ]]; then
        echo "[loop] result_pipeline.py exited $status — skipping this iteration" | tee -a "$LOG_FILE"
    else
        echo "$output" \
          | { grep -oP '\[result_pipeline\] draft original_tweet_id=\K[0-9]+' || true; } \
          | while read -r rid; do
            echo "[loop] result draft $rid — invoking claude to edit" | tee -a "$LOG_FILE"

            prompt="Review and edit the result tweet draft at @storybot/result_drafts/$rid.txt — edit the file directly. The full computed result (W/L, net P&L, per-market breakdown) is in @storybot/live_runs/result_$rid.json; the scorecard image that will attach is @storybot/live_runs/result_$rid.png. Verify every dollar and W-L number in the tweet matches the artifact's aggregate, keep it under 270 chars, no URLs (they're stripped), and stay neutral on wins and losses (no gloating, no excuses). The tweet must be at least two sentences (a result lead, then a separate sentence stating the P&L like 'Cashed +\$31k.' or 'Burned -\$28k.') — publish_result.py re-runs validate_tweet (see @storybot/twitter_pipeline.py), which rejects single-sentence tweets. publish_result.py runs right after you finish and re-validates."

            if claude -p "$prompt" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
                if python storybot/publish_result.py "$rid" 2>&1 | tee -a "$LOG_FILE"; then
                    rm -f "storybot/result_drafts/$rid.txt"
                    echo "[loop] published result $rid" | tee -a "$LOG_FILE"
                else
                    echo "[loop] publish_result failed for $rid — draft preserved" | tee -a "$LOG_FILE"
                fi
            else
                echo "[loop] claude edit failed for $rid — not publishing" | tee -a "$LOG_FILE"
            fi
        done
    fi

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (exit=$status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    sleep "$INTERVAL_SECONDS"
done
