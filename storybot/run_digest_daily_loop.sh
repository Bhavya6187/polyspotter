#!/usr/bin/env bash
# Sends the PolySpotter daily digest once a day at RUN_HOUR (local time).
#
# digestbot.py --send generates the digest, publishes it to the website
# (digests table → /digest/<date>), then emails every confirmed, non-
# unsubscribed subscriber via Resend. This wrapper just fires it on a
# daily schedule, sleeping until the next RUN_HOUR:00 local time each loop.
#
# The host is on America/Los_Angeles, so the default RUN_HOUR=6 means
# 6 AM Pacific and tracks DST automatically (PST/PDT) — no fixed offset.
#
# Intended to be launched inside a screen/tmux session:
#     screen -S digest
#     ./storybot/run_digest_daily_loop.sh
# Detach with C-a d. Reattach with: screen -r digest
#
# Env knobs:
#   RUN_HOUR=6        hour of day (local, 0-23) to send. Default 6.
#   DRY_RUN=true      forwarded to digestbot — resolves recipients but
#                     never calls Resend (safe to leave running for a test).

set -u
set -o pipefail

RUN_HOUR="${RUN_HOUR:-6}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/storybot/logs"
LOG_FILE="$LOG_DIR/digest.log"

mkdir -p "$LOG_DIR"

# shellcheck disable=SC1091
source "$PROJECT_ROOT/venv/bin/activate"

cd "$PROJECT_ROOT"

trap 'echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] loop interrupted, exiting" | tee -a "$LOG_FILE"; exit 0' INT TERM

# Seconds from now until the next RUN_HOUR:00:00 local time. If that time has
# already passed today, target tomorrow.
seconds_until_run_hour() {
    local now target
    now="$(date +%s)"
    target="$(date -d "today ${RUN_HOUR}:00:00" +%s)"
    if (( now >= target )); then
        target="$(date -d "tomorrow ${RUN_HOUR}:00:00" +%s)"
    fi
    echo $(( target - now ))
}

echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] digest loop started (RUN_HOUR=${RUN_HOUR}, DRY_RUN=${DRY_RUN:-false})" | tee -a "$LOG_FILE"

while true; do
    wait_s="$(seconds_until_run_hour)"
    next_at="$(date -d "+${wait_s} seconds" +%Y-%m-%dT%H:%M:%S%z)"
    echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] sleeping ${wait_s}s until next run at ${next_at}" | tee -a "$LOG_FILE"
    sleep "$wait_s"

    {
        echo ""
        echo "===== digest run started $(date +%Y-%m-%dT%H:%M:%S%z) ====="
    } | tee -a "$LOG_FILE"

    # stdbuf -oL -eL keeps output line-buffered so the tee'd log updates live.
    stdbuf -oL -eL python storybot/digestbot.py --send 2>&1 | tee -a "$LOG_FILE"
    status="${PIPESTATUS[0]}"

    {
        echo "===== digest run finished $(date +%Y-%m-%dT%H:%M:%S%z) (exit=$status) ====="
    } | tee -a "$LOG_FILE"

    if [[ "$status" -ne 0 ]]; then
        echo "[loop] digestbot.py exited $status — see log above" | tee -a "$LOG_FILE"
    fi
done
