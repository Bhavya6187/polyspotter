# Repo-review follow-up (2026-09-26) — design

Source: `HANDOFF-2026-09-26-open-findings.md` (untracked, repo root), the list of
verified findings deliberately left out of PR #46. This document records how
that list was decomposed, which items ship now, which are held for a product
decision, and the assumptions made while working autonomously.

## Goal

Clear the mechanical, calibration-neutral findings from the handoff in four
independent PRs (one per subsystem), measure the calibration-sensitive items
on real data so the owner can decide them, and finish the post-merge rollout
steps.

## Rollout steps (section 0) — status

| Step | Status on 2026-09-26 |
|------|----------------------|
| Ingest token | Generated, added to local `.env`, set on the Railway backend service. `POST /api/ingest` without the header returns 401 as of 11:40 PT. |
| Scanner restart | The 11:29:51 process was started six seconds before the `git pull` that brought in the resume cap, so it was replaying the 7-day backlog on the old code. Stopped; restarted on the new code after the prune (see session report). |
| SQLite prune | Dry run: 22.45M of 25.7M `price_candles` rows and 23,747 of 45,579 `wallet_pnl` wallets eligible. Real run executed without `--vacuum` while the scanner was stopped. |
| Grader | 16 `graded_calls` in the last 24h; `grade_attempts` is empty (no skips recorded yet). Re-check after the scanner has produced fresh alerts. |
| Claude CLI auth | `loggedIn: true` on the bot host. |

## Decomposition

Four implementation PRs, each on its own worktree/branch, plus this docs branch.

| PR | Branch | Scope (handoff items) |
|----|--------|------------------------|
| A | `fix/scanner-followup` | 1.4 thesis headline cache; 1.5 SELL→BUY remap via Gamma outcomes; 1.7: win-rate fetch-then-swap, orderbook throttle key + index, negative-lookup TTLs, console ranking, docstring, `requirements.txt` |
| B | `fix/backend-followup` | 2.1 `alerts(created_at)` index + batched by-market query + trigram-friendly search; 2.2 miss caching + NBA scoreboard cache; 2.3 slug-date-first game matching, spread sign, soccer slug fallback; 2.4 group_events row consistency, seo_worker regen skip, top3 strength bands, 404s for bad dates, GET unsubscribe confirmation page, cheap HEAD health, 502 detail scrubbing, CORS; new `/api/health/bots` |
| C | `fix/storybot-followup` | 3.1 digest settlement check, pick-step section hygiene, idempotent send, tool-less `claude -p`; 3.2 record-card source consistency, `.posted` sidecar + fail-closed cadence, weighted tweet length, `alert_ids` normalisation, event titles for twitter/article writers, closer-path removal, result-pipeline deletion, log/run-dir rotation |
| D | `fix/frontend-followup` | 4: `useNow()` hydration fix, sitemap index split, 5xx≠404, public cover URLs, tag-slug round trip, PriceChart/CommandPalette races, SEO hygiene, dead-code removal, `npm audit fix` |

## Held for a product decision (measured, not shipped)

These change scoring, gating, the LLM prompt, or strategy semantics. A read-only
analysis agent measured each on live data; its report is attached to the
session summary and should be copied next to this spec when the decision is made.

- **1.1 LLM cache key** ignores trade size and never expires. Options: add a
  score band to the key, add a TTL, or both. Cost impact quantified.
- **1.2 `SYSTEM_PROMPT` rewrite.** Baseline keep rate captured; rewrite needs a
  replay comparison before shipping.
- **1.3 `wallet_clustering` known-funder boost** always fires. Clear bug, but
  fixing it lowers severities ~1.0 and moves alerts across the gate floor;
  count of affected alerts measured.
- **1.6 `pre_event_volume_spike` divisor.** Same reasoning; measured.
- **1.7 dedup indexes + `transactionHash`.** Needs a unique-index rebuild on
  three multi-million-row tables in a 27 GB file: maintenance window.
- **1.7 `wallet_clustering` via `tokentx`.** Changes what "funder" means and
  Etherscan quota; needs its own design.
- **1.7 `correlated_cross_market` joining sibling markets.** Changes alert
  composition and composite scores.
- **2.3 NCAA slugs resolving through NBA aliases.** Needs a data-source decision.
- **2.4 wallet page open positions / >50 closed.** Product scope.
- **5 Astro edge layer / sitemaps.** Outside the repo; investigated, findings in
  the session report.

## Assumptions made autonomously

- **1.5** is treated as a determinism/dedup fix, not a calibration change: every
  Polymarket condition is binary, so remapping SELL to the opposite BUY from
  Gamma `outcomes` only removes duplicate alerts and applies the existing
  favourite filter consistently.
- **top3 strength** bands on the 2026-07 scale: `min(4, max(1, int(score // 2.5)))`
  (1 bar below 5.0, 2 bars 5.0–7.5, 3 bars 7.5–10, 4 bars at 10+). Last-30-day
  max score is 13.7.
- **`/api/health/bots`** returns JSON ages for the newest digest, tweet, graded
  call and alert, and 503 when the digest is older than 30h or the last tweet
  older than 36h. Thresholds are constants for the owner to tune.
- **Result pipeline** files are deleted rather than made to `exit 1`; the
  `follower_snapshots` / `weekly_scoreboards` tables stay in `schema.sql`
  (no destructive migration).
- **Tweet length** is computed with an in-repo weighted-length function
  following X's published rules (URLs 23, Latin/most BMP ranges weight 1,
  everything else weight 2) instead of adding a dependency.
- **Digest idempotency** uses a per-date `sent_at` guard in the `digests` table
  plus Resend's `Idempotency-Key` header.

## Testing

- Scanner/storybot: pytest in `test/`; every fix lands with its failing test first.
- Backend: pytest in `backend/`; DB-backed tests skip unless `TEST_DATABASE_URL`
  is set, so SQL changes are covered by unit tests on the query builders where
  possible and by manual EXPLAIN on production after deploy.
- Frontend: `npm run lint` and `npm run build` must pass; hydration fixes are
  verified by a build plus a manual SSR/CSR check on one page each.

## Out of scope

Anything that needs the owner's calibration judgement (above), the Astro edge
routing, and Railway replica/limit changes tracked in memory.
