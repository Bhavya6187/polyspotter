# Backend follow-up (PR B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the backend performance, robustness and correctness findings in sections 2.1–2.4 of the 2026-09-26 handoff and add a bot-freshness health endpoint.

**Architecture:** FastAPI app in `backend/app.py` (2.7k lines) with sync psycopg2 queries; sport overlays in `backend/sports/`. Tests live in `backend/` and DB-backed tests skip unless `TEST_DATABASE_URL` is set, so query changes are tested through pure helper functions where possible. Worktree: `.worktrees/backend-followup`, branch `fix/backend-followup`. Run tests with `cd backend && /home/bhavya/git/polybot/venv/bin/pytest -q` (baseline: 193 passed, 37 skipped).

**Tech Stack:** Python 3.13, FastAPI, psycopg2, Pydantic, pytest with `TestClient`.

---

### Task 1: Index and batched by-market query (handoff 2.1)

**Files:**
- Modify: `backend/schema.sql` (add `CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts (created_at DESC);`)
- Modify: `backend/app.py` (`/api/alerts/by-market` handler; the `q=` search predicate)
- Test: `backend/test_endpoints.py` (extend) and a new pure-function test

- [ ] Read the by-market handler. Extract the per-market child query into a helper that takes the list of condition ids and a per-market cap and returns one SQL string + params using `condition_id = ANY(%s)` with `row_number() OVER (PARTITION BY condition_id ORDER BY composite_score DESC, created_at DESC)`.
- [ ] Write failing tests: (a) `test_by_market_child_query_is_single_statement` — the helper returns one statement containing `ANY(` and `row_number()` and the cap; (b) `test_search_predicate_uses_trigram_operator` — the search predicate builder returns `%s <% market_title` (trigram word-similarity operator) rather than `word_similarity(...) > 0.2`.
- [ ] Run, confirm failures; implement. Wire the handler to issue the batched query once per page. Confirm how `schema.sql` is applied in production (grep for it in `app.py`/Dockerfile); if it is not applied automatically, add the index to whatever migration path exists and say so in the commit message.
- [ ] Run the suite, commit: `perf(api): index alerts(created_at), batch by-market children, trigram-friendly search`.

### Task 2: Cache negative overlay results and the NBA scoreboard (handoff 2.2)

**Files:**
- Modify: `backend/sports/basketball.py` (~lines 771–788), `backend/app.py` (event page Gamma lookups for unknown slugs)
- Test: `backend/test_basketball.py` (extend)

- [ ] Write failing tests: (a) `test_missing_predictor_is_cached_as_miss` — with ESPN patched to return no predictor, two consecutive overlay requests make one ESPN summary fetch; (b) `test_scoreboard_fetched_once_per_ttl` — two NBA-path requests within the TTL make one scoreboard fetch; (c) for the event page: `test_unknown_event_slug_miss_is_cached` — two requests for an unknown slug make one Gamma call.
- [ ] Run, confirm failures; implement with a module-level sentinel (`_MISS = object()`) stored in the existing cache with a shorter TTL (`MISS_TTL_S = 300`), and cache the scoreboard under a date key. Reduce outbound timeouts to 5s where they are 10s.
- [ ] Run the suite, commit: `perf(sports): cache overlay misses and the NBA scoreboard`.

### Task 3: Match the slug's game before today's scoreboard; fix spread sign and soccer fallback (handoff 2.3)

**Files:**
- Modify: `backend/sports/basketball.py` (~688–704, 820–822, 301–306), `backend/sports/cricket.py` (~642–645), `backend/sports/soccer.py` (~507–510, `can_handle`), `backend/sports/mlb.py` (~498–501), `backend/sports/nhl.py` (~407–410)
- Test: `backend/test_basketball.py`, `backend/test_soccer.py`, `backend/test_mlb.py`, `backend/test_nhl.py`, cricket tests (extend each)

- [ ] For each overlay, write a failing test where the slug date is tomorrow and today's scoreboard also has the same two teams (a series or doubleheader): the overlay must return tomorrow's game (status `pre`) not today's.
- [ ] Write `test_spread_sign_home_favoured`: home favoured by 4.5 yields `SpreadInfo.value == -4.5` for the home side (match the convention the frontend displays; read `frontend/src/components` basketball overlay to confirm the sign it expects and state it in the test's docstring).
- [ ] Write `test_soccer_can_handle_slug_fallback`: a slug that only matches via the fallback path returns True.
- [ ] Run, confirm failures; implement by resolving the slug date first and consulting today's scoreboard only when the slug date is today or missing; remove the hardcoded `status="pre"` / 0-0 in the ESPN-only basketball path by reading the real status.
- [ ] Run the suite, commit: `fix(sports): resolve the slug's game before today's scoreboard; spread sign; soccer slug fallback`.

### Task 4: Correctness odds and ends (handoff 2.4)

**Files:**
- Modify: `backend/app.py` (group_events rows ~743, `/api/top3` strength, articles/digest date parsing, `/api/unsubscribe`, `/api/health`, 502 handler, CORS), `backend/seo_worker.py` (~68–82)
- Test: `backend/test_endpoints.py`, `backend/test_seo_worker_skip.py`, `backend/test_subscribe.py`, `backend/test_digest_api.py` (extend)

- [ ] group_events: write a failing test on the SQL builder that the representative columns come from one row (`(array_agg(... ORDER BY composite_score DESC))[1]` or `DISTINCT ON`), then implement.
- [ ] seo_worker: failing test `test_worker_copies_existing_seo_instead_of_regenerating` — a new alert row on a market that already has `seo_title` set gets the existing fields copied and no GPT call; implement.
- [ ] top3 strength: update `test_top3_strength_banding` to `min(4, max(1, int(score // 2.5)))` and implement.
- [ ] Dates: failing tests that `/api/articles/by-slug/2026-13-45/x` and `/api/digest/2026-13-45` return 404, not 500; parse with `date.fromisoformat` inside a `try` and raise `HTTPException(404)`.
- [ ] Unsubscribe: failing test that `GET /api/unsubscribe?token=...` returns 200 HTML containing a form that POSTs to the same URL and does not change the subscriber row; `POST` (RFC 8058 `List-Unsubscribe=One-Click`) still unsubscribes. Check `storybot/digestbot.py` builds the email link to the GET URL and keep it working.
- [ ] Health: failing test that `HEAD /api/health` does not run `COUNT(*)` (patch the cursor and assert the statement uses `EXISTS`/`LIMIT 1`, or a `MAX(created_at)` on the indexed column); implement.
- [ ] 502s: failing test that the upstream exception text is not in the response body (a generic message plus a logged detail); implement.
- [ ] CORS: read the `CORSMiddleware` config. If `allow_credentials=True` is combined with wildcard origins, set `allow_credentials=False` (nothing uses cookies) and add a test asserting the response headers.
- [ ] Run the suite, commit: `fix(api): group_events row consistency, seo copy, strength bands, date 404s, unsubscribe confirm, cheap health, scrubbed 502s`.

### Task 5: `/api/health/bots` (handoff 5)

**Files:**
- Modify: `backend/app.py`, `backend/models.py`
- Test: `backend/test_endpoints.py` (extend)

- [ ] Read `backend/schema.sql` for `digests`, `tweeted_alerts`, `graded_calls`, `alerts` timestamp columns.
- [ ] Write failing tests with a patched DB cursor: (a) fresh timestamps → 200 with JSON `{digest_age_h, tweet_age_h, graded_age_h, alert_age_h, stale: []}`; (b) digest 40h old → 503 with `stale: ["digest"]`; (c) tweet 50h old → 503 with `stale: ["tweet"]`.
- [ ] Implement with constants `DIGEST_STALE_H = 30`, `TWEET_STALE_H = 36`; graded and alert ages are informational only (alerts are covered by `/api/health`). Support `HEAD` cheaply.
- [ ] Document the endpoint in the `app.py` module docstring list and in `README.md`'s endpoint table.
- [ ] Run the suite, commit: `feat(api): /api/health/bots reports digest and tweet freshness`.

### Task 6: Final check

- [ ] `cd backend && /home/bhavya/git/polybot/venv/bin/pytest -q` — baseline plus new tests, zero failures.
- [ ] `/home/bhavya/git/polybot/venv/bin/ruff check backend` on changed files.
- [ ] Report status with the list of commits and any item where production application (index creation) needs a manual step.
