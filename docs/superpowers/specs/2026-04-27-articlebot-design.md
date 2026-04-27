# Articlebot — Daily X Article Generator

**Date:** 2026-04-27
**Status:** Spec

## Problem

[storybot/storybot.py](../../../storybot/storybot.py) and the other Twitter bots (`twitter_simple.py`, `twitter_pipeline.py`) all produce short-form content — a single tweet or a 3-5 tweet thread — picked from a 3-hour alert window. They give the timeline a constant heartbeat but they never *develop* a story: the format caps research depth, forces wallet/market/strategy color into ~280 chars per beat, and reaches only an audience already on Polymarket Twitter.

We want a second content surface aimed at **growing followers among a general audience**: people who follow the news but don't speak desk slang. The format that fits is a short article (500-700 words) — long enough to introduce a wallet/market/bet to a stranger, short enough that someone scrolling past on Twitter will actually read it.

This spec describes **`articlebot.py`**, a new daily bot that:

1. Looks at the last 24 hours of alerts (vs. today's 3-hour window).
2. Tournament-picks the single most interesting event-level story.
3. Researches it deeply with the same `query`-tool agent the threads use.
4. Writes a short article (~500-700 words, markdown) and renders one cover chart.
5. Persists the draft to Postgres + disk; a human pastes it into the X article composer manually.

Articlebot lives alongside the existing storybots — none of them are replaced.

## Out of scope

- Replacing `storybot.py` or any of the existing Twitter bots.
- Auto-posting to X. v1 is human-paste only (X Articles have no public REST creation endpoint, and we want a quality gate before going live).
- Hosting articles on polyspotter.com. The article body is self-contained on X; it merely *links to* polyspotter market/wallet/alert pages.
- New chart types. We reuse [storybot/charts.py](../../../storybot/charts.py) and the chart picker pattern from [storybot/twitter_pipeline.py](../../../storybot/twitter_pipeline.py).
- Inline images beyond a single cover chart.
- Slack/email notifications. The cron's stdout is the notification surface.
- An admin UI for browsing drafts (deferrable; out of v1).
- Multi-article-per-day mode, per-tag schedules, or per-vertical bots.

## Architecture

```
[cron, daily 13:00 UTC]
   │
   ▼
fetch_24h_event_summaries()
        │  ── SQL: alerts grouped by event_slug over last 24h, joined with
        │         signals; Gamma-settled filter applied (reuses _gamma_status_for_markets)
        ▼
tournament_picker()
        │  ── stage 1: chunked picker (40 events/chunk, reasoning_effort=medium)
        │       → top-3 finalists per chunk
        │  ── stage 2: final picker over ~15-30 finalists (reasoning_effort=high)
        │       → ONE event_slug + alert_ids
        │       → dedup against last 7 days of articles
        ▼
prefetch_bundle(scope)         ── reused unchanged from storybot.py
        │
        ▼
research_agent()
        │  ── reused agent loop from storybot.py with bumped budgets:
        │       MAX_TOOL_CALLS=40, MAX_ITERATIONS=35
        │  ── new system prompt → article-shaped JSON output
        ▼
render_cover_chart()
        │  ── dispatches `cover_chart_spec` to charts.py
        │  ── soft fault on render failure
        ▼
persist_article()
        │  ── INSERT into `articles` (Postgres)
        │  ── write articles/<run_id>.md and articles/<run_id>.png
        ▼
print path to stdout           ── human pastes into X article composer
```

New code:

- `storybot/articlebot.py` — entrypoint, tournament picker, system prompt, output validator, storage.
- `storybot/style_rules.py` — voice/style rules extracted from `storybot.py`'s system prompt as a string constant; both bots import it. (See "Voice rules" below.)
- `storybot/articles/` directory for `.md` + `.png` files.
- `storybot/mark_published.py` — small CLI to flip an article row from `draft` to `published`.
- `_migrate_add_articles(cur)` block in [backend/database.py](../../../backend/database.py).

Reused unchanged:

- `storybot/bot_utils.py` (DB clients, `_accumulate_usage`, `_compact_alert_for_picker`).
- `storybot/tweet_utils.py` (chart rendering helpers, `_POLYSPOTTER_URL_RE`, `_BANNED_TWEET_PHRASES`).
- `storybot/compressor.py` (the `query` tool for the research agent).
- `storybot/storybot.py`'s `prefetch_bundle()`, `_make_dispatcher()`, `_assistant_tool_message()`, and the agent-loop body — extracted into a small import surface as part of this work so articlebot can call them. (Pure relocation; no behavior change to the thread bot.)

## Tournament picker

Replaces the single-pass `pick_story()` in `storybot.py`.

### Stage 0 — SQL pre-aggregation

A new query (sibling to `SEED_ALERTS_SQL` in [storybot/bot_utils.py](../../../storybot/bot_utils.py)):

```sql
SELECT
    a.event_slug,
    MAX(a.composite_score)        AS top_composite,
    SUM(a.total_usd)              AS event_usd,
    COUNT(*)                      AS alert_count,
    ARRAY_AGG(DISTINCT s.strategy)
        FILTER (WHERE s.strategy IS NOT NULL) AS strategies_fired,
    JSON_AGG(jsonb_build_object(
        'id', a.id,
        'composite_score', a.composite_score,
        'alert_type', a.alert_type,
        'market_title', a.market_title,
        'wallet', a.wallet,
        'total_usd', a.total_usd,
        'tags', a.tags,
        'llm_headline', a.llm_headline,
        'cluster_headline', a.cluster_headline,
        'condition_id', a.condition_id,
        'game_start_time', a.game_start_time,
        'event_end_estimate', a.event_end_estimate,
        'end_date', a.end_date,
        'created_at', a.created_at
    ) ORDER BY a.composite_score DESC)        AS alerts,
    MIN(a.created_at)             AS first_alert_at,
    MAX(a.created_at)             AS last_alert_at
FROM alerts a
LEFT JOIN alert_signals s ON s.alert_id = a.id
WHERE a.created_at >= NOW() - INTERVAL '24 hours'
  AND (
      (a.game_start_time IS NOT NULL AND a.game_start_time > NOW())
      OR (a.game_start_time IS NULL
          AND COALESCE(a.event_end_estimate, a.end_date) > NOW())
  )
  AND a.event_slug IS NOT NULL
GROUP BY a.event_slug
ORDER BY top_composite DESC
LIMIT 300
```

Then the same Gamma `_is_settled` filter `fetch_seed_alerts()` already applies, batched against the distinct condition_ids referenced by surviving events. Settled events drop out.

300 is a hard cap; below the cap we work with what we have. Above it, the cap drops the lowest-composite events first (we trust composite_score for shortlisting; we don't trust it for *picking*).

### Stage 1 — chunked first-round picker

Split the survivors into chunks of 40. For each chunk, one LLM call:

- **System prompt:** "You're surfacing the most *story-worthy* events for a daily article. Prefer color/narrative over composite_score. A high score with no human angle is less interesting than a medium score with a strong character (sharp wallet, coordinated squad, surprise market, late timing). Return the top 3 event_slugs as JSON: `{"finalists": ["slug-a", "slug-b", "slug-c"], "reasoning": "<one sentence>"}`. Skip is NOT an option here — pick the best 3 you've got, even on a quiet chunk; the next stage handles the skip."
- **User content:** the chunk's events, each compacted to: event_slug, top_composite, event_usd, alert_count, strategies_fired, top 3 alerts (`_compact_alert_for_picker` shape), first/last alert timestamps.
- **Reasoning effort:** medium (filtering, not deciding).
- **Failure handling:** invalid JSON or LLM error → drop the chunk's finalists. Other chunks proceed.

Output: up to ~22 finalist event_slugs (300/40 ≈ 7-8 chunks × 3).

### Stage 2 — final picker

One LLM call over the finalists:

- **System prompt:** "Pick the SINGLE best story for today's article — or skip if nothing on this list is good enough to write about for a general audience. The article will be ~600 words, will quote specific numbers, and will be the only thing we publish today. If the best story on this list is generic, return decision=skip. Recently-covered events you must skip unless something materially new has happened (a new sharper wallet, a meaningful price move, a resolution): {recent_event_slugs}. Voice: smart financial Twitter that a curious news-following adult who doesn't speak desk slang can read."
- **User content:** the finalists with their full compact alert payloads; plus `recent_event_slugs` from the last 7 days of `articles` rows (excluding `status='skipped'`).
- **Reasoning effort:** high.
- **Output JSON:** `{"decision": "post"|"skip", "event_slug": "...", "alert_ids": [...], "reason": "..."}` — same shape `pick_story()` produces today, just with `event_slug` added for clarity.
- **Failure handling:** any error or invalid JSON → hard skip. Better than publishing a bad pick.

The downstream agent loop receives `chosen_alerts` (the alerts matching the chosen `alert_ids`) — identical contract to today's storybot.

## Article output format

The research agent's final assistant message is JSON:

```jsonc
{
  "decision": "post" | "skip",
  "reason": "one short sentence",
  "article": {                                // null when skip
    "headline": "…",                          // ≤ 90 chars
    "subhead": "…",                           // ≤ 160 chars, dek under headline
    "body_markdown": "…",                     // 450-800 words; see "Body shape"
    "cover_alt_text": "…"                     // ≤ 200 chars
  },
  "alert_ids": [<int>, ...] | null,           // alerts the article is about
  "cover_chart_spec": {                       // null = no cover; article still ships
    "chart_type": "wallet_record_card" | "price_sparkline" |
                  "volume_bar" | "cluster_card",
    "alert_id": <int>,                        // which alert's data
    "params": {…}                             // passed to charts.py fetcher
  }
}
```

### Body shape

The system prompt mandates and the validator enforces:

1. **Opening paragraph** (the hook). 2-3 sentences. Stakes baked in, story in one line — same rule as today's tweet HOOK. Doesn't restate the headline.
2. **3-4 body sections**, each headed by an `## H2`. The model picks 3-4 from this menu (it doesn't need all of them; it picks what fits the story):
   - `## The wallet` (or `## The squad` for clusters)
   - `## The bet`
   - `## What the market thinks`
   - `## What to watch`
   - `## The track record`
   - `## The other side`
   The H2 menu is documented in the prompt; the validator only enforces that body_markdown contains 3-4 lines starting with `## ` (no specific titles required, but the prompt gives the menu).
3. **Closing paragraph** with the catalyst/level/wallet to track, and **1-2 polyspotter.com links inline** in markdown link syntax (`[anchor text](https://polyspotter.com/market/<slug>)`). At least one polyspotter link is MANDATORY; validator enforces.

### Validation rules (hard, validator enforces, one model retry on failure)

- `decision` is `"post"` or `"skip"`.
- When `decision="post"`:
  - `article` is non-null; `headline` ≤ 90 chars and non-empty; `subhead` ≤ 160 chars and non-empty; `cover_alt_text` ≤ 200 chars when present.
  - `body_markdown` word count between 450 and 800 inclusive (slight tolerance around the 500-700 target).
  - `body_markdown` contains 3-4 lines matching `^## \w+`.
  - `body_markdown` contains ≥ 1 polyspotter.com URL matching `_POLYSPOTTER_URL_RE` (reused from `tweet_utils`).
  - `body_markdown` contains zero banned phrases (`_BANNED_TWEET_PHRASES`, reused).
  - `alert_ids` is a non-empty list of integers.
- On any validation failure: one retry with a targeted user message naming the specific rule violated. Second failure → skip with `reason="validation failed: <details>"`.

### Cover chart

`cover_chart_spec` is optional. If present, after JSON validation:

- Dispatch to `charts.py` using the existing `chart_type` enum and the alert_id from the spec.
- Render a PNG to `articles/<run_id>.png`.
- On render failure: log, set `cover_path=NULL`, ship the article without a cover. Soft fault.

The model picks the chart type using a small embedded reference in the system prompt (mirroring the existing `twitter_pipeline.py` chart picker stage), keyed off which signals fired:

| Story shape | Suggested chart |
|---|---|
| One sharp wallet's record carries the story | `wallet_record_card` |
| Price moved on the market | `price_sparkline` |
| Volume spike | `volume_bar` |
| Coordinated squad / clustering | `cluster_card` |
| Story doesn't lean on one chart | `null` (no cover) |

## Voice rules

The voice rules in `storybot.py`'s `SYSTEM_PROMPT` (banned phrases, first-use unpack rules, number readability rules, the rewrite table, the analyst-speak ban) are extracted into `storybot/style_rules.py` as a single multi-line string constant `STYLE_RULES`. Both bots import it and inline it into their respective system prompts.

This is a pure relocation. The thread bot's system prompt assembles to the exact same string it does today; the article bot's prompt uses the same `STYLE_RULES` plus the article-specific instructions (length, H2 menu, polyspotter link requirement, etc.).

The article system prompt's voice paragraph is unchanged from the thread bot's: "smart financial-twitter — Matt Levine writing about Polymarket, not a desk trader Slack."

## Storage

### `articles` Postgres table

Migration added to [backend/database.py](../../../backend/database.py) as `_migrate_add_articles(cur)`, called from `_run_migrations` (idempotent, runs at startup):

```sql
CREATE TABLE IF NOT EXISTS articles (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL UNIQUE,
    event_slug      TEXT NOT NULL,
    alert_ids       INTEGER[] NOT NULL,
    headline        TEXT NOT NULL,
    subhead         TEXT NOT NULL,
    body_markdown   TEXT NOT NULL,
    cover_alt_text  TEXT,
    cover_path      TEXT,
    md_path         TEXT NOT NULL,
    word_count      INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
        -- 'draft' | 'published' | 'skipped'
    posted_url      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_articles_event_slug
    ON articles (event_slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_status
    ON articles (status, created_at DESC);
```

When `decision="skip"`, articlebot still inserts a row with `status='skipped'`, `body_markdown=''`, `headline=''`, etc., minimal placeholders — for audit trail and observability (so we can answer "did the bot run today, and what did it decide?" by looking at one table). The picker dedup query explicitly excludes `status='skipped'` rows: skipping an event today shouldn't bar us from covering it next week if it grows into something real.

### Files on disk

`storybot/articles/<run_id>.md`:

```markdown
# {headline}

*{subhead}*

![cover]({run_id}.png)

{body_markdown}

---
run_id: {run_id} | event_slug: {event_slug} | alert_ids: [...]
posted_url: <fill in after publishing>
```

`storybot/articles/<run_id>.png` — the cover chart (skipped if `cover_chart_spec=null` or render failed).

Mirrors the existing `storybot/dry_runs/` layout. The directory is gitignored (already covered by existing `dry_runs/` patterns; a one-line addition to `.gitignore` covers `storybot/articles/`).

### Dry-run mode

`ARTICLEBOT_DRY_RUN=true`:

- Renders the chart into `storybot/dry_runs/<run_id>.png` (not `articles/`).
- Writes a transcript JSON to `storybot/dry_runs/<run_id>.json` (same shape as today's storybot dry-run dump, plus the article fields).
- Does NOT insert into Postgres.
- Does write the `.md` file to `storybot/dry_runs/<run_id>.md` so the human can preview.

### `mark_published.py` helper

Single-purpose CLI:

```bash
python storybot/mark_published.py <run_id> <x_article_url>
```

Updates the `articles` row: `status='published'`, `posted_url=<url>`, `posted_at=NOW()`. Validates that the URL is `https://x.com/...` or `https://twitter.com/...`. Errors loudly if the run_id doesn't exist or is already published.

## Run modes and entrypoint

```bash
# Daily cron (13:00 UTC suggested)
source venv/bin/activate
python storybot/articlebot.py

# Dry run (no DB write, full LLM trace dumped to dry_runs/)
ARTICLEBOT_DRY_RUN=true python storybot/articlebot.py
```

Cron schedule: `0 13 * * *` UTC = 9am ET. Suggested, not load-bearing — easy to change later.

## Errors and skip philosophy

Same as `storybot.py`: skip the run cleanly when in doubt; never publish a bad article.

| Failure | Behavior |
|---|---|
| Stage-1 chunk picker errors | Drop chunk's finalists; continue |
| Stage-2 final picker errors | Hard skip; insert `status='skipped'` row; exit 0 |
| `MAX_ITERATIONS` exhausted in agent | Skip with reason; exit 0 |
| Final JSON invalid | One retry; second failure → skip |
| Validation rule violation | One retry with targeted hint; second failure → skip |
| Chart rendering fails | Soft fault; ship article with `cover_path=NULL` |
| Postgres insert fails | Log loud; .md file already on disk; exit 1 |
| Gamma-settled filter API fails | Degrade gracefully (same fallback `fetch_seed_alerts` already does) |

## Tests

Mirror today's `test/` layout. Add four files:

- `test/test_articlebot_picker.py` — tournament picker logic. LLM monkeypatched to return canned JSON. Cases: 0 events, 1 event, 1 chunk, multiple chunks, all chunks return invalid JSON, dedup against prior articles excludes a recently-covered event, stage-2 skip propagates.
- `test/test_articlebot_validator.py` — output validator. Cases: word count too low, too high, just right; missing polyspotter link; only 2 H2s (fail) / 3 H2s (pass) / 4 H2s (pass) / 5 H2s (fail); banned phrase in body; missing alert_ids on post.
- `test/test_articlebot_storage.py` — articles table insert path; `mark_published.py` update path. Real Postgres (test schema) via the existing test fixtures.
- `test/test_articlebot_e2e.py` — single end-to-end run with all LLM and tool calls monkeypatched. Asserts: `articles` row inserted, `.md` file on disk with expected content, `.png` rendered, `mark_published.py` flips status correctly.

The shared agent-loop code factored out of `storybot.py` keeps its existing tests; we don't duplicate them.

## Tool-call budget and reasoning effort

| Stage | `MAX_TOOL_CALLS` | `MAX_ITERATIONS` | `reasoning_effort` |
|---|---|---|---|
| Stage-1 chunk picker | n/a (no tools) | n/a | medium |
| Stage-2 final picker | n/a (no tools) | n/a | high |
| Research agent | 40 | 35 | high |

Articles need more research than threads: the user's request was "investigate as deeply as possible." 40/35 is roughly 2x today's storybot budgets. The agent's existing `forcing_final` budget-exhaustion logic is reused unchanged — if the agent burns through its tool budget, it gets one prompt to write the article with what it has.

## Decisions

**Why a new file (`articlebot.py`) instead of a flag on `storybot.py`?** The two bots have different cadence (daily vs hourly), different windows (24h vs 3h), different picker strategies (tournament vs single-pass), and different output shapes (article vs thread). Sharing a single file behind a flag would gate everything behind a mode check. Two files reading from a shared `style_rules.py` (and the relocated agent-loop helpers) is cleaner.

**Why tournament picker (D1) instead of stratified single picker (D2)?** Stratified buckets bias the shortlist by tag heuristics — but "general-audience interesting" cuts across tags (an obscure-market story can beat a sports story for color even though sports has more 24h volume). Letting the model judge in batches is the only approach that stays close to "interesting" at scale, and the user's "break it up into multiple requests" language fits the tournament shape directly.

**Why human-paste (B1) instead of auto-post?** X Articles have no public REST creation endpoint as of writing. v1 is human-in-the-loop both because the API forces it and because we want a quality gate while we're tuning the prompt. Once the bot is producing publish-ready output ≥ 90% of runs, we can revisit (e.g., switch to long-form tweet auto-post, or paste via X's RUM-detected web automation, or whatever the API surface looks like by then).

**Why one cover chart and no inline charts?** A 600-word article with two charts becomes a chart-with-captions. One cover image ahead of the text is the format X Articles is built for and the format readers expect. Inline charts can come later if the analytics show they help.

**Why reuse the existing voice rules verbatim instead of writing article-specific ones?** The existing voice rules are already explicitly tuned for general readers (the first-use-unpack rules for "wallet"→"account", framing prices as probabilities, banning trader/analyst jargon). They were built for the same audience this article targets — just at a different length. Reusing them keeps the article and thread bots feeling like the same publication.

**Why insert a `status='skipped'` row instead of tracking skips separately?** Audit trail. Operators ask "did the bot run today, and what did it decide?" — and one table with a status column answers that with a single query. Skip rows do NOT participate in picker dedup (skipping today doesn't perma-bar an event); they exist purely for observability.

## Open questions deferred to implementation

- Exact wording of the stage-1 vs stage-2 picker prompts (will be tuned during implementation against a few real days of dry-runs).
- Whether `JSON_AGG` vs joining on the side is faster in the stage-0 SQL on the production DB (will benchmark; both are correct).
- The exact set of polyspotter.com URLs the agent prefers (market vs wallet vs alert vs tag) — the existing storybot system prompt has a section on this; articlebot will inherit the same URL-construction logic and we'll let the model pick contextually.

## Files touched

New:
- `storybot/articlebot.py`
- `storybot/style_rules.py`
- `storybot/mark_published.py`
- `storybot/articles/` (directory; gitignored)
- `test/test_articlebot_picker.py`
- `test/test_articlebot_validator.py`
- `test/test_articlebot_storage.py`
- `test/test_articlebot_e2e.py`

Modified:
- `storybot/storybot.py` — voice rules extracted to `style_rules.py`; agent-loop helpers (`prefetch_bundle`, `_make_dispatcher`, `_assistant_tool_message`, the loop body) made importable. No behavior change.
- `backend/database.py` — `_migrate_add_articles(cur)` added and wired into `_run_migrations`.
- `.gitignore` — add `storybot/articles/`.
