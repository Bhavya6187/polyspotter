# Proof Loop — Plan 1: Grading Engine + Scoreboard API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grade resolved markets we featured (one deduped call each) and expose the public track record via `GET /api/scoreboard`.

**Architecture:** A standalone one-pass worker (`backend/grade_worker.py`, mirroring `seo_worker.py`) finds featured markets that have resolved, picks the highest-conviction alert as "the call," fetches the winning outcome from Gamma, and upserts a graded row into a new `graded_calls` Postgres table. All decision logic lives in pure functions in `backend/grading.py` so it is unit-testable without DB/network. A new FastAPI endpoint aggregates `graded_calls` into 30-day + all-time stats.

**Tech Stack:** Python 3.13, FastAPI, psycopg2 (RealDictCursor), Gamma API, pytest.

**Spec:** `docs/superpowers/specs/2026-06-04-homepage-proof-loop-design.md` (subsystem A).

---

## File Structure

- **Create** `backend/grading.py` — pure grading/aggregation logic (no I/O).
- **Create** `backend/grade_worker.py` — one-pass I/O loop (DB + Gamma), mirrors `seo_worker.py`.
- **Create** `backend/test_grading.py` — unit tests for `grading.py`.
- **Create** `backend/test_scoreboard.py` — endpoint test (monkeypatched data access).
- **Modify** `backend/schema.sql` — add `graded_calls` table DDL.
- **Modify** `backend/database.py` — register `_migrate_add_graded_calls` in `init_db()`.
- **Modify** `backend/models.py` — add `ScoreboardWindow`, `ScoreboardRecentCall`, `ScoreboardResponse`.
- **Modify** `backend/app.py` — add `GET /api/scoreboard`.
- **Modify** `CLAUDE.md` — document the grading worker run command.

Definitions locked from the spec:
- **Unit of record:** one row per resolved featured market = the alert with the highest `composite_score` on that market.
- **Featured:** `composite_score >= SCORE_THRESHOLD` (use `2.0`, the floor the homepage list already applies; defined as a constant so it is changeable).
- **Copy return:** `$100` flat per call; `won → (1 - entry_price) / entry_price`; `lost → -1.0`. Headline % = equal-weight **mean** of `return_pct`.
- **Resolution:** winning outcome = `outcomes[argmax(outcomePrices)]` when `max(prices) >= 0.98`; else ungraded. 50-50 (both ≈0.5) excluded.

---

## Task 1: `graded_calls` table + migration

**Files:**
- Modify: `backend/schema.sql` (append)
- Modify: `backend/database.py` (`init_db` + new function)

- [ ] **Step 1: Append the table DDL to `backend/schema.sql`**

Add at the end of the file:

```sql
-- graded_calls: one row per resolved market we featured. "The call" is the
-- highest-composite_score alert on that market; we grade it $100-flat,
-- hold-to-resolution. Powers /api/scoreboard (the public track record).
CREATE TABLE IF NOT EXISTS graded_calls (
    condition_id     TEXT PRIMARY KEY,          -- one call per market
    alert_id         INTEGER NOT NULL,          -- the chosen alert
    event_slug       TEXT,
    market_title     TEXT,
    outcome          TEXT NOT NULL,             -- copy_action.outcome
    entry_price      DOUBLE PRECISION NOT NULL, -- copy_action.entry_price
    resolved_outcome TEXT NOT NULL,             -- winning outcome from Gamma
    won              BOOLEAN NOT NULL,
    return_pct       DOUBLE PRECISION NOT NULL, -- (1-entry)/entry if won else -1.0
    composite_score  DOUBLE PRECISION NOT NULL,
    resolved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    graded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_graded_calls_resolved ON graded_calls(resolved_at DESC);
```

- [ ] **Step 2: Add the migration function in `backend/database.py`**

After `_migrate_add_events_table` (around line 226), add:

```python
def _migrate_add_graded_calls(cur):
    """Create the graded_calls table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS graded_calls (
            condition_id     TEXT PRIMARY KEY,
            alert_id         INTEGER NOT NULL,
            event_slug       TEXT,
            market_title     TEXT,
            outcome          TEXT NOT NULL,
            entry_price      DOUBLE PRECISION NOT NULL,
            resolved_outcome TEXT NOT NULL,
            won              BOOLEAN NOT NULL,
            return_pct       DOUBLE PRECISION NOT NULL,
            composite_score  DOUBLE PRECISION NOT NULL,
            resolved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            graded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_graded_calls_resolved
            ON graded_calls(resolved_at DESC)
    """)
```

- [ ] **Step 3: Call it from `init_db()`**

In `init_db()` (line ~38), add after `_migrate_add_events_table(cur)`:

```python
            _migrate_add_graded_calls(cur)
```

- [ ] **Step 4: Verify the module imports and DDL is valid SQL syntax**

Run: `cd backend && python -c "import database; print('ok')"`
Expected: prints `ok` (raises only if `DATABASE_URL` unset — that's fine; the import + function defs are what we're checking). If it raises `RuntimeError: DATABASE_URL...`, run with a dummy: `DATABASE_URL=postgres://x python -c "import database; print('ok')"` → prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/schema.sql backend/database.py
git commit -m "feat(grading): add graded_calls table + migration"
```

---

## Task 2: Pure grading helpers (`grading.py`)

**Files:**
- Create: `backend/grading.py`
- Test: `backend/test_grading.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/test_grading.py`:

```python
from grading import winning_outcome, is_won, copy_return, pick_call


def test_winning_outcome_resolved():
    assert winning_outcome(["Yes", "No"], [0.99, 0.01]) == "Yes"
    assert winning_outcome(["A", "B"], [0.005, 0.995]) == "B"


def test_winning_outcome_unresolved_returns_none():
    assert winning_outcome(["Yes", "No"], [0.6, 0.4]) is None   # not decided
    assert winning_outcome(["Yes", "No"], [0.5, 0.5]) is None   # 50-50 excluded


def test_winning_outcome_bad_shapes_return_none():
    assert winning_outcome([], []) is None
    assert winning_outcome(["Yes"], [0.99, 0.01]) is None       # length mismatch


def test_is_won_case_insensitive():
    assert is_won("San Diego Padres", "san diego padres ") is True
    assert is_won("Padres", "Phillies") is False


def test_copy_return_win_and_loss():
    assert copy_return(0.5, won=True) == 1.0          # 50c -> $1.00 = +100%
    assert round(copy_return(0.38, won=True), 4) == round((1 - 0.38) / 0.38, 4)
    assert copy_return(0.38, won=False) == -1.0


def test_pick_call_takes_highest_score():
    alerts = [
        {"id": 1, "composite_score": 5.0},
        {"id": 2, "composite_score": 14.0},
        {"id": 3, "composite_score": 9.0},
    ]
    assert pick_call(alerts)["id"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_grading.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grading'`.

- [ ] **Step 3: Implement `backend/grading.py`**

```python
"""Pure grading + scoreboard aggregation logic — no I/O, no DB, no network.

A "call" is the highest-conviction alert on a resolved market. We grade it
$100-flat, hold-to-resolution: a win returns (1-entry)/entry, a loss -1.0.
"""

from __future__ import annotations

RESOLVED_THRESHOLD = 0.98  # one outcome price >= this => market decided


def winning_outcome(outcomes, prices, threshold: float = RESOLVED_THRESHOLD):
    """Return the decided outcome name, or None if not (cleanly) resolved.

    Decided = the outcomes/prices line up and exactly one price >= threshold.
    50-50 and still-trading markets return None (left ungraded)."""
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    top = max(prices)
    if top < threshold:
        return None
    return outcomes[prices.index(top)]


def is_won(copy_outcome: str, resolved_outcome: str) -> bool:
    """Case-insensitive match between the call's outcome and the winner."""
    return (copy_outcome or "").strip().lower() == (resolved_outcome or "").strip().lower()


def copy_return(entry_price: float, won: bool) -> float:
    """$100-flat copy return. Win -> (1-entry)/entry, loss -> -1.0."""
    if not won:
        return -1.0
    return (1.0 - entry_price) / entry_price


def pick_call(alerts):
    """The single call for a market = the alert with the highest composite_score."""
    return max(alerts, key=lambda a: a["composite_score"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_grading.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/grading.py backend/test_grading.py
git commit -m "feat(grading): pure grading helpers + tests"
```

---

## Task 3: Scoreboard aggregation (`summarize`)

**Files:**
- Modify: `backend/grading.py`
- Modify: `backend/test_grading.py`

- [ ] **Step 1: Add failing tests to `backend/test_grading.py`**

Append:

```python
from datetime import datetime, timedelta, timezone
from grading import summarize


def _row(won, return_pct, days_ago):
    return {
        "won": won,
        "return_pct": return_pct,
        "resolved_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


def test_summarize_window_and_alltime():
    rows = [
        _row(True, 1.0, 1),    # in window
        _row(True, 0.5, 5),    # in window
        _row(False, -1.0, 10), # in window
        _row(True, 2.0, 45),   # outside 30d window, in all-time
    ]
    out = summarize(rows, window_days=30)
    # window: 2 wins / 1 loss
    assert out["window"]["wins"] == 2
    assert out["window"]["losses"] == 1
    assert round(out["window"]["hit_rate"], 3) == round(2 / 3, 3)
    # mean return over window rows = (1.0 + 0.5 - 1.0) / 3
    assert round(out["window"]["copy_return_pct"], 4) == round(0.5 / 3, 4)
    # all-time includes the 45-day-old win
    assert out["all_time"]["wins"] == 3
    assert out["all_time"]["losses"] == 1


def test_summarize_empty():
    out = summarize([], window_days=30)
    assert out["window"]["wins"] == 0
    assert out["window"]["losses"] == 0
    assert out["window"]["hit_rate"] == 0.0
    assert out["window"]["copy_return_pct"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_grading.py -k summarize -v`
Expected: FAIL — `ImportError: cannot import name 'summarize'`.

- [ ] **Step 3: Implement `summarize` in `backend/grading.py`**

Append to `backend/grading.py` (add `from datetime import datetime, timedelta, timezone` at top):

```python
def _stats(rows):
    wins = sum(1 for r in rows if r["won"])
    losses = sum(1 for r in rows if not r["won"])
    total = wins + losses
    hit_rate = wins / total if total else 0.0
    copy_return_pct = (sum(r["return_pct"] for r in rows) / total) if total else 0.0
    return {
        "wins": wins,
        "losses": losses,
        "hit_rate": hit_rate,
        "copy_return_pct": copy_return_pct,
    }


def summarize(rows, window_days: int = 30):
    """Aggregate graded rows into {window, all_time}. Equal-weight mean return."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    window_rows = [r for r in rows if r["resolved_at"] >= cutoff]
    return {
        "window_days": window_days,
        "window": _stats(window_rows),
        "all_time": _stats(rows),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_grading.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/grading.py backend/test_grading.py
git commit -m "feat(grading): scoreboard aggregation (summarize)"
```

---

## Task 4: Grading worker (`grade_worker.py`)

**Files:**
- Create: `backend/grade_worker.py`
- Modify: `backend/test_grading.py` (add `grade_once` test with injected deps)

The worker's logic is made testable by dependency injection: `grade_once(conn, fetch_market)` takes a DB connection and a `fetch_market(condition_id) -> dict|None` callable, so tests pass fakes.

- [ ] **Step 1: Write the failing test for `grade_once`**

Append to `backend/test_grading.py`:

```python
from grade_worker import grade_once


class _FakeCursor:
    def __init__(self, candidate_rows, alert_rows_by_cid):
        self._candidate_rows = candidate_rows
        self._alert_rows_by_cid = alert_rows_by_cid
        self.upserts = []
        self._last = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT DISTINCT a.condition_id"):
            self._last = self._candidate_rows
        elif s.startswith("SELECT id, composite_score"):
            self._last = self._alert_rows_by_cid[params[0]]
        elif s.startswith("INSERT INTO graded_calls"):
            self.upserts.append(params)
            self._last = []

    def fetchall(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def test_grade_once_grades_a_won_call():
    cid = "0xabc"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 10, "composite_score": 14.0, "event_slug": "mlb-x",
             "market_title": "Padres vs Phillies",
             "llm_copy_action": '{"outcome": "San Diego Padres", "entry_price": 0.38}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["San Diego Padres", "Philadelphia Phillies"],
                "prices": [0.99, 0.01]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    params = cur.upserts[0]
    # params order: cid, alert_id, event_slug, title, outcome, entry, resolved, won, ret, score
    assert params[0] == cid
    assert params[1] == 10
    assert params[6] == "San Diego Padres"  # resolved_outcome
    assert params[7] is True                # won
    assert round(params[8], 4) == round((1 - 0.38) / 0.38, 4)


def test_grade_once_skips_unresolved():
    cid = "0xopen"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 5.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": '{"outcome": "Yes", "entry_price": 0.5}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["Yes", "No"], "prices": [0.6, 0.4]}  # not decided

    graded = grade_once(conn, fake_fetch)
    assert graded == 0
    assert cur.upserts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_grading.py -k grade_once -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grade_worker'`.

- [ ] **Step 3: Implement `backend/grade_worker.py`**

```python
"""Grading worker — one pass, then exit (wrap in a shell sleep loop, like
seo_worker.py). Finds featured markets that have resolved but aren't yet
graded, picks the highest-conviction alert as "the call", determines the
winning outcome from Gamma, and upserts a row into graded_calls.

    while true; do python backend/grade_worker.py; sleep 1800; done

Autocommit connection: no transaction is held open across a Gamma HTTP call.
"""

from __future__ import annotations

import json
import sys
from contextlib import closing
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from database import get_conn  # noqa: E402
from grading import winning_outcome, is_won, copy_return, pick_call  # noqa: E402

GAMMA_API = "https://gamma-api.polymarket.com"
SCORE_THRESHOLD = 2.0   # "featured" floor — matches the homepage list
BATCH_LIMIT = 50        # markets to consider per pass


def fetch_market(condition_id: str):
    """Return {outcomes: list[str], prices: list[float]} for a market, or None.

    Retries with closed=true because Gamma hides closed markets by default."""
    for params in ({"condition_ids": condition_id},
                   {"condition_ids": condition_id, "closed": "true"}):
        try:
            resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
        except Exception:
            continue
        if not markets:
            continue
        m = markets[0]
        raw_out = m.get("outcomes", "[]")
        raw_prc = m.get("outcomePrices", "[]")
        outcomes = json.loads(raw_out) if isinstance(raw_out, str) else raw_out
        try:
            prices = [float(p) for p in (json.loads(raw_prc) if isinstance(raw_prc, str) else raw_prc)]
        except (ValueError, TypeError):
            prices = []
        return {"outcomes": outcomes or [], "prices": prices}
    return None


def grade_once(conn, fetch=fetch_market) -> int:
    """Grade up to BATCH_LIMIT ungraded featured markets. Returns count graded."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT a.condition_id
            FROM alerts a
            WHERE a.condition_id IS NOT NULL
              AND a.composite_score >= %s
              AND a.llm_copy_action IS NOT NULL
              AND a.llm_copy_action <> '{}'
              AND NOT EXISTS (
                  SELECT 1 FROM graded_calls g WHERE g.condition_id = a.condition_id
              )
            ORDER BY a.condition_id
            LIMIT %s
        """, (SCORE_THRESHOLD, BATCH_LIMIT))
        candidate_cids = [r["condition_id"] for r in cur.fetchall()]

    graded = 0
    for cid in candidate_cids:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, composite_score, event_slug, market_title, llm_copy_action
                FROM alerts
                WHERE condition_id = %s AND composite_score >= %s
                  AND llm_copy_action IS NOT NULL AND llm_copy_action <> '{}'
            """, (cid, SCORE_THRESHOLD))
            alerts = cur.fetchall()
        if not alerts:
            continue

        market = fetch(cid)
        if not market:
            continue
        resolved = winning_outcome(market["outcomes"], market["prices"])
        if resolved is None:
            continue  # not cleanly decided — leave ungraded, retry next pass

        call = pick_call(alerts)
        try:
            action = json.loads(call["llm_copy_action"])
        except (json.JSONDecodeError, TypeError):
            continue
        outcome = action.get("outcome")
        entry = action.get("entry_price")
        if not outcome or entry in (None, 0):
            continue

        won = is_won(outcome, resolved)
        ret = copy_return(float(entry), won)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO graded_calls
                    (condition_id, alert_id, event_slug, market_title, outcome,
                     entry_price, resolved_outcome, won, return_pct, composite_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (condition_id) DO NOTHING
            """, (
                cid, call["id"], call.get("event_slug"), call.get("market_title"),
                outcome, float(entry), resolved, won, ret, call["composite_score"],
            ))
        graded += 1
        print(f"[grade_worker] {call.get('market_title')}: "
              f"{'WON' if won else 'LOST'} {ret:+.0%}", flush=True)
    return graded


def main() -> int:
    print("[grade_worker] start", flush=True)
    conn = get_conn()
    conn.autocommit = True
    try:
        with closing(conn):
            n = grade_once(conn)
    except Exception as e:
        print(f"[grade_worker] FAILED: {e}", flush=True)
        return 0
    print(f"[grade_worker] done: graded={n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_grading.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/grade_worker.py backend/test_grading.py
git commit -m "feat(grading): grade_worker one-pass grading loop"
```

---

## Task 5: `GET /api/scoreboard` endpoint

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`
- Create: `backend/test_scoreboard.py`

- [ ] **Step 1: Add response models to `backend/models.py`**

Append (the file already uses Pydantic `BaseModel` — match its import style at the top):

```python
class ScoreboardWindow(BaseModel):
    wins: int
    losses: int
    hit_rate: float
    copy_return_pct: float


class ScoreboardRecentCall(BaseModel):
    market_title: str | None = None
    outcome: str
    won: bool
    return_pct: float
    event_slug: str | None = None
    resolved_at: datetime


class ScoreboardResponse(BaseModel):
    window_days: int
    window: ScoreboardWindow
    all_time: ScoreboardWindow
    recent: list[ScoreboardRecentCall]
```

Note: `datetime` is already imported in `models.py` (used by existing models like `resolved_at`). If not, add `from datetime import datetime`.

- [ ] **Step 2: Write the failing endpoint test**

Create `backend/test_scoreboard.py`:

```python
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


def test_scoreboard_aggregates(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_rows = [
        {"market_title": "Padres vs Phillies", "outcome": "San Diego Padres",
         "won": True, "return_pct": (1 - 0.38) / 0.38, "event_slug": "mlb-x",
         "resolved_at": now - timedelta(days=2)},
        {"market_title": "Knicks vs Spurs", "outcome": "Knicks",
         "won": False, "return_pct": -1.0, "event_slug": "nba-y",
         "resolved_at": now - timedelta(days=3)},
    ]
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: fake_rows)

    resp = client.get("/api/scoreboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"]["wins"] == 1
    assert data["window"]["losses"] == 1
    assert data["window"]["hit_rate"] == 0.5
    assert len(data["recent"]) == 2
    assert data["recent"][0]["market_title"] == "Padres vs Phillies"


def test_scoreboard_empty(monkeypatch):
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: [])
    resp = client.get("/api/scoreboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"]["wins"] == 0
    assert data["all_time"]["wins"] == 0
    assert data["recent"] == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest test_scoreboard.py -v`
Expected: FAIL — 404 (route missing) or AttributeError on `_scoreboard_rows`.

- [ ] **Step 4: Implement the endpoint in `backend/app.py`**

Add near the other read endpoints (e.g. after `get_resolving_soon`). Ensure imports at top of `app.py`: `from grading import summarize` and `from models import ScoreboardResponse` (models are already imported there — extend the existing import list). The data-access helper is a module-level function so tests can monkeypatch it:

```python
_SCOREBOARD_TTL = 120  # seconds
_scoreboard_cache: tuple[float, dict] | None = None


def _scoreboard_rows() -> list[dict]:
    """Raw graded_calls rows (newest first). Separated out so tests can fake it."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT market_title, outcome, won, return_pct, event_slug, resolved_at
            FROM graded_calls
            ORDER BY resolved_at DESC
        """)
        return list(cur.fetchall())


@app.get("/api/scoreboard", response_model=ScoreboardResponse)
def get_scoreboard():
    """Public track record: 30-day + all-time W/L, hit rate, copy return,
    plus the most recent graded calls (the 'receipts'). Cached 120s."""
    global _scoreboard_cache
    now = _time.time()
    if _scoreboard_cache and _scoreboard_cache[0] > now:
        return _scoreboard_cache[1]

    rows = _scoreboard_rows()
    agg = summarize(rows, window_days=30)
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
            for r in rows[:8]
        ],
    }
    _scoreboard_cache = (now + _SCOREBOARD_TTL, result)
    return result
```

(If `db`, `_time`, or the models import differ in name, match the existing symbols in `app.py` — `db()` is used at line ~1286, `_time` at line ~1196.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest test_scoreboard.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all green (existing tests + new grading/scoreboard tests).

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/app.py backend/test_scoreboard.py
git commit -m "feat(grading): GET /api/scoreboard endpoint"
```

---

## Task 6: Document the worker run command

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a run snippet under the "Running" section of `CLAUDE.md`**

After the Articlebot block, add:

```markdown
Grading worker (grades resolved featured markets → `graded_calls` → `/api/scoreboard`):
```bash
source venv/bin/activate
python backend/grade_worker.py            # one pass, then exits
# Run on a loop (recommended every 30 min):
while true; do python backend/grade_worker.py; sleep 1800; done
```
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document grade_worker run command"
```

---

## Self-Review Notes

- **Spec coverage (subsystem A):** `graded_calls` table (Task 1) ✓; one-call-per-market dedup via `pick_call` + PRIMARY KEY on `condition_id` (Tasks 2, 4) ✓; $100-flat equal-weight return (Task 2) ✓; 30d + all-time windows (Task 3) ✓; settlement detection + winning outcome reusing the codebase's `>=0.98` rule (Task 2/4) ✓; 50-50 excluded (Task 2 test) ✓; `/api/scoreboard` with `recent` receipts (Task 5) ✓; cold-start empty shape returns zeros (Task 5 test) ✓ — the *UI* cold-start "Building our track record" copy belongs to Plan 2 (homepage).
- **No placeholders:** every code step is complete and runnable.
- **Type consistency:** `winning_outcome`/`is_won`/`copy_return`/`pick_call`/`summarize` signatures match across `grading.py`, `grade_worker.py`, tests, and the endpoint. `graded_calls` columns match between `schema.sql`, the migration, the worker INSERT, and the endpoint SELECT.

## Deferred to later plans

- **Plan 2 (Homepage):** `ScoreboardHero`, `RecentCalls`, reorder, ticker removal, cold-start UI copy, `fetchScoreboard()` client.
- **Plan 3 (Email):** `subscribers` table, `POST /api/subscribe`, `EmailCapture`, `digest_worker.py`, Resend integration.
