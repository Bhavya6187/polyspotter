#!/usr/bin/env bash
# Runs backend/grade_worker.py every INTERVAL_SECONDS (default 30 min).
# grade_worker does ONE grading pass and exits (see its docstring) — this
# wrapper is the shell loop it expects, plus logging.
#
# Normally launched as the "grader" window by scripts/start_bots.sh, but
# works standalone inside any screen/tmux session:
#     ./scripts/run_grade_worker_loop.sh
#
# Env knobs:
#   INTERVAL_SECONDS=1800   seconds between passes.

set -u
set -o pipefail

INTERVAL_SECONDS="${INTERVAL_SECONDS:-1800}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/storybot/logs"
LOG_FILE="$LOG_DIR/grade_worker.log"

mkdir -p "$LOG_DIR"

# shellcheck disable=SC1091
source "$PROJECT_ROOT/venv/bin/activate"

cd "$PROJECT_ROOT"

trap 'echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] loop interrupted, exiting" | tee -a "$LOG_FILE"; exit 0' INT TERM

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] grade_worker loop started (INTERVAL_SECONDS=${INTERVAL_SECONDS})" | tee -a "$LOG_FILE"

while true; do
    {
        echo ""
        echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    } | tee -a "$LOG_FILE"

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    stdbuf -oL -eL python backend/grade_worker.py 2>&1 | tee -a "$LOG_FILE"
    status="${PIPESTATUS[0]}"

    {
        echo "===== run finished $(date -u +%Y-%m-%dT%H:%M:%SZ) (exit=$status) ====="
        echo "sleeping ${INTERVAL_SECONDS}s until next run"
    } | tee -a "$LOG_FILE"

    if [[ "$status" -ne 0 ]]; then
        echo "[loop] grade_worker.py exited $status — see log above" | tee -a "$LOG_FILE"
    fi

    sleep "$INTERVAL_SECONDS"
done
