# Storybot follow-up (PR C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the digest and twitter pipeline findings in section 3 of the 2026-09-26 handoff and remove the retired results pipeline.

**Architecture:** `storybot/digestbot.py` (pick + write + send), `storybot/twitter_pipeline.py` / `publish_tweet.py` / `tweet_utils.py`, shell loops in `storybot/*.sh`. Tests live in `test/` (and `storybot/test_digestbot*.py`). Worktree: `.worktrees/storybot-followup`, branch `fix/storybot-followup`. Run tests with `/home/bhavya/git/polybot/venv/bin/pytest -q` from the worktree root (baseline: 1224 passed, 37 skipped, includes the storybot tests).

**Tech Stack:** Python 3.13, psycopg2 (Postgres) and `db.py` (SQLite), Resend HTTP API, tweepy, `claude -p` CLI.

---

### Task 1: Digest never features settled markets (handoff 3.1)

**Files:**
- Modify: `storybot/digestbot.py` (candidate selection, `_WEEK_HOT_SQL`)
- Test: `storybot/test_digestbot.py` (extend)

- [ ] Find how the twitter and article bots check settlement (`_gamma_status_for_markets` / `_is_settled` in `storybot/bot_utils.py` or `twitter_pipeline.py`).
- [ ] Write failing tests: (a) `test_digest_candidates_drop_settled_markets` — with Gamma patched to report one candidate as settled, it is absent from both sections; (b) `test_week_hot_sql_requires_end_date` — the week-pool SQL contains a `end_date IS NOT NULL` (or equivalent) predicate.
- [ ] Run, confirm failures; implement by calling the shared settlement check on the union of candidates before the PICK step.
- [ ] Commit: `fix(digestbot): exclude settled markets and NULL end dates from candidates`.

### Task 2: PICK step section hygiene (handoff 3.1, ~lines 849–856)

**Files:**
- Modify: `storybot/digestbot.py`
- Test: `storybot/test_digestbot.py` (extend)

- [ ] Write failing tests: (a) `test_today_picks_only_from_today_pool` — an LLM response that lists a week-pool slug under "Resolving Today" is dropped from that section; (b) `test_event_not_in_both_sections` — a slug returned in both sections appears only in "Resolving Today"; (c) `test_resolving_today_capped` — more slugs than the cap (read the number the prompt asks for and use that constant) are truncated in the LLM's order.
- [ ] Run, confirm failures; implement as a pure `normalise_picks(llm_picks, today_pool, week_pool, cap)` used by the PICK step.
- [ ] Commit: `fix(digestbot): validate PICK output against the pools and cap Resolving Today`.

### Task 3: Idempotent send (handoff 3.1)

**Files:**
- Modify: `storybot/digestbot.py` (send path), `backend/schema.sql` (add `sent_at TIMESTAMPTZ` to `digests` if absent)
- Test: `storybot/test_digestbot.py` (extend)

- [ ] Read how the digest row is written and how the email is sent (Resend request construction).
- [ ] Write failing tests: (a) `test_send_skipped_when_already_sent_today` — a `digests` row for today with `sent_at` set means no email request and no overwrite of the web version; (b) `test_send_sets_sent_at_and_idempotency_key` — the Resend request carries header `Idempotency-Key: digest-<YYYY-MM-DD>` and `sent_at` is written after success.
- [ ] Run, confirm failures; implement. If the column must be added, add it to `schema.sql` and include an `ALTER TABLE digests ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ` in whatever migration path the backend uses at startup; state in the commit message that production needs it applied before the next digest run.
- [ ] Commit: `fix(digestbot): idempotent send per day`.

### Task 4: Tool-less `claude -p` for the digest write pass (handoff 3.1)

**Files:**
- Modify: `storybot/digestbot.py` (the `claude -p` invocation)
- Test: `storybot/test_digestbot.py` (extend)

- [ ] Run `claude --help` and identify the flag that disables all built-in tools for `-p` mode (expected: `--tools ""`; if unavailable, use `--allowedTools ""` with `--disallowedTools` covering Bash, Edit, Write, WebFetch, WebSearch, Agent). Record the flag in the docstring.
- [ ] Write failing test `test_digest_claude_invocation_disables_tools`: the argv passed to `subprocess` contains the tool-disabling flag and does not contain `--dangerously-skip-permissions`.
- [ ] Run, confirm failure; implement.
- [ ] Commit: `fix(digestbot): run the write pass without tools`.

### Task 5: Twitter record card uses the same wallet and source as the text (handoff 3.2)

**Files:**
- Modify: `storybot/twitter_pipeline.py` (card fetcher and facts bundle)
- Test: `test/test_twitter_pipeline_facts_bundle.py` (extend)

- [ ] Read how the facts bundle picks the "best" wallet and W-L record and how `wallet_record_card` picks its wallet.
- [ ] Write failing test `test_record_card_matches_text_record`: for a cluster alert with two wallets whose SQLite and Postgres records differ, the card is built for the wallet chosen by the facts bundle and shows the same W-L numbers as the tweet text.
- [ ] Run, confirm failure; implement by passing the chosen wallet and its record (from the facts bundle) into the card fetcher instead of re-selecting.
- [ ] Commit: `fix(twitter): record card uses the tweet's wallet and record`.

### Task 6: Posting is never lost (handoff 3.2, `publish_tweet.py:141-170`)

**Files:**
- Modify: `storybot/publish_tweet.py`, `storybot/run_twitter_pipeline_loop.sh`, `storybot/twitter_pipeline.py` (`fetch_recent_tweets`)
- Test: `test/test_publish_tweet.py`, `test/test_twitter_pipeline_cadence.py` (extend)

- [ ] Write failing tests: (a) `test_posted_sidecar_written_before_record` — after a successful API post, `<draft>.posted` exists containing the tweet id even if `record_tweet` raises; the exit code is non-zero and the draft file still exists; (b) `test_rerun_with_posted_sidecar_does_not_repost` — a second run with the sidecar present makes no API post, records the tweet, then removes the draft and sidecar; (c) `test_ambiguous_post_error_marks_pending` — a 503 / `RemoteDisconnected` from the post call writes `<draft>.pending` and exits non-zero without deleting the draft; (d) `test_fetch_recent_tweets_db_error_fails_closed` — on a DB error the cadence gate treats the state as unknown and does not post.
- [ ] Run, confirm failures; implement. Update the loop script so `.pending` drafts are skipped with a logged line telling the operator to check X before deleting the marker.
- [ ] Commit: `fix(twitter): .posted/.pending sidecars, fail-closed cadence gate`.

### Task 7: Weighted tweet length and `alert_ids` normalisation (handoff 3.2)

**Files:**
- Modify: `storybot/tweet_utils.py` (~164–167), `storybot/publish_tweet.py`, `storybot/twitter_pipeline.py` (`validate_event_pick`)
- Test: `test/test_twitter_pipeline_validation.py`, `test/test_publish_tweet.py` (extend), new `test/test_tweet_weighted_length.py`

- [ ] Write failing tests for `weighted_length(text)`: `"abc"` → 3; `"…"` → 2; `"→"` → 2; an emoji → 2; `"see example.com today"` counts the bare domain as 23; NFC normalisation (`"é"` → 1). Add `test_length_check_uses_weighted_length` for the existing validator at the 280 boundary.
- [ ] Implement `weighted_length` per X's v3 rules: normalise NFC; weight 1 for code points in ranges 0–4351, 8192–8205, 8208–8223, 8242–8247; weight 2 otherwise; URLs and bare domains (detect with a conservative regex for `scheme://` or `word.tld` with a known TLD list of at least com/net/org/io/co/gov/edu/xyz/ai/app) count 23.
- [ ] Write failing test `test_alert_ids_accept_numeric_strings`: `validate_event_pick` output with `"123"` passes `publish_tweet`'s check as `123`; implement by normalising with `int()` at the validation boundary.
- [ ] Commit: `fix(twitter): weighted tweet length, integer alert_ids`.

### Task 8: Event titles for twitter and article writers (handoff 3.2)

**Files:**
- Modify: `storybot/twitter_pipeline.py`, `storybot/articlebot.py`
- Test: `test/test_twitter_pipeline_draft.py`, `test/test_articlebot_pipeline_improvements.py` (extend)

- [ ] Find `fetch_event_titles` / `attach_event_titles` used by the digest (PR #44) and the prompt-building points in the twitter and article writers.
- [ ] Write failing tests: the writer prompt text contains the real event title for the picked market (and not only `market_title` + slug) in both bots.
- [ ] Run, confirm failures; implement by reusing the digest helpers.
- [ ] Commit: `fix(storybot): feed real event titles to the twitter and article writers`.

### Task 9: Remove the closer path and the retired results pipeline (handoff 3.2)

**Files:**
- Delete: `storybot/run_result_pipeline_loop.sh`, `storybot/result_pipeline.py`, `storybot/publish_result.py`, and `storybot/result_store.py` only if nothing else imports it after the closer removal; the eight `test/test_result_*.py` files and `test/test_track_record_closer.py`.
- Modify: `storybot/twitter_pipeline.py` (`recent_record()`, `_attach_track_record_closer`), `storybot/run_twitter_pipeline_loop.sh` (prompt item 5), `scripts/start_bots.sh` comments if they reference deleted files.
- Test: `test/test_twitter_pipeline_draft.py` (extend)

- [ ] `grep -rn "result_store\|result_pipeline\|publish_result\|recent_record\|_attach_track_record_closer\|closer_decision" --include=*.py --include=*.sh --include=*.md .` (exclude venv/frontend) and list every reference before deleting.
- [ ] Write failing test `test_no_track_record_closer_in_draft`: a draft is produced without any "Recent flags:" closer and the code path no longer exists (`hasattr` false).
- [ ] Delete files, remove the code path and the prompt item, keep `follower_snapshots` / `weekly_scoreboards` tables in `schema.sql` untouched. Leave `test_follower_snapshot.py` / `test_weekly_scoreboard.py` if their modules still exist and are used elsewhere; otherwise delete module and test together and say so.
- [ ] Run the suite; commit: `chore(storybot): remove the retired results pipeline and track-record closer`.

### Task 10: Rotate logs and run directories (handoff 3.2)

**Files:**
- Modify: `storybot/run_twitter_pipeline_loop.sh`, `storybot/run_digest_daily_loop.sh`, `scripts/run_grade_worker_loop.sh`, `scripts/run_seo_worker_loop.sh` (or a shared `scripts/rotate_logs.sh` sourced by all four)
- Test: new `test/test_rotate_logs.py` running the script with `bash` on a temp tree

- [ ] Write failing test: given a temp `storybot/logs/x.log` of 25 MB and `storybot/live_runs/` entries older than 30 days and newer than 30 days, running the rotation keeps `x.log` under 20 MB with a single `x.log.1`, deletes only the old run directories.
- [ ] Implement `scripts/rotate_logs.sh` (`find "$ROOT/storybot/live_runs" -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} +`; for each `*.log` over 20 MB: `mv f f.1`) and call it once per loop iteration from each loop script.
- [ ] Commit: `chore(bots): rotate storybot logs and prune live_runs older than 30 days`.

### Task 11: Final check

- [ ] `/home/bhavya/git/polybot/venv/bin/pytest -q` from the worktree root; zero failures.
- [ ] `/home/bhavya/git/polybot/venv/bin/ruff check` on changed files; `bash -n` on changed shell scripts.
- [ ] Report status with commits and the list of production steps (schema column, operator note on `.pending`).
