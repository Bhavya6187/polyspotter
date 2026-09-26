#!/usr/bin/env bash
# Keeps the bot loops' on-disk output bounded. Called once per iteration by
# each loop script (twitter, digest, grader, seo); safe to run by hand.
#
#   storybot/logs/*.log      any file over 20 MB is moved to <file>.1
#                            (replacing the previous .1); the loops append
#                            with `tee -a`, which reopens the file each time,
#                            so the next write starts a fresh log.
#   storybot/live_runs/*     entries (files or run directories) not modified
#                            for more than 30 days are deleted.
#
# The project root comes from this script's own location, never from cwd, and
# must contain storybot/; otherwise the script exits non-zero touching nothing.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -n "$ROOT" && -d "$ROOT/storybot" ]] || { echo "rotate_logs: bad root '$ROOT'" >&2; exit 1; }
MAX_LOG_BYTES=$((20 * 1024 * 1024))

for f in "$ROOT"/storybot/logs/*.log; do
    [[ -f "$f" ]] || continue
    if (( $(stat -c %s "$f") > MAX_LOG_BYTES )); then
        mv -f "$f" "$f.1"
    fi
done

if [[ -d "$ROOT/storybot/live_runs" ]]; then
    find "$ROOT/storybot/live_runs" -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} +
fi
