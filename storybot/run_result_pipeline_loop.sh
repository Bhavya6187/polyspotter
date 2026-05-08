#!/usr/bin/env bash
# Runs storybot/result_pipeline.py every hour, logging to storybot/logs/.
# This script does NOT post to Twitter; result_pipeline.py only prints
# the composed follow-up tweets and saves them to live_runs/result_*.json.
# Once the format is dialed in, we can flip the post step on inside the
# script itself.
#
# Intended to be launched inside a screen/tmux session:
#     screen -S results
#     ./storybot/run_result_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r results
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline.

set -u

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

    if stdbuf -oL -eL python storybot/result_pipeline.py 2>&1 | tee -a "$LOG_FILE"; then
        status="${PIPESTATUS[0]}"
    else
        status="${PIPESTATUS[0]}"
    fi

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (exit=$status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    sleep "$INTERVAL_SECONDS"
done
