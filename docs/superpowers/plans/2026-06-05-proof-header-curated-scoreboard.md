# Proof Header Reframe + Curated Scoreboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the home page proof header to lead with copy return (dropping hit rate and the W–L record), computed off a curated graded set that excludes recurring-crypto coin-flips, plus a per-category "Sharpest in" hook.

**Architecture:** Pure helpers in `backend/grading.py` (`exclude_junk`, `top_categories`) filter and aggregate graded rows; `/api/scoreboard` joins `alerts.tags`, filters once, and derives window/all_time/recent/categories off the curated rows; the model gains a `categories` field; `ScoreboardHero.jsx` renders the new hierarchy. Exclusion is display-only and reversible — `grade_worker.py` and the DB schema are untouched.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic / pytest (backend); Next.js 15 / React 19 / ESLint (frontend). `alerts.tags` is JSON-encoded text (e.g. `'["Sports","NBA"]'`).

**Reference spec:** `docs/superpowers/specs/2026-06-05-proof-header-curated-scoreboard-design.md`

---

## File Structure

- Modify: `backend/grading.py` — add `JUNK_TAGS`, `META_TAGS`, `CATEGORY_MIN_CALLS`, `TOP_CATEGORIES`, `_row_tags`, `exclude_junk`, `top_categories`.
- Modify: `backend/models.py:999-1019` — add `ScoreboardCategory`, add `categories` to `ScoreboardResponse`.
- Modify: `backend/app.py:74` (import), `:1318-1358` (`_scoreboard_rows`, `get_scoreboard`).
- Modify: `backend/test_grading.py` — tests for `exclude_junk`, `top_categories`.
- Modify: `backend/test_scoreboard.py` — tests for junk exclusion + categories in the endpoint.
- Modify: `frontend/src/components/ScoreboardHero.jsx` — new header layout.

All commands assume the repo root `/home/bhavya/git/polybot` and an activated venv (`source venv/bin/activate`) unless a `cd` is shown.

---

## Task 1: `exclude_junk` + tag parsing in grading.py

**Files:**
- Modify: `backend/grading.py`
- Test: `backend/test_grading.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_grading.py`:

```python
from grading import exclude_junk, JUNK_TAGS


def test_exclude_junk_drops_junk_tagged_rows():
    rows = [
        {"won": True, "return_pct": 0.5, "tags": '["Sports","MLB"]'},      # keep
        {"won": False, "return_pct": -1.0, "tags": '["Crypto Prices"]'},   # drop
        {"won": True, "return_pct": 0.2, "tags": '["Up or Down","5M"]'},   # drop
    ]
    out = exclude_junk(rows)
    assert len(out) == 1
    assert out[0]["tags"] == '["Sports","MLB"]'


def test_exclude_junk_tolerates_missing_and_malformed_tags():
    rows = [
        {"won": True, "return_pct": 0.5},                  # no tags key -> keep
        {"won": True, "return_pct": 0.5, "tags": None},    # None -> keep
        {"won": True, "return_pct": 0.5, "tags": "not json"},  # malformed -> keep
        {"won": True, "return_pct": 0.5, "tags": '["Bitcoin"]'},  # junk -> drop
    ]
    out = exclude_junk(rows)
    assert len(out) == 3


def test_junk_tags_includes_recurring_crypto_set():
    assert {"Crypto Prices", "Bitcoin", "Up or Down", "Recurring"} <= JUNK_TAGS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_grading.py -k "exclude_junk or junk_tags" -v`
Expected: FAIL with `ImportError: cannot import name 'exclude_junk'`.

- [ ] **Step 3: Implement `JUNK_TAGS`, `_row_tags`, `exclude_junk`**

In `backend/grading.py`, add `import json` under the existing `from datetime import ...` line, then add after the module docstring constants (after `RESOLVED_THRESHOLD`):

```python
# Recurring / short-duration crypto price markets (BTC up-or-down, etc.) are
# return-negative coin-flips where copying adds no edge. Excluded from the
# public scoreboard at query time (display-only; rows stay in graded_calls).
JUNK_TAGS = {
    "Crypto", "Crypto Prices", "Recurring", "Bitcoin", "Ethereum",
    "Up or Down", "5M", "Daily", "Weekly", "Hide From New",
}


def _row_tags(row) -> set:
    """Parse a graded row's joined alerts.tags (JSON text) into a set of tag
    strings. Tolerates a missing key / None / non-string / malformed JSON by
    returning an empty set (so such rows are never treated as junk)."""
    raw = row.get("tags")
    if isinstance(raw, (list, tuple)):
        return set(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return set()
        return set(parsed) if isinstance(parsed, list) else set()
    return set()


def exclude_junk(rows):
    """Drop rows whose tags intersect JUNK_TAGS (recurring crypto coin-flips)."""
    return [r for r in rows if not (_row_tags(r) & JUNK_TAGS)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_grading.py -k "exclude_junk or junk_tags" -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/grading.py backend/test_grading.py
git commit -m "feat(scoreboard): exclude_junk helper to drop recurring-crypto calls"
```

---

## Task 2: `top_categories` in grading.py

**Files:**
- Modify: `backend/grading.py`
- Test: `backend/test_grading.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_grading.py`:

```python
from grading import top_categories


def _cat_row(tags, won, return_pct, days_ago=1):
    return {
        "tags": tags,
        "won": won,
        "return_pct": return_pct,
        "resolved_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


def test_top_categories_ranks_by_return_and_caps_at_three():
    rows = []
    # Tennis: 25 calls, avg return +0.20
    rows += [_cat_row('["Tennis"]', True, 0.20) for _ in range(25)]
    # MLB: 25 calls, avg return +0.10
    rows += [_cat_row('["MLB"]', True, 0.10) for _ in range(25)]
    # Soccer: 25 calls, avg return +0.05
    rows += [_cat_row('["Soccer"]', True, 0.05) for _ in range(25)]
    # NBA: 25 calls, avg return -0.10 (4th by return, dropped by top-3)
    rows += [_cat_row('["NBA"]', False, -0.10) for _ in range(25)]
    cats = top_categories(rows, window_days=30)
    assert [c["name"] for c in cats] == ["Tennis", "MLB", "Soccer"]
    assert cats[0]["calls"] == 25
    assert round(cats[0]["return_pct"], 4) == 0.20


def test_top_categories_requires_min_sample():
    rows = [_cat_row('["Tennis"]', True, 0.5) for _ in range(19)]  # below 20
    assert top_categories(rows, window_days=30) == []


def test_top_categories_excludes_meta_and_junk_tags():
    # Every row also carries the broad "Sports"/"Games" meta tags and a junk tag;
    # only the real category ("Soccer") should surface.
    rows = [_cat_row('["Sports","Games","Soccer","Bitcoin"]', True, 0.1)
            for _ in range(20)]
    cats = top_categories(rows, window_days=30)
    assert [c["name"] for c in cats] == ["Soccer"]


def test_top_categories_ignores_out_of_window_rows():
    rows = [_cat_row('["Tennis"]', True, 0.5, days_ago=45) for _ in range(25)]
    assert top_categories(rows, window_days=30) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_grading.py -k top_categories -v`
Expected: FAIL with `ImportError: cannot import name 'top_categories'`.

- [ ] **Step 3: Implement `top_categories` + constants**

In `backend/grading.py`, add these constants right after the `JUNK_TAGS` block:

```python
# "Sharpest in" hook: rank recognizable categories by avg copy return.
META_TAGS = {"Sports", "Games"}   # too broad to read as a "category"
CATEGORY_MIN_CALLS = 20           # meaningful-sample floor
TOP_CATEGORIES = 3
```

Then add this function at the end of `backend/grading.py`:

```python
def top_categories(rows, window_days: int = 30):
    """Top categories by avg copy return over the windowed rows.

    Aggregates per tag (excluding META_TAGS and JUNK_TAGS), requires at least
    CATEGORY_MIN_CALLS calls, ranks by avg return desc, and returns up to
    TOP_CATEGORIES entries as {name, calls, hit_rate, return_pct}. Pass rows
    that are already junk-excluded; the 30-day window is applied here."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    skip = META_TAGS | JUNK_TAGS
    agg = {}  # tag -> [wins, total, sum_return]
    for r in rows:
        if r["resolved_at"] < cutoff:
            continue
        for tag in _row_tags(r):
            if tag in skip:
                continue
            a = agg.setdefault(tag, [0, 0, 0.0])
            a[0] += 1 if r["won"] else 0
            a[1] += 1
            a[2] += r["return_pct"]
    cats = [
        {
            "name": tag,
            "calls": total,
            "hit_rate": wins / total,
            "return_pct": sr / total,
        }
        for tag, (wins, total, sr) in agg.items()
        if total >= CATEGORY_MIN_CALLS
    ]
    cats.sort(key=lambda c: c["return_pct"], reverse=True)
    return cats[:TOP_CATEGORIES]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_grading.py -k top_categories -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/grading.py backend/test_grading.py
git commit -m "feat(scoreboard): top_categories aggregation for Sharpest-in hook"
```

---

## Task 3: `categories` in the response model

**Files:**
- Modify: `backend/models.py:999-1019`

- [ ] **Step 1: Add the `ScoreboardCategory` model and `categories` field**

In `backend/models.py`, replace the `ScoreboardResponse` class (lines 1015-1019) and insert `ScoreboardCategory` before it, so the block reads:

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
    categories: list[ScoreboardCategory] = []
```

(`ScoreboardWindow` and `ScoreboardRecentCall` above it are unchanged.)

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd backend && python -c "import models; print(models.ScoreboardCategory.model_fields.keys()); print('categories' in models.ScoreboardResponse.model_fields)"`
Expected: prints the category field names and `True`.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat(scoreboard): add categories to ScoreboardResponse model"
```

---

## Task 4: Curated scoreboard endpoint

**Files:**
- Modify: `backend/app.py:74` (import), `:1318-1358` (`_scoreboard_rows`, `get_scoreboard`)
- Test: `backend/test_scoreboard.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/test_scoreboard.py`:

```python
def test_scoreboard_excludes_junk_tagged_calls(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_rows = [
        {"market_title": "Padres vs Phillies", "outcome": "San Diego Padres",
         "won": True, "return_pct": 0.5, "entry_price": 0.4, "event_slug": "mlb-x",
         "resolved_at": now - timedelta(days=2), "tags": '["Sports","MLB"]'},
        {"market_title": "BTC up or down", "outcome": "Up",
         "won": False, "return_pct": -1.0, "entry_price": 0.5, "event_slug": "btc",
         "resolved_at": now - timedelta(days=1), "tags": '["Crypto Prices","Up or Down"]'},
    ]
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: fake_rows)
    monkeypatch.setattr(app_module, "_scoreboard_cache", None)

    data = client.get("/api/scoreboard").json()
    # The crypto coin-flip is filtered everywhere.
    assert data["window"]["wins"] == 1
    assert data["window"]["losses"] == 0
    assert len(data["recent"]) == 1
    assert data["recent"][0]["market_title"] == "Padres vs Phillies"


def test_scoreboard_returns_top_categories(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_rows = [
        {"market_title": f"t{i}", "outcome": "X", "won": True, "return_pct": 0.2,
         "entry_price": 0.5, "event_slug": "atp", "resolved_at": now - timedelta(days=1),
         "tags": '["Sports","Tennis"]'}
        for i in range(20)
    ]
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: fake_rows)
    monkeypatch.setattr(app_module, "_scoreboard_cache", None)

    data = client.get("/api/scoreboard").json()
    assert [c["name"] for c in data["categories"]] == ["Tennis"]
    assert data["categories"][0]["calls"] == 20
```

Also update the two existing tests so their fake rows carry a `tags` key (add `"tags": '["Sports","MLB"]'` to the Padres row and `"tags": '["Sports","NBA"]'` to the Knicks row in `test_scoreboard_aggregates`; `test_scoreboard_empty` needs no change). This keeps them representative of the new joined row shape:

```python
        {"market_title": "Padres vs Phillies", "outcome": "San Diego Padres",
         "won": True, "return_pct": (1 - 0.38) / 0.38, "event_slug": "mlb-x",
         "resolved_at": now - timedelta(days=2), "tags": '["Sports","MLB"]'},
        {"market_title": "Knicks vs Spurs", "outcome": "Knicks",
         "won": False, "return_pct": -1.0, "event_slug": "nba-y",
         "resolved_at": now - timedelta(days=3), "tags": '["Sports","NBA"]'},
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd backend && python -m pytest test_scoreboard.py -v`
Expected: the two new tests FAIL (`categories` KeyError / junk row still counted); the existing two still pass.

- [ ] **Step 3: Update the import**

In `backend/app.py`, change line 74 from:

```python
from grading import summarize
```

to:

```python
from grading import summarize, exclude_junk, top_categories
```

- [ ] **Step 4: Update `_scoreboard_rows` to join tags**

Replace the query in `_scoreboard_rows` (`backend/app.py:1322-1326`) with:

```python
        cur.execute("""
            SELECT g.market_title, g.outcome, g.won, g.return_pct, g.entry_price,
                   g.event_slug, g.resolved_at, a.tags
            FROM graded_calls g
            JOIN alerts a ON a.id = g.alert_id
            ORDER BY g.resolved_at DESC
        """)
```

- [ ] **Step 5: Filter once and add categories in `get_scoreboard`**

Replace the body of `get_scoreboard` from `rows = _scoreboard_rows()` through the `result = { ... }` assignment (`backend/app.py:1339-1356`) with:

```python
    rows = _scoreboard_rows()
    curated = exclude_junk(rows)
    agg = summarize(curated, window_days=30)
    result = {
        "window_days": agg["window_days"],
        "window": agg["window"],
        "all_time": agg["all_time"],
        "recent": [
            {
                "market_title": r["market_title"],
                "outcome": r["outcome"],
                "won": r["won"],
                "return_pct": r["return_pct"],
                "event_slug": r["event_slug"],
                "resolved_at": r["resolved_at"],
            }
            for r in curated[:8]
        ],
        "categories": top_categories(curated, window_days=30),
    }
```

- [ ] **Step 6: Run the full scoreboard + grading suites**

Run: `cd backend && python -m pytest test_scoreboard.py test_grading.py -v`
Expected: all pass (4 scoreboard + the Task 1/2 grading tests + pre-existing grading tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app.py backend/test_scoreboard.py
git commit -m "feat(scoreboard): serve curated set + categories from /api/scoreboard"
```

---

## Task 5: Reframe the header component

**Files:**
- Modify: `frontend/src/components/ScoreboardHero.jsx`

No frontend unit-test framework exists; verification is `npm run lint` + `npm run build` (project convention) plus the render reasoning below.

- [ ] **Step 1: Rewrite `ScoreboardHero.jsx`**

Replace the entire contents of `frontend/src/components/ScoreboardHero.jsx` with:

```jsx
// Presentational proof hero. Leads with copy return (the unfakeable edge) over
// a curated graded set (recurring-crypto coin-flips excluded server-side).
// Hit rate and the W-L record are intentionally not shown — return is the
// honest signal; hit rate just tracks entry price. Shows a "building" state
// until >= MIN_GRADED calls exist so a tiny early sample never reads as a claim.

import EmailCapture from "./EmailCapture";

const MIN_GRADED = 10;

function asSignedPct(fraction) {
  if (!Number.isFinite(fraction)) return "—";
  const v = Math.round(fraction * 100) || 0; // `|| 0` normalizes -0 to 0
  return `${v >= 0 ? "+" : ""}${v}%`;
}

// Flat $100-per-call profit, rounded to the nearest $100 (it's an estimate).
function asDollars(amount) {
  if (!Number.isFinite(amount)) return "—";
  const rounded = Math.round(amount / 100) * 100 || 0;
  const sign = rounded >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

export default function ScoreboardHero({ scoreboard }) {
  const window = scoreboard?.window;
  const allTime = scoreboard?.all_time;
  const gradedCount = allTime ? allTime.wins + allTime.losses : 0;
  const categories = scoreboard?.categories ?? [];

  const shell = "mb-6 rounded-2xl p-6 sm:p-8";
  const shellStyle = {
    background: "var(--surface-card)",
    border: "1px solid var(--border)",
  };

  if (!window || gradedCount < MIN_GRADED) {
    return (
      <section aria-label="Track record" className={shell} style={shellStyle}>
        <h2
          className="text-lg font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          We grade every call we make.
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          PolySpotter tracks Polymarket&rsquo;s sharpest wallets and scores each
          call against the result.{" "}
          {gradedCount > 0
            ? `Building our track record — ${gradedCount} call${gradedCount === 1 ? "" : "s"} graded so far.`
            : "Our public track record is being built now."}
        </p>
        <div className="mt-4 max-w-md">
          <EmailCapture source="hero" />
        </div>
      </section>
    );
  }

  const windowCount = window.wins + window.losses;
  const ret = window.copy_return_pct;
  const returnColor = ret >= 0 ? "var(--bullish)" : "var(--bearish)";
  const profit = ret * windowCount * 100; // flat $100 on each graded call

  return (
    <section aria-label="Track record" className={shell} style={shellStyle}>
      <div
        className="text-5xl font-extrabold tracking-tight tabular-nums"
        style={{ color: returnColor }}
      >
        {asSignedPct(ret)}
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        avg return per call · last {scoreboard.window_days}d
      </div>
      <div
        className="mt-2 text-base font-semibold tabular-nums"
        style={{ color: "var(--text-secondary)" }}
      >
        ≈ {asDollars(profit)} if you&rsquo;d put $100 on every call
      </div>

      <p
        className="mt-5 max-w-xl text-sm"
        style={{ color: "var(--text-secondary)" }}
      >
        Across {windowCount.toLocaleString("en-US")} graded calls, copying
        Polymarket&rsquo;s sharpest wallets returned {asSignedPct(ret)}. We grade
        every call against the result — crypto coin-flips excluded.
      </p>

      {categories.length > 0 && (
        <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          <span style={{ color: "var(--text-muted)" }}>Sharpest in: </span>
          {categories.map((c) => c.name).join(" · ")}
        </p>
      )}

      <div className="mt-5 max-w-md">
        <p className="mb-2 text-xs" style={{ color: "var(--text-muted)" }}>
          Get the daily smart-money brief:
        </p>
        <EmailCapture source="hero" />
      </div>
    </section>
  );
}
```

(The old `Stat` and `asPct` helpers are removed — they are no longer referenced, and leaving them would trip `no-unused-vars`.)

- [ ] **Step 2: Lint**

Run: `cd frontend && npm run lint`
Expected: no errors for `ScoreboardHero.jsx` (no unused vars, no unescaped entities — apostrophes use `&rsquo;`).

- [ ] **Step 3: Build to confirm the component compiles**

Run: `cd frontend && npm run build`
Expected: build completes; no type/JSX errors from `ScoreboardHero.jsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ScoreboardHero.jsx
git commit -m "feat(frontend): lead proof hero with copy return, drop hit rate"
```

---

## Final verification

- [ ] **Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Confirm the live curated numbers (optional sanity check)**

Run (repo root, venv active): start the API (`cd backend && uvicorn app:app --port 8000`) in one shell, then `curl -s localhost:8000/api/scoreboard | python -m json.tool` in another.
Expected: `window.copy_return_pct` ≈ 0.14, `categories` lists ~3 names (e.g. Tennis/MLB/Soccer), and no crypto coin-flip titles in `recent`.

---

## Notes for the implementer

- `alerts.tags` is JSON text (`'["Sports","NBA"]'`), never a Postgres array — always parse via `_row_tags`, never index it as a list off the row.
- Exclusion is display-only: `graded_calls` keeps every call, so tuning `JUNK_TAGS` or removing the filter fully reverses the change. No migration.
- The dollar figure is deliberately an estimate (nearest $100, flat stake). Do not add compounding.
- `summarize` is unchanged — it stays tag-agnostic and operates on whatever rows it's handed (now the curated ones).
