#!/usr/bin/env bash
# Runs storybot/twitter_pipeline.py every 3 hours, logging to storybot/logs/.
# Intended to be launched inside a screen/tmux session:
#     screen -S twitter
#     ./storybot/run_twitter_pipeline_loop.sh
# Detach with C-a d. Reattach with: screen -r twitter
#
# Pass DRY_RUN=true in the environment to forward it to the pipeline.

set -u

INTERVAL_SECONDS="${INTERVAL_SECONDS:-10800}"  # 3 hours

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
    if stdbuf -oL -eL python storybot/twitter_pipeline.py 2>&1 | tee -a "$LOG_FILE"; then
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
