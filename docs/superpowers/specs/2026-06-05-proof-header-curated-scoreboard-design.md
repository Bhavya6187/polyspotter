# Proof Header Reframe + Curated Scoreboard

**Date:** 2026-06-05
**Status:** Approved design, pending implementation plan
**Area:** `backend/grading.py`, `backend/app.py`, `backend/models.py`, `frontend/src/components/ScoreboardHero.jsx`

## Problem

The home page proof header (`ScoreboardHero.jsx`) displays three co-equal stats:
`W–L record` · `copy return %` · `hit rate`. Analysis of the 736 graded calls
(last 30 days) showed:

1. **Hit rate is a price artifact, not a skill signal.** It tracks entry price
   almost mechanically (≈25¢ entry → ≈26% hit; ≈85¢ entry → ≈88% hit) because
   Polymarket is roughly calibrated. Leading with 64% invites the (half-correct)
   objection "you're just buying favorites." Within any price band, conviction
   (`composite_score`) adds nothing.
2. **Copy return is the honest edge.** It is flat-to-negative at high entry
   prices, so a persistent +12–14% across hundreds of calls cannot be faked by
   buying favorites. It should lead, not trail.
3. **Recurring crypto coin-flips dilute the record.** The 70 calls tagged as
   recurring/short-duration crypto price markets (BTC up-or-down, etc.) are
   return-negative (−6.6% avg) and contribute no copy edge. Excluding them moves
   30-day copy return from **+12.3% → +14.3%** with hit rate essentially
   unchanged.
4. **Category is the real edge axis.** Among recognizable categories with a
   meaningful sample, return (not hit rate) separates them: Tennis (+20%),
   MLB (+19%), Soccer (+17%) carry the book; NBA/WNBA/Valorant bleed it.

## Goals

- Reframe the header to lead with copy return (the unfakeable edge) and drop
  hit rate and the W–L record entirely.
- Compute the displayed numbers off a **curated** graded set that excludes the
  recurring-crypto coin-flips, retroactively and reversibly.
- Add a specificity hook ("Sharpest in: Tennis · MLB · Soccer") sourced from
  per-category return.

## Non-Goals (YAGNI)

- No `grade_worker.py` change — exclusion is a display-layer filter only.
- No schema migration / new columns / new tables.
- No `avg_entry` field (hit rate is gone, so it is unneeded).
- No bankroll compounding — the dollar figure assumes flat $100 per call.

## Design

### 1. Exclusion (query-time, retroactive) — `backend/grading.py`

`alerts.tags` is a JSON-encoded text column (`TEXT DEFAULT '[]'`, e.g.
`'["Sports","NBA"]'`), so values must be `json.loads`-parsed before comparison.

Add a tunable constant and a pure helper:

```python
JUNK_TAGS = {
    "Crypto", "Crypto Prices", "Recurring", "Bitcoin", "Ethereum",
    "Up or Down", "5M", "Daily", "Weekly", "Hide From New",
}

def _row_tags(row) -> set[str]:
    """Parse a graded row's joined alerts.tags JSON into a set (robust to
    None / malformed JSON → empty set)."""

def exclude_junk(rows):
    """Drop rows whose tags intersect JUNK_TAGS (recurring crypto coin-flips)."""
    return [r for r in rows if not (_row_tags(r) & JUNK_TAGS)]
```

This is the same tag set that produced the quoted +14.3% / 666-call figures, so
the headline number and the methodology stay consistent.

### 2. Categories — `backend/grading.py`

```python
META_TAGS = {"Sports", "Games"}   # too broad to be a "category"
CATEGORY_MIN_CALLS = 20           # meaningful-sample floor
TOP_CATEGORIES = 3

def top_categories(rows, window_days: int = 30):
    """Per-tag aggregate over the windowed curated rows. Exclude META_TAGS and
    JUNK_TAGS, require >= CATEGORY_MIN_CALLS, rank by avg return desc, return the
    top TOP_CATEGORIES as {name, calls, hit_rate, return_pct}."""
```

On current data this yields **Tennis · MLB · Soccer**.

### 3. Scoreboard endpoint — `backend/app.py`

- `_scoreboard_rows()` query gains a join to expose tags and entry price:
  ```sql
  SELECT g.market_title, g.outcome, g.won, g.return_pct, g.entry_price,
         g.event_slug, g.resolved_at, a.tags
  FROM graded_calls g
  JOIN alerts a ON a.id = g.alert_id
  ORDER BY g.resolved_at DESC
  ```
  (`entry_price` is selected for completeness/future use; not surfaced in v1.)
- `get_scoreboard()` filters once: `curated = exclude_junk(rows)`, then derives
  `window` / `all_time` / `recent` **and** `categories` from `curated`, so the
  excluded coin-flips disappear everywhere. The 120s cache is unchanged.
- Cache key/shape: response gains `categories`.

### 4. Models — `backend/models.py`

```python
class ScoreboardCategory(BaseModel):
    name: str
    calls: int
    hit_rate: float
    return_pct: float

class ScoreboardResponse(BaseModel):
    window_days: int
    window: ScoreboardWindow
    all_time: ScoreboardWindow
    recent: list[ScoreboardRecentCall]
    categories: list[ScoreboardCategory]   # new
```

`ScoreboardWindow` is unchanged (still carries `hit_rate` for API consumers /
the building-state logic, even though the header no longer renders it).

### 5. Header — `frontend/src/components/ScoreboardHero.jsx`

Remove the W–L `Stat` and the hit-rate `Stat`. New layout (numbers below are
illustrative of current data; all values are computed live from the response —
the dollar line is `copy_return_pct × (wins+losses) × $100`, so on the curated
30-day set it is ≈ +$9.5k, not a hardcoded figure):

```
   +14%   avg return per call · last 30d
   ≈ +$9,100  if you'd put $100 on every call

   Across 666 graded calls, copying Polymarket's sharpest
   wallets returned +14%. We grade every call against the
   result — crypto coin-flips excluded.

   Sharpest in: Tennis · MLB · Soccer

   Get the daily smart-money brief:  [ email ___ ][ → ]
```

- Hero `+14%` = `asSignedPct(window.copy_return_pct)`, colored bullish/bearish
  by sign.
- Dollar sub-line derived client-side: `copy_return_pct × (wins+losses) × $100`,
  rounded. No new API field.
- Sample size (`wins + losses`) folded into the methodology prose, not shown as
  a stat.
- "Sharpest in:" renders `scoreboard.categories[*].name` joined by ` · `; the
  whole line is omitted if `categories` is empty.
- `EmailCapture` stays. The `< MIN_GRADED` building state stays; its count now
  derives from the curated `all_time` total.

### 6. Tests

- `backend/` pytest (pure, no DB):
  - `exclude_junk` removes junk-tagged rows, keeps clean ones, tolerates
    `None` / malformed tags.
  - `summarize` stats match expected on a curated fixture.
  - `top_categories` respects `CATEGORY_MIN_CALLS`, excludes META/JUNK tags,
    ranks by return desc, caps at 3.
- `frontend`: `npm run lint` passes; component renders hero %, derived dollar
  line, and category list from a stub scoreboard.

## Data Flow

```
graded_calls ─┐
              ├─ JOIN alerts.tags ─► _scoreboard_rows()
              │                          │
              │                    exclude_junk()  ──► curated rows
              │                          │
              │            ┌─────────────┼──────────────┐
              │       summarize()   top_categories()  recent[:8]
              │            │             │              │
              └────────────┴──── ScoreboardResponse ────┘
                                         │
                                  /api/scoreboard
                                         │
                                  ScoreboardHero.jsx
                            (+14% hero · ≈+$N · categories)
```

## Risks / Notes

- `JUNK_TAGS` and `META_TAGS` are heuristic tag lists; documented as tunable. If
  a legitimate non-recurring crypto market is tagged `Crypto`, it is excluded —
  acceptable for v1 given the goal (drop coin-flips) and reversibility.
- The added join is over a single-PK table on an indexed FK; negligible cost,
  and the result is cached 120s.
- Exclusion is display-only: `graded_calls` retains every call, so the choice is
  fully reversible by editing `JUNK_TAGS` or removing the filter.
