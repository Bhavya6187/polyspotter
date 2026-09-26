# Scanner follow-up (PR A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the calibration-neutral scanner bugs from the 2026-09-26 handoff: uncached thesis headlines, batch-dependent SELL→BUY remapping, and the small correctness items in 1.7.

**Architecture:** Each task is a local change to one strategy module, `seeder.py` or `db.py`, with a pytest in `test/` written first. No scoring constants change. Worktree: `.worktrees/scanner-followup`, branch `fix/scanner-followup`. Run tests with `/home/bhavya/git/polybot/venv/bin/pytest` from the worktree root (baseline on main: 1224 passed, 37 skipped).

**Tech Stack:** Python 3.13, SQLite via `db.py`, pytest (existing `test/` conventions: patch network with `unittest.mock`, use a temp `db.DB_PATH`).

---

### Task 1: Cache thesis headlines and only build theses for kept alerts (handoff 1.4)

**Files:**
- Modify: `seeder.py` (`build_theses_payload`, `_generate_thesis_headline`)
- Modify: `db.py` (new table `thesis_headlines`)
- Test: `test/test_seeder_theses.py` (extend), new `test/test_thesis_headline_cache.py`

- [ ] Read `seeder.build_theses_payload` and `_generate_thesis_headline`, and `test/test_seeder_theses.py` / `test/test_thesis_headline_logging.py` for how theses are constructed and how GPT calls are patched in tests.
- [ ] Write failing tests: (a) `test_thesis_headline_cached_across_runs` — two calls of the headline generator with the same `(wallet, event_slug, sorted condition_ids)` make exactly one `responses.create` call (patch the OpenAI client) and return the same headline; (b) `test_thesis_headline_cache_key_changes_with_new_market` — adding a condition id to the group triggers a new call; (c) `test_theses_built_only_for_kept_alerts` — a `correlated_cross_market` group whose alert was discarded by the gate/LLM produces no thesis and no GPT call.
- [ ] Run them, confirm they fail for the expected reason.
- [ ] Implement: `db.py` table `thesis_headlines(cache_key TEXT PRIMARY KEY, headline TEXT NOT NULL, created_at REAL NOT NULL)` created in `_init_tables`; helpers `get_thesis_headline(key)` / `save_thesis_headline(key, headline)`. In `seeder.py`, compute `key = f"thesis:{wallet}:{event_slug}:{','.join(sorted(cids))}"`, check the cache before calling GPT, save after. In `build_theses_payload`, take the set of kept alert keys (whatever the caller already has after LLM filtering) and skip groups whose alert was not kept.
- [ ] Run the full suite, commit: `fix(seeder): cache thesis headlines and build theses only for kept alerts`.

### Task 2: Always remap SELL clusters to the opposite BUY (handoff 1.5)

**Files:**
- Modify: `detection_strategies/concentrated_one_sided.py` (~lines 59–70 and ~90)
- Test: `test/test_concentrated_one_sided.py` (extend)

- [ ] Read the strategy and the existing tests. Confirm how it currently decides to remap SELLs (both outcomes present in the batch) and how it fetches Gamma market metadata (`gamma_cache`).
- [ ] Write failing tests: (a) `test_sell_cluster_remaps_without_opposite_outcome_in_batch` — three wallets SELL "No" on a condition whose Gamma outcomes are `["Yes","No"]`; only SELLs are in the batch; the signal is keyed as `Yes:BUY` (or whatever the existing key shape is for buys). (b) `test_sell_cluster_key_stable_across_batches` — the dedup key produced for the SELL-only batch equals the key produced when a Yes BUY is also present. (c) `test_remapped_sell_cluster_respects_favourite_filter` — a SELL cluster whose remapped BUY side is at a price above the favourite threshold is filtered exactly like a native BUY cluster.
- [ ] Run, confirm failures.
- [ ] Implement: derive the opposite outcome from Gamma `outcomes` for the condition (fall back to the batch-based method only if Gamma has no outcomes), remap before keying so the favourite filter and the dedup key see the BUY form. Keep the tests' patched Gamma cache shape consistent with `test/test_gamma_cache.py`.
- [ ] Run the suite, commit: `fix(concentrated_one_sided): remap SELL clusters via Gamma outcomes, not batch contents`.

### Task 3: Fetch positions before wiping the old ones (handoff 1.7, win_rate_tracking)

**Files:**
- Modify: `detection_strategies/win_rate_tracking.py` (~lines 71–72)
- Test: `test/test_win_rate_tracking.py` (extend)

- [ ] Write failing test `test_position_refetch_timeout_keeps_previous_rows`: seed `wallet_pnl` with N rows for a wallet, patch the Data API positions call to raise `requests.Timeout`, run the refresh; assert the wallet still has N rows and `total_positions` is unchanged.
- [ ] Run, confirm failure (rows are wiped).
- [ ] Implement: fetch first; only inside a single transaction delete + insert once the fetch succeeded.
- [ ] Run the suite, commit: `fix(win_rate_tracking): fetch positions before replacing the old rows`.

### Task 4: Orderbook snapshot throttle keyed by token (handoff 1.7, db.py ~1015/1061)

**Files:**
- Modify: `db.py` (snapshot save/throttle and `get_orderbook_stats`)
- Test: new `test/test_orderbook_snapshots.py`

- [ ] Read the two functions and the table definition (find the table name and columns; note the 764k-row production table has no `token_id` index).
- [ ] Write failing tests: (a) `test_second_token_snapshot_not_throttled_by_first` — save a snapshot for token A of condition C, then immediately for token B of C; both rows exist. (b) `test_same_token_snapshot_throttled_within_window` — a second save for token A within 10 minutes is dropped. (c) `test_orderbook_snapshot_index_exists` — after `get_db()`, `sqlite_master` has an index covering `(condition_id, token_id)` (or `token_id`) on the snapshot table.
- [ ] Run, confirm failures.
- [ ] Implement: throttle on `(condition_id, token_id)`; add `CREATE INDEX IF NOT EXISTS` in `_init_tables`/`_migrate`. Note in the commit message that the index build runs once at scanner startup on the production file.
- [ ] Run the suite, commit: `fix(db): throttle orderbook snapshots per token and index the table`.

### Task 5: Negative lookups expire (handoff 1.7)

**Files:**
- Modify: `detection_strategies/new_wallet_large_bet.py` (~line 72), `detection_strategies/wallet_clustering.py` (~lines 130, 173)
- Test: `test/test_new_wallet_large_bet.py`, `test/test_wallet_clustering.py` (extend)

- [ ] Write failing tests: (a) `test_profile_404_not_cached_forever` — a 404 profile lookup is retried after the negative TTL elapses (patch `time.time`); (b) `test_funder_none_cache_respects_db_retry` — an in-memory `None` funder does not prevent the DB's 7-day NULL retry from re-querying once that window has passed.
- [ ] Run, confirm failures.
- [ ] Implement: store `(value, expires_at)` in the in-memory caches with a module constant `NEGATIVE_TTL_S = 6 * 3600` for profiles; for funders, do not cache `None` in memory at all (let the DB row's retry timestamp govern).
- [ ] Run the suite, commit: `fix(strategies): expire negative lookup caches`.

### Task 6: Console summary ranking, docstring, requirements (handoff 1.7)

**Files:**
- Modify: `polybot.py` (`_format_summary`, `filter_resolved_markets` docstring)
- Modify: `requirements.txt`
- Test: new `test/test_format_summary.py`

- [ ] Write failing test `test_format_summary_ranks_by_composite_score`: two alerts where raw severity sum and `compute_composite_score` disagree on ordering; the summary lists the higher composite first.
- [ ] Run, confirm failure; implement by ranking with `compute_composite_score`; fix the docstring to state 0.95.
- [ ] `requirements.txt`: list every direct dependency imported by the scanner, storybot and scripts (grep imports across `*.py` excluding `backend/`, `venv/`, `frontend/`; at least `requests`, `python-dotenv`, `openai`, `matplotlib`, `Pillow`, `psycopg2-binary`, `dateparser`, `tweepy`, `cachetools`, `jmespath`, `pytest`), pinned to the versions in `venv` (`pip freeze | grep -i <name>`). Do not add `backend/requirements.txt` items that the scanner does not import.
- [ ] Run the suite, commit: `chore(scanner): composite-ranked console summary, docstring, complete pinned requirements`.

### Task 7: Final check

- [ ] Run `/home/bhavya/git/polybot/venv/bin/pytest -q` from the worktree root; expect the baseline count plus the new tests, zero failures.
- [ ] Run `/home/bhavya/git/polybot/venv/bin/ruff check .` on changed files (config in `pyproject.toml`).
- [ ] Report status with the list of commits.
