# Combined Bot Runner — Design

**Date:** 2026-06-12
**Status:** Approved

## Problem

Six detached screen sessions run the project's bots: `polybot`, `digest`,
`twitter_pipeline`, `twitter_result`, `grader`, and `polyspotter-seo`.
Managing five separate sessions (besides polybot) is noisy, and two of them
(`grader`, `polyspotter-seo`) are ad-hoc `while true; do …; sleep N; done`
one-liners typed into screen with no logging and no record if they crash.

## Goal

Collapse the five non-polybot sessions into a single screen session started
by one command, without touching any working pipeline logic. `polybot` stays
in its own session.

## Approach (chosen from three)

**One screen session, one named window per bot**, created by a wrapper
script. Rejected alternatives: (a) a supervisor script running all loops as
background jobs — loses live per-bot consoles; (b) a unified Python
scheduler — most code and regression risk for no current functional gain,
since the twitter/result loops embed claude-edit + publish chains that work
today.

## Components

### 1. `scripts/start_bots.sh` (new)

The single entry point. Creates a detached screen session named `bots` with
five windows:

| Window | Command | Cadence |
|---|---|---|
| `digest` | `storybot/run_digest_daily_loop.sh` | daily at RUN_HOUR (6am local) |
| `twitter` | `storybot/run_twitter_pipeline_loop.sh` | hourly, self-gated |
| `results` | `storybot/run_result_pipeline_loop.sh` | hourly |
| `grader` | `scripts/run_grade_worker_loop.sh` | every 30 min |
| `seo` | `scripts/run_seo_worker_loop.sh` | every 10 min |

Behavior:
- Refuses to start (exit 1, prints reattach hint) if a `bots` session
  already exists.
- Sets screen `zombie kr` mode: a window whose command dies stays open
  showing the final output; `r` relaunches it, `k` closes it. No silent
  disappearance.
- Runs from the project root regardless of invocation directory.

### 2. `scripts/run_grade_worker_loop.sh` (new)

Promotes the inline grader one-liner to a loop script matching the existing
storybot loop-script conventions: activate `venv/`, run
`python backend/grade_worker.py` every `INTERVAL_SECONDS` (default 1800),
tee output to `storybot/logs/grade_worker.log`, clean INT/TERM trap.

### 3. `scripts/run_seo_worker_loop.sh` (new)

Same shape for `backend/seo_worker.py`, default interval 600s, logging to
`storybot/logs/seo_worker.log`.

## Unchanged

- The three storybot loop scripts are reused verbatim.
- `polybot` keeps its own screen session.
- Log locations: all five loop logs live in `storybot/logs/` (already
  gitignored), so `tail -f storybot/logs/*.log` watches everything.

## Cutover

1. Verify each old session is idle (its only child is `sleep`).
2. `screen -S <id> -X quit` the five old sessions (not polybot).
3. Run `scripts/start_bots.sh`; verify five live windows and that the
   grader/seo logs fill on their first pass.

Restart safety: digest recomputes its sleep-until-6am on start; the twitter
pipeline self-gates on its cadence windows; results, grader, and seo are
idempotent one-pass workers, so an immediate extra run is harmless.

## Error handling

Each loop script already absorbs non-zero exits from its python worker and
keeps looping. A crash of the loop script itself is caught by screen's
zombie mode (window persists, `r` to restart).

## Non-goals

- Surviving reboots. Screen sessions don't persist across reboots today and
  this design doesn't change that. systemd user units are the follow-up if
  that's ever wanted.
- Managing `polybot` itself.

## Testing

- `bash -n` / shellcheck on all three scripts.
- Live verification at cutover: `screen -ls` shows exactly `bots` +
  `polybot`; `screen -S bots -Q windows` lists five windows; process tree
  shows each loop alive; grader/seo first-pass output lands in their logs.
