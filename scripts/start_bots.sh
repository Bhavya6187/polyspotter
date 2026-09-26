#!/usr/bin/env bash
# Starts every bot loop EXCEPT polybot in a single detached screen session
# named "bots", one named window per bot:
#
#   0 digest    storybot/run_digest_daily_loop.sh      daily at RUN_HOUR (6am local)
#   1 twitter   storybot/run_twitter_pipeline_loop.sh  hourly, self-gated
#   2 grader    scripts/run_grade_worker_loop.sh       every 30 min
#   3 seo       scripts/run_seo_worker_loop.sh         every 10 min
#
# results loop retired 2026-06-16 and its code removed — do not re-add.
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
# All loop logs land in storybot/logs/ — tail -f storybot/logs/*.log

set -euo pipefail

SESSION="bots"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT"

# Drop sockets left behind by a crashed/killed screen daemon so a stale
# "(Dead ???)" entry doesn't trip the already-exists check below.
screen -wipe >/dev/null 2>&1 || true

# Capture the listing first: with pipefail, `screen -ls | grep -q` can report
# grep's early exit as a SIGPIPE failure and fall through to a duplicate session.
existing="$(screen -ls 2>/dev/null || true)"
# Live rows look like "\t296797.bots\t(09/26/2026 10:31:28 AM)\t(Detached)";
# dead ones end in "(Dead ???)" and are ignored.
if grep -qE "[0-9]+\.${SESSION}[[:space:]].*\((Attached|Detached)\)" <<<"$existing"; then
    echo "screen session '${SESSION}' already exists — attach with: screen -r ${SESSION}" >&2
    exit 1
fi

screen -dmS "$SESSION" -t digest ./storybot/run_digest_daily_loop.sh
# `screen -dmS` returns before the child has created its socket; the next
# `-X` commands fail with "No screen session found" if they win the race.
for _ in $(seq 1 50); do
    screen -ls 2>/dev/null | grep -qE "[0-9]+\.${SESSION}[[:space:]]" && break
    sleep 0.1
done
# Keep windows open (showing output) when their command dies: r relaunches, k closes.
screen -S "$SESSION" -X zombie kr
screen -S "$SESSION" -X screen -t twitter ./storybot/run_twitter_pipeline_loop.sh
screen -S "$SESSION" -X screen -t grader ./scripts/run_grade_worker_loop.sh
screen -S "$SESSION" -X screen -t seo ./scripts/run_seo_worker_loop.sh

echo "started screen session '${SESSION}' with windows:"
screen -S "$SESSION" -Q windows
echo ""
echo "attach: screen -r ${SESSION}   (Ctrl-A \" = window picker, Ctrl-A d = detach)"
