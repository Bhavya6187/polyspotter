# Twitter pipeline: chained draft → claude edit → publish workflow

**Date:** 2026-05-10
**Status:** Design
**Owner:** bhavya

## Problem

Today the twitter pipeline is a single-shot script. `python
storybot/twitter_pipeline.py` runs the full chain — seed fetch, quality
floor, event picker, data fetch, chart picker, tweet writer (with retries),
post to X, record in DB — and exits. `storybot/run_twitter_pipeline_loop.sh`
wraps that in a `while true; sleep 18000` loop inside `screen`.

The user wants a Claude Code editing pass inserted between drafting and
posting, mirroring `storybot/run_full_workflow.sh` (the article workflow).
On every loop iteration: the pipeline drafts, Claude reviews/edits, then a
new publisher posts.

The naive way to wire this — pause posting, shell out to Claude, resume
posting — breaks because today's pipeline doesn't persist the drafted tweet
text anywhere a second process can pick it up. The tweet only enters the DB
via `record_tweet` *after* posting. The chart PNG and per-stage transcript
are dumped to `storybot/live_runs/` for debugging, but the tweet body itself
is in-memory only.

So this is a real split: the pipeline has to stop one step earlier and write
a draft artifact, a new publisher has to read that artifact and finish the
job, and the loop shell has to chain them with `claude -p` in the middle.

## Goals

- One loop iteration runs: draft → `claude -p` edit → publish.
- Claude edits a single human-readable `.txt` on disk (not the transcript JSON,
  not a DB row).
- Edits flow through to the posted tweet; the publisher re-reads the file.
- `validate_tweet` runs in the publisher as a defensive check — Claude can't
  push a tweet that exceeds length or contains a banned phrase.
- Any step failure (pipeline error, Claude error, publish validation fail)
  aborts *this iteration's* posting but the outer loop keeps ticking on its
  5-hour cadence.
- The pipeline becomes draft-only: posting only happens through the new
  publisher, removing today's dual-path (one-shot post vs. interactive
  DRY_RUN confirm).

## Non-goals

- LLM re-validation in the publisher. `validate_tweet_anchor` and
  `llm_validate_tweet` already ran during the writer's retry loop; Claude
  has the transcript and is the second human-in-the-loop. Re-running them
  on every publish is paid tokens with no clear benefit, and is not what
  `publish_article.py` does either.
- A Postgres `tweet_drafts` table. The article workflow persists drafts to
  `articles` because the on-site article reads from that table. Tweets have
  no equivalent reader — `record_tweet` is the only DB touchpoint and it
  runs after posting. Disk-only state is sufficient.
- Preserving the existing interactive `DRY_RUN` confirm in
  `twitter_pipeline.py`. The pipeline becomes non-posting; DRY_RUN keeps
  affecting where the draft `.txt` and transcript JSON land but no longer
  triggers an interactive prompt.
- A draft-only mode env flag (`DRAFT_ONLY=true`). The pipeline always
  drafts; there is no posting code path inside it.

## Architecture

Three files change; one is new.

```
storybot/twitter_pipeline.py    ← edit: drop post block, persist draft .txt
storybot/publish_tweet.py       ← new:  load draft, validate, post, record
storybot/run_twitter_pipeline_loop.sh  ← edit: chain draft → claude → publish
```

Draft layout on disk:

```
storybot/twitter_drafts/<run_id>.txt              ← live draft, tweet body only
storybot/dry_runs/twitter_drafts/<run_id>.txt     ← DRY_RUN draft
storybot/live_runs/twitter_pipeline_<run_id>.json ← transcript (existing)
storybot/live_runs/twitter_pipeline_<run_id>.png  ← chart image (existing)
```

The `.txt` is the only file Claude edits. Everything else — transcript JSON,
chart PNG — is read-only context for Claude and metadata for the publisher.

Data flow per iteration:

```
twitter_pipeline.py
  → seeds, picks event, fetches data, picks chart, writes tweet
  → writes <run_id>.txt to storybot/twitter_drafts/
  → augments transcript with publish_meta {alert_ids, chart_type,
                                            target_alert_id,
                                            chart_png_path,
                                            recent_openers,
                                            recent_tweets}
  → prints `[twitter_pipeline] draft run_id=<hex>` on stdout
  → exits 0 (no post, no DB write)

run_twitter_pipeline_loop.sh
  → captures stdout, greps for `draft run_id=<hex>`
  → if missing: skip-path log, sleep, next iteration
  → if present: invokes `claude -p` with the editor prompt
                +--dangerously-skip-permissions
  → claude reads .txt, transcript JSON, chart PNG; edits .txt in place
  → on claude exit 0: runs python storybot/publish_tweet.py <run_id>
  → on claude non-zero: logs failure, does NOT publish, draft stays on disk

publish_tweet.py
  → reads storybot/twitter_drafts/<run_id>.txt
  → reads storybot/live_runs/twitter_pipeline_<run_id>.json → publish_meta
  → reads storybot/live_runs/twitter_pipeline_<run_id>.png if present
  → runs validate_tweet (length + banned phrases)
  → builds twitter clients, calls post_tweet
  → calls record_tweet(alert_ids, tweet_id, tweet_text)
  → logs and exits
```

## Components

### `twitter_pipeline.py` changes

- Delete the entire "Post" block in `main()` (lines ~2010–2052 in the current
  file): `_build_twitter_client`, `_build_twitter_api_v1`, `post_tweet`, the
  `print(f"\n--- Tweet ...")` block, the interactive DRY_RUN confirm, the
  `record_tweet` call. Remove the corresponding `from tweet_utils import …`
  entries for the symbols no longer used here.
- After the existing `_dump_transcript(run_id, transcript)` call, write the
  tweet body to:
  - `storybot/twitter_drafts/<run_id>.txt` when not DRY_RUN
  - `storybot/dry_runs/twitter_drafts/<run_id>.txt` when DRY_RUN
- Before dumping, extend `transcript` with a top-level `publish_meta` key
  containing everything the publisher and Claude need without recomputing:
  - `alert_ids` (from `pick["alert_ids"]`)
  - `chart_type` (from `chart_pick["chart_type"]`)
  - `target_alert_id` (already computed via `_chart_target_alert_id`)
  - `chart_png_path` (absolute path of the saved PNG, or `null` if no chart)
  - `recent_openers` (the list fetched for the writer)
  - `recent_tweets` (the list fetched for the picker/validator)
- Print `[twitter_pipeline] draft run_id=<hex>` after writing the draft. The
  shell parser greps for this exact prefix.
- Return 0.

The skip paths (no alerts in window, all alerts deduped, no alerts cleared
quality floor, event picker chose skip) keep their existing behavior: log,
return 0, no `draft run_id=` line printed. The shell treats absence of that
line as "no draft this iteration."

### `publish_tweet.py` (new)

```
usage: publish_tweet.py <run_id>
```

Flow:

1. Parse `run_id` from `argv[1]`; exit 2 with usage on missing/extra args.
2. Read `storybot/twitter_drafts/<run_id>.txt`. Exit 1 if missing.
3. Read `storybot/live_runs/twitter_pipeline_<run_id>.json`. Pull
   `publish_meta` block. Exit 1 if missing or missing required keys
   (`alert_ids`, `chart_type`, `target_alert_id`, `chart_png_path`).
4. If `chart_png_path` is non-null, read those bytes; otherwise `chart_png =
   None`.
5. Call `validate_tweet(text)` (imported from `twitter_pipeline`). On
   failure, print the validation error to stderr and exit 1 — the draft is
   preserved on disk for inspection.
6. Build `_build_twitter_client()` and `_build_twitter_api_v1()` (latter
   only if `chart_png` is not None).
7. Call `post_tweet(tweet, twitter_client, twitter_api_v1, media_png,
   dry_run=False)`. On exception, log `publish_tweet_post_error` and
   exit 1.
8. Call `record_tweet(alert_ids, tweet_id, tweet)`. Log
   `publish_tweet_record_error` and exit 0 (matches today's pipeline
   behavior — once the tweet is live, record failure is a soft fail).
9. Log `publish_tweet_done` with run_id and tweet_id; exit 0.

No DRY_RUN branch. `publish_tweet.py` always posts.

### `run_twitter_pipeline_loop.sh` changes

Outer shell stays the same (signal trap, log file path, sleep, screen
buffering). Replace the existing single python invocation block with:

```bash
{
    echo ""
    echo "===== run started $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} | tee -a "$LOG_FILE"

output=$(stdbuf -oL -eL python storybot/twitter_pipeline.py 2>&1 | tee -a "$LOG_FILE")
pipeline_status="${PIPESTATUS[0]}"

if [[ "$pipeline_status" -ne 0 ]]; then
    echo "[loop] twitter_pipeline.py exited $pipeline_status — skipping this iteration" | tee -a "$LOG_FILE"
else
    run_id=$(echo "$output" | grep -oP '\[twitter_pipeline\] draft run_id=\K[a-f0-9]+' || true)
    if [[ -z "$run_id" ]]; then
        echo "[loop] no draft produced (pipeline skipped). Sleeping." | tee -a "$LOG_FILE"
    else
        echo "[loop] draft run_id=$run_id — invoking claude to edit" | tee -a "$LOG_FILE"
        prompt="<the editor prompt — see Section 'Claude prompt' below>"
        if claude -p "$prompt" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
            if python storybot/publish_tweet.py "$run_id" 2>&1 | tee -a "$LOG_FILE"; then
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
```

Key points:

- No `set -e` in the loop body. Every sub-step's failure is caught and
  logged so the outer loop keeps running.
- The shell does NOT post unless Claude exits 0 and `publish_tweet.py` exits
  0 sequentially.
- Orphaned drafts (claude or publish failed) sit in `storybot/twitter_drafts/`
  for human inspection; the next iteration starts a fresh draft on a
  different `run_id`. No cleanup logic — orphans accumulate slowly and are
  cheap.

### Claude prompt

The literal prompt string the shell passes to `claude -p`:

```text
Review and edit the twitter pipeline draft with run_id=$run_id.

The draft tweet is at @storybot/twitter_drafts/$run_id.txt — edit this file
directly. Keep it postable: the workflow runs @storybot/publish_tweet.py
right after you finish and will re-validate before posting. If the draft is
fine, leave it alone; if it has problems, fix them.

The full transcript with every stage's input and output (event picker, data
bundle, facts bundle, chart picker, writer attempts, recent tweets the
picker saw) is at @storybot/live_runs/twitter_pipeline_$run_id.json — open
it whenever you need to verify a claim in the tweet.

The chart that will be attached is at
@storybot/live_runs/twitter_pipeline_$run_id.png — open it to confirm the
tweet's hook actually anchors to what the image shows.

Fix these before finishing:

1. FACT FIDELITY. Every concrete number in the tweet (dollar amounts,
   win-loss tuples like 'X-Y', percentages, ROI %, cents prices, cluster
   sizes, minutes-to-resolution) must be reachable in the transcript's
   facts_bundle, trades, or chosen_alerts. The bot has a known habit of
   inflating wallet records and inventing cluster sizes. If you can't verify
   a number in the transcript, either replace it with the actual value from
   there or rewrite the line to drop the specific stat.

2. CHART ANCHOR. The tweet's lede must match the chart that will be
   attached. transcript.stages.3_chart_picker.hook_anchor tells you what
   the chart was chosen to anchor — the tweet's opening must reference the
   same subject (the specific wallet, the specific price move, the specific
   cluster). Don't open with an unrelated angle.

3. LENGTH AND BANNED PHRASES. publish_tweet.py re-runs validate_tweet, which
   rejects: tweet length > TWEET_MAX_CHARS (twitter-counted, not raw len)
   and any banned phrase from _BANNED_TWEET_PHRASES (see
   @storybot/tweet_utils.py for the exact list). Stay under length and
   avoid the banned phrasing.

4. OPENER FRESHNESS. The transcript's publish_meta.recent_openers field has
   the last 5 tweet openers we've shipped. The first ~6 words of this tweet
   must not be a near-paraphrase of any of them — we don't want a feed that
   all sounds the same.

Refer to validate_tweet and validate_tweet_anchor in
@storybot/twitter_pipeline.py for the exact validator rules if anything is
unclear. publish_tweet.py runs immediately after you finish, so the tweet
must be in a postable state.
```

## Error handling

| Failure                          | Behavior                                                    |
|----------------------------------|-------------------------------------------------------------|
| `twitter_pipeline.py` exits ≠ 0  | Log, no claude, no publish, sleep to next iteration.        |
| Pipeline emits no `draft run_id` | Skip path (no alerts / quality floor / dedup). Sleep.       |
| `claude -p` exits ≠ 0            | Log, no publish, draft preserved on disk. Sleep.            |
| `validate_tweet` fails in publisher | Publisher exits 1. Log. Draft preserved. No retry. Sleep. |
| `post_tweet` raises              | Publisher logs `publish_tweet_post_error`, exits 1.         |
| `record_tweet` raises            | Publisher logs `publish_tweet_record_error`, exits 0 (tweet is already live; soft fail). |

The loop never aborts. Errors are always log-and-continue.

## Testing

- **Manual smoke run.** With pipeline + publisher in place but loop shell
  unchanged: run `python storybot/twitter_pipeline.py`, confirm draft `.txt`
  and transcript appear, then run `python storybot/publish_tweet.py
  <run_id>` and confirm the tweet posts and gets recorded.
- **DRY_RUN draft path.** `DRY_RUN=true python storybot/twitter_pipeline.py`
  writes to `storybot/dry_runs/twitter_drafts/`. The publisher never reads
  from there, so a stray DRY_RUN draft cannot accidentally publish.
- **Loop shell smoke.** Start the loop, watch the first iteration: confirm
  the `===== run started =====` line, the `draft run_id=` line, the claude
  invocation logs, the publish logs, and the `===== run finished =====`
  line. Detach the screen and confirm it keeps ticking.
- **Loop survival.** Inject a failure (`mv venv venv.bak` briefly during a
  run) and confirm the loop logs the failure and proceeds to the next
  sleep. No need for a formal pytest — the failure paths are linear shell
  branches.

## Open questions

None.
