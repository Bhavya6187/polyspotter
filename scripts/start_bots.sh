#!/usr/bin/env bash
# Starts every bot loop EXCEPT polybot in a single detached screen session
# named "bots", one named window per bot:
#
#   0 digest    storybot/run_digest_daily_loop.sh      daily at RUN_HOUR (6am local)
#   1 twitter   storybot/run_twitter_pipeline_loop.sh  hourly, self-gated
#   2 results   storybot/run_result_pipeline_loop.sh   hourly
#   3 grader    scripts/run_grade_worker_loop.sh       every 30 min
#   4 seo       scripts/run_seo_worker_loop.sh         every 10 min
#
# Usage:
#     ./scripts/start_bots.sh    # start detached; refuses if "bots" already exists
#     screen -r bots             # attach
#     Ctrl-A "                   # window picker        Ctrl-A d   detach
#
# zombie mode is on: if a loop dies its window stays open showing the final
# output — press r in it to relaunch, k to close. Nothing dies silently.
#
# polybot is intentionally NOT managed here; it keeps its own session.
# All five loop logs land in storybot/logs/ — tail -f storybot/logs/*.log

set -euo pipefail

SESSION="bots"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT"

if screen -ls 2>/dev/null | grep -qE "[0-9]+\.${SESSION}[[:space:]]"; then
    echo "screen session '${SESSION}' already exists — attach with: screen -r ${SESSION}" >&2
    exit 1
fi

screen -dmS "$SESSION" -t digest ./storybot/run_digest_daily_loop.sh
# Keep windows open (showing output) when their command dies: r relaunches, k closes.
screen -S "$SESSION" -X zombie kr
screen -S "$SESSION" -X screen -t twitter ./storybot/run_twitter_pipeline_loop.sh
screen -S "$SESSION" -X screen -t results ./storybot/run_result_pipeline_loop.sh
screen -S "$SESSION" -X screen -t grader ./scripts/run_grade_worker_loop.sh
screen -S "$SESSION" -X screen -t seo ./scripts/run_seo_worker_loop.sh

echo "started screen session '${SESSION}' with windows:"
screen -S "$SESSION" -Q windows
echo ""
echo "attach: screen -r ${SESSION}   (Ctrl-A \" = window picker, Ctrl-A d = detach)"
