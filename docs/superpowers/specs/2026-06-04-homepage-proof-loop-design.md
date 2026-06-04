# Homepage Proof Loop — Design Spec

**Date:** 2026-06-04
**Status:** Approved for planning
**Goal:** Turn the PolySpotter homepage into a daily-habit engine by proving the smart-money signals work, then capturing email to pull users back.

## Problem

The site gets little engagement. The homepage is a competent but undifferentiated feed: five stacked widgets (Top 3, follow strip, ticker, resolving-soon, filters) above a paginated list of 885 markets. Two gaps drive the low engagement:

1. **No proof.** The entire pitch is "copy the sharps," but nothing shows whether the alerts actually won. Without a visible track record there is no trust and no reason to return.
2. **No return trigger.** It's a feed that looks the same every visit. Nothing brings a user back tomorrow.

## Strategy: the Proof Loop

> **Show copying works → capture email → email pulls them back with fresh proof.**

This MVP threads three pieces thinly rather than fully building any one:

| Piece | Role |
|---|---|
| **A. Scoreboard** | The trust hook — graded track record of our calls |
| **B. Email loop** | The return trigger — capture + daily digest |
| **C. Homepage redesign** | The conversion surface that feeds A → B |

## Key Decisions (locked)

- **Hero:** scoreboard-first (proof is the headline).
- **Unit of record:** one deduped call per resolved market — the single highest-conviction (top `composite_score`) alert on that market is "our call." Avoids contradictory/duplicate alerts on one game muddying the record.
- **Copy-return model:** hypothetically stake **$100 flat per call** at the alert's `copy_action.entry_price`, **equal-weight**, **held to resolution**. Win → payout at $1.00/share (return = `(1 - entry)/entry`); loss → −100%. One whale can't dominate; simple to explain.
- **Windows:** headline = rolling **30 days**; **all-time** also computed and shown secondarily.
- **Follow mechanic:** **deferred to v2.** MVP "Sharps to follow" is a browsable leaderboard linking to wallet pages. No accounts/auth in this MVP.
- **Digest:** a single **global** daily brief (not personalized).
- **Email provider:** **Resend** (swappable behind a thin interface), single opt-in + unsubscribe link.
- **Email capture** appears in the hero **and** repeated at the bottom of the feed.

## Architecture

Three subsystems, matching the existing repo split (scanner / backend / frontend).

### A. Scoreboard — grading engine

Reuses the existing settlement detection already in the backend (`_is_market_settled(closed, uma_status, prices)` + Gamma `closed=true` retry; winning outcome inferred from `outcomePrices` ≈ 1.0). Grading pattern mirrors the scanner's existing `tracked_bets` resolved/won flow.

**New Postgres table `graded_calls`** (one row per resolved market we featured):

| column | type | notes |
|---|---|---|
| `alert_id` | int FK→alerts | the chosen highest-conviction alert |
| `condition_id` | text | |
| `event_slug` | text | |
| `market_title` | text | denormalized for display |
| `outcome` | text | from `copy_action.outcome` |
| `entry_price` | double | from `copy_action.entry_price` |
| `resolved_outcome` | text | winning outcome from Gamma |
| `won` | bool | |
| `return_pct` | double | `(1-entry)/entry` if won else −1.0 |
| `composite_score` | double | the call's score (for "highest-conviction" audit) |
| `resolved_at` | timestamptz | |
| `graded_at` | timestamptz | |

Unique on `condition_id` (one call per market).

**Grading job** (`backend/grade_worker.py`, cron ~ every 30–60 min):
1. Find featured markets with resolved status not yet in `graded_calls`. "Featured" = above the homepage `composite_score` threshold (same threshold the homepage list uses), so it matches what readers saw.
2. For each, pick top-score alert as the call.
3. Fetch resolution via existing Gamma settlement helper; determine winning outcome.
4. Compute `won` + `return_pct`; upsert into `graded_calls`.
5. Skip 50-50 / cancelled resolutions (exclude from record; log count).

**New endpoint `GET /api/scoreboard`:**
```json
{
  "window_days": 30,
  "wins": 47, "losses": 19, "hit_rate": 0.71,
  "copy_return_pct": 2.12,
  "all_time": { "wins": ..., "losses": ..., "hit_rate": ..., "copy_return_pct": ... },
  "recent": [
    {"market_title":"Padres v Phillies","outcome":"San Diego Padres","won":true,"return_pct":0.63,"event_slug":"...","resolved_at":"..."}
  ]
}
```
`recent` = last ~8 graded calls for the receipts strip.

### B. Email loop

**New Postgres table `subscribers`:** `id, email (unique), created_at, confirmed (bool, default true for single opt-in), unsubscribe_token (uuid), source (text), unsubscribed_at`.

**New endpoint `POST /api/subscribe`** `{email, source}` → validates, upserts, returns 200 (idempotent). Basic rate-limit + email-format validation. Honeypot field to deter bots.

**New endpoint `GET /api/unsubscribe?token=...`** → marks unsubscribed, returns a confirmation page.

**Email sender abstraction** (`backend/email_sender.py`): thin `send(to, subject, html)` wrapping Resend's API, keyed off `RESEND_API_KEY`. Provider-swappable.

**Daily digest job** (`backend/digest_worker.py`, cron 1×/day ~13:30 UTC, after articlebot's 13:00 run — kept in `backend/` since it needs the DB, Resend, and the scoreboard, reading article content from the `articles` table): composes one HTML brief =
- Scoreboard line (30d record + copy return)
- Today's PolySpotter article teaser (reuse `articles` table content)
- Top 3 sharpest live calls (from `/api/top3`)
- 3–4 recent receipts (from `graded_calls`)
- Unsubscribe footer

Sends to all confirmed subscribers. `DRY_RUN=true` prints instead of sending (mirrors articlebot convention).

### C. Homepage redesign

New top-to-bottom order in `home-client.jsx`:

1. **Header** — unchanged (brand, search, live, theme).
2. **ScoreboardHero** *(new)* — `GET /api/scoreboard`; big 30d record + copy return + hit rate, value-prop line, inline email form (`POST /api/subscribe`).
3. **RecentCalls receipts** *(new)* — `scoreboard.recent`; chips with ✓/✗ + return %, each linking to the market/alert.
4. **Today's sharpest calls** *(reframed `TopThree`)* — relabel; same data.
5. **ResolvingSoonStrip** *(kept, condensed)*.
6. **SharpsLeaderboard** *(new, Follow deferred)* — top wallets by win-rate/PnL using existing `pseudonym.js` for names; links to wallet pages. No follow button in MVP.
7. **Latest moves** *(reframed feed)* — existing `AlertList` + `Filters`, demoted below curated content.
8. **Email capture (repeat)** *(new)* — same subscribe form at the foot of the feed.

**Removed:** `Ticker` from the homepage (code comment already notes it "duplicates feed"). `TopThreeFollowStrip` folded into the leaderboard concept (or removed).

New components: `ScoreboardHero.jsx`, `RecentCalls.jsx`, `EmailCapture.jsx` (shared by hero + footer), `SharpsLeaderboard.jsx`. New API client methods: `fetchScoreboard()`, `subscribeEmail()`.

## Data Flow

```
scanner → alerts (Postgres)
grade_worker (cron) → reads resolved alerts + Gamma settlement → graded_calls
backend /api/scoreboard → aggregates graded_calls
homepage ScoreboardHero/RecentCalls → renders proof
homepage EmailCapture → POST /api/subscribe → subscribers
articlebot (cron 13:00) → articles
digest_worker (cron 13:30) → scoreboard + article + top3 + receipts → Resend → subscribers' inboxes
```

## Error Handling

- **Cold start / empty record:** if `graded_calls` has < N (e.g. 10) rows, the hero shows a "Building our track record — N calls graded so far" state instead of a misleading tiny sample. Receipts strip hides until ≥ 3 rows.
- **Gamma unavailable / ambiguous resolution:** grading job leaves the market ungraded and retries next run; never guesses a winner.
- **Subscribe failures:** form shows inline error, never blocks page; duplicate email returns success (idempotent).
- **Email send failures:** per-recipient try/catch, log + continue; digest job is idempotent per day (dedup table or date guard) so a re-run doesn't double-send.
- **No subscribers / no article:** digest job no-ops with a log line.

## Testing

- **Grading (pytest, backend):** win/loss/return math for YES/NO resolutions; dedup to one call per market (highest score wins); 50-50 excluded; idempotent upsert.
- **Scoreboard endpoint:** aggregation math, 30d window boundary, empty/cold-start shape.
- **Subscribe endpoint:** valid/invalid email, idempotency, honeypot rejection, unsubscribe token flow.
- **Digest composer:** assembles all sections; `DRY_RUN` prints and sends nothing; no-subscriber no-op.
- **Frontend:** `npm run lint`; ScoreboardHero renders cold-start vs populated; EmailCapture success/error states.

## Out of Scope (v2+)

- Per-user **Follow** + personalized digests + accounts/auth.
- Web push / browser notifications.
- "Since you last visited" anonymous diff.
- Double opt-in / advanced deliverability (DKIM tuning beyond Resend defaults).

## Build Order

1. **A — grading engine + `/api/scoreboard`** (foundation; nothing is believable without it).
2. **C — ScoreboardHero + RecentCalls + homepage reorder** (makes proof visible).
3. **B — subscribe endpoint + EmailCapture form** (start collecting audience).
4. **B — digest job** (closes the loop).

Each step is independently shippable and adds standalone value.
