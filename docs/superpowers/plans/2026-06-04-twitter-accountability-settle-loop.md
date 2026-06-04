# Twitter Accountability — Settle Loop (Component A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on the existing-but-disabled result loop so PolySpotter posts a settle tweet ("That Felix call? ✅ Cashed +$140k") with a scorecard image when a flagged market resolves, curated win-weighted with an honesty floor — giving viewers a verifiable track record and a reason to follow.

**Architecture:** Reuse `result_pipeline.py`'s correct resolution/P&L math. Add (1) a `result_tweets` Postgres table + thin store module for dedup/recording, (2) pure selection logic (curated, win-bias 0.8, honesty floor for big losses), (3) a `result_scorecard` chart renderer in `charts.py`, (4) a link-free result prompt, and (5) `publish_result.py` mirroring `publish_tweet.py`. The loop script chains compose → Claude edit → publish, exactly like `run_twitter_pipeline_loop.sh`.

**Tech Stack:** Python 3.13, psycopg2 (Postgres via `DATABASE_URL`), matplotlib (`charts.py`), tweepy (`tweet_utils.post_tweet`), Azure OpenAI (`OpenAI` responses API), pytest.

**Spec:** `docs/superpowers/specs/2026-06-04-twitter-accountability-layer-design.md` (Phase 1 = Component A only).

---

## File Structure

- **Create** `storybot/result_store.py` — thin Postgres helpers for the `result_tweets` table: `record_result`, `result_exists`, `todays_posted_outcomes`. One responsibility: persistence + dedup for posted results.
- **Modify** `backend/schema.sql` — add the `result_tweets` table.
- **Modify** `storybot/result_pipeline.py` — add pure selection/classification helpers; drop the URL from the prompt; build scorecard data; have `main()` select → compose → render → write a draft + artifact (no posting here).
- **Modify** `storybot/charts.py` — add `ResultScorecardData`, `_draw_result_scorecard`, `render_result_scorecard`; add `"result_scorecard"` to `CHART_TYPES`.
- **Create** `storybot/publish_result.py` — read draft + artifact, re-validate, post text + scorecard PNG, record `result_tweets` row. Mirrors `publish_tweet.py`.
- **Modify** `storybot/run_result_pipeline_loop.sh` — chain compose → `claude -p` edit → `publish_result.py`.
- **Create** `test/test_result_store.py`, `test/test_result_selection.py`, `test/test_result_scorecard.py`, `test/test_publish_result.py`.

All `RESULT_*` tunables live as module constants in `result_pipeline.py`: `RESULT_DAILY_CAP=2`, `RESULT_WIN_BIAS=0.8`, `RESULT_LOSS_NOTABLE_USD=20000.0`, `RESULT_WASH_BAND=0.01`.

---

## Task 1: `result_tweets` table + store module

**Files:**
- Modify: `backend/schema.sql` (append after the `tweeted_alerts` block, ~line 201)
- Create: `storybot/result_store.py`
- Test: `test/test_result_store.py`

- [ ] **Step 1: Add the table to `backend/schema.sql`**

Append after the `idx_tweeted_alerts_wallet_market` index (after line 201):

```sql
-- result_tweets: one row per flag-tweet we've settled with a result follow-up.
-- Source of truth for result dedup and (deferred) the scoreboard. One row per
-- original flag tweet (UNIQUE original_tweet_id). posted_at is NULL until the
-- result is actually published by publish_result.py.
CREATE TABLE IF NOT EXISTS result_tweets (
    id                 BIGSERIAL PRIMARY KEY,
    original_tweet_id  TEXT NOT NULL UNIQUE,
    result_tweet_id    TEXT,
    alert_ids          BIGINT[] NOT NULL DEFAULT '{}',
    condition_ids      TEXT[]   NOT NULL DEFAULT '{}',
    n_won              INTEGER  NOT NULL DEFAULT 0,
    n_lost             INTEGER  NOT NULL DEFAULT 0,
    net_pl_usd         NUMERIC  NOT NULL DEFAULT 0,
    total_invested_usd NUMERIC  NOT NULL DEFAULT 0,
    outcome            TEXT     NOT NULL DEFAULT 'wash',
    event_label        TEXT,
    posted_at          TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_result_tweets_posted_at
    ON result_tweets (posted_at DESC);
```

- [ ] **Step 2: Write the failing test for `todays_posted_outcomes` parsing**

Create `test/test_result_store.py`:

```python
from datetime import datetime, timezone

import storybot.result_store as rs


def test_todays_posted_outcomes_filters_to_et_day_and_maps_wins(monkeypatch):
    # _run returns rows of (posted_at, outcome). The function should keep only
    # rows on the same ET calendar day as `now` and map outcome -> is_win.
    now = datetime(2026, 6, 4, 18, 0, tzinfo=timezone.utc)  # 2pm ET
    rows = [
        {"posted_at": datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc),
         "outcome": "cashed"},   # same ET day -> win
        {"posted_at": datetime(2026, 6, 4, 16, 0, tzinfo=timezone.utc),
         "outcome": "burned"},   # same ET day -> loss
        {"posted_at": datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc),
         "outcome": "cashed"},   # previous ET day -> excluded
    ]
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: rows)
    assert rs.todays_posted_outcomes(now) == [True, False]


def test_record_result_passes_unique_conflict_sql(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    rs.record_result(
        original_tweet_id="111", result_tweet_id="222",
        alert_ids=[1, 2], condition_ids=["0xabc"],
        n_won=3, n_lost=1, net_pl_usd=31000.0,
        total_invested_usd=20000.0, outcome="cashed",
        event_label="Padres-Phillies Over 7.5",
    )
    assert "ON CONFLICT (original_tweet_id)" in captured["query"]
    assert captured["params"][0] == "111"
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `source venv/bin/activate && pytest test/test_result_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storybot.result_store'`

- [ ] **Step 4: Implement `storybot/result_store.py`**

```python
"""Persistence + dedup for posted result tweets (the result_tweets table).

Thin layer over Postgres so result_pipeline.py / publish_result.py can record
settled calls and ask "did we already settle this flag tweet?" without
duplicating SQL. Every public function goes through `_run` so tests can
monkeypatch a single seam.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "")
QUERY_TIMEOUT_SECONDS = 10
_AUDIENCE_TZ = ZoneInfo("America/New_York")


def _run(query: str, params: tuple, fetch: bool = False):
    """Execute one statement. Returns list[dict] when fetch, else None."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        cur.close()
        return [dict(r) for r in rows] if fetch else None
    finally:
        conn.close()


def result_exists(original_tweet_id: str) -> bool:
    """True if we've already recorded a result for this flag tweet."""
    rows = _run(
        "SELECT 1 FROM result_tweets WHERE original_tweet_id = %s LIMIT 1",
        (str(original_tweet_id),), fetch=True,
    )
    return bool(rows)


def record_result(*, original_tweet_id: str, result_tweet_id: str | None,
                  alert_ids: list[int], condition_ids: list[str],
                  n_won: int, n_lost: int, net_pl_usd: float,
                  total_invested_usd: float, outcome: str,
                  event_label: str | None) -> None:
    """Insert (or no-op on duplicate) a settled-result row."""
    _run(
        """
        INSERT INTO result_tweets
            (original_tweet_id, result_tweet_id, alert_ids, condition_ids,
             n_won, n_lost, net_pl_usd, total_invested_usd, outcome,
             event_label, posted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (original_tweet_id) DO NOTHING
        """,
        (str(original_tweet_id),
         str(result_tweet_id) if result_tweet_id else None,
         [int(i) for i in alert_ids],
         [str(c) for c in condition_ids],
         int(n_won), int(n_lost), float(net_pl_usd),
         float(total_invested_usd), str(outcome), event_label),
    )


def todays_posted_outcomes(now: datetime) -> list[bool]:
    """is_win flags for results posted on the same ET calendar day as `now`.

    'cashed' -> True (win); anything else -> False. Used to keep the running
    win share near RESULT_WIN_BIAS and to count today's posts against the cap.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(_AUDIENCE_TZ).date()
    rows = _run(
        "SELECT posted_at, outcome FROM result_tweets "
        "WHERE posted_at IS NOT NULL "
        "AND posted_at >= NOW() - INTERVAL '2 days'",
        (), fetch=True,
    ) or []
    out: list[bool] = []
    for r in rows:
        pa = r.get("posted_at")
        if pa is None:
            continue
        if pa.tzinfo is None:
            pa = pa.replace(tzinfo=timezone.utc)
        if pa.astimezone(_AUDIENCE_TZ).date() == today:
            out.append((r.get("outcome") or "") == "cashed")
    return out
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `pytest test/test_result_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/schema.sql storybot/result_store.py test/test_result_store.py
git commit -m "feat(results): add result_tweets table + result_store helpers"
```

---

## Task 2: Outcome classification + curated selection (pure logic)

**Files:**
- Modify: `storybot/result_pipeline.py` (add constants + pure helpers near the top, after the existing `RESULT_MIN_AGE_MINUTES` constant ~line 65)
- Test: `test/test_result_selection.py`

- [ ] **Step 1: Write the failing tests**

Create `test/test_result_selection.py`:

```python
import storybot.result_pipeline as rp


def test_classify_outcome_cashed_burned_wash():
    assert rp.classify_outcome({"net_pl_usd": 5000.0,
                                "total_invested_usd": 10000.0}) == "cashed"
    assert rp.classify_outcome({"net_pl_usd": -8000.0,
                                "total_invested_usd": 10000.0}) == "burned"
    # within 1% of invested -> wash
    assert rp.classify_outcome({"net_pl_usd": 50.0,
                                "total_invested_usd": 10000.0}) == "wash"


def test_notable_loss_always_selected_even_with_wins():
    # Honesty floor: a $40k loss is posted even alongside a winning call.
    cands = [
        {"id": "w", "is_win": True, "net_pl_usd": 12000.0, "notability": 12000.0},
        {"id": "L", "is_win": False, "net_pl_usd": -40000.0, "notability": 40000.0},
    ]
    picked = {c["id"] for c in rp.select_results(cands, posted_today=[])}
    assert "L" in picked  # big loss not hidden
    assert len(picked) == 2  # both fit under cap=2


def test_small_loss_suppressed_when_a_win_is_available():
    cands = [
        {"id": "w", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
        {"id": "s", "is_win": False, "net_pl_usd": -3000.0, "notability": 3000.0},
    ]
    picked = [c["id"] for c in rp.select_results(
        cands, posted_today=[], daily_cap=1)]
    assert picked == ["w"]  # win preferred; small loss below honesty floor


def test_daily_cap_and_remaining_slots_respected():
    cands = [
        {"id": "a", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
        {"id": "b", "is_win": True, "net_pl_usd": 8000.0, "notability": 8000.0},
    ]
    # one already posted today -> only one slot left
    picked = rp.select_results(cands, posted_today=[True], daily_cap=2)
    assert len(picked) == 1
    assert picked[0]["id"] == "a"  # higher notability first


def test_win_bias_forces_win_when_share_below_target():
    # No wins posted yet, share would start below target -> prefer the win
    # over an equally-notable big loss for the first slot.
    cands = [
        {"id": "L", "is_win": False, "net_pl_usd": -50000.0, "notability": 50000.0},
        {"id": "w", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
    ]
    picked = [c["id"] for c in rp.select_results(
        cands, posted_today=[], daily_cap=1, win_bias=0.8)]
    assert picked == ["w"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest test/test_result_selection.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'classify_outcome'`

- [ ] **Step 3: Implement the helpers in `result_pipeline.py`**

Add after `RESULT_MIN_AGE_MINUTES = 60` (around line 65):

```python
# Curated result selection. We do NOT post every resolved call — we post a
# small, win-weighted set per day, but never hide a big loss (honesty floor),
# because a visibly all-wins record reads as cherry-picked and destroys the
# trust the whole accountability layer exists to build.
RESULT_DAILY_CAP = 2
RESULT_WIN_BIAS = 0.8            # target fraction of posted results that are wins
RESULT_LOSS_NOTABLE_USD = 20000.0  # a loss this big is ALWAYS eligible
RESULT_WASH_BAND = 0.01         # |net_pl| within 1% of invested -> "wash"


def classify_outcome(aggregate: dict) -> str:
    """'cashed' | 'burned' | 'wash' from net P&L vs invested."""
    net = float(aggregate.get("net_pl_usd") or 0.0)
    invested = float(aggregate.get("total_invested_usd") or 0.0)
    if invested > 0 and abs(net) <= RESULT_WASH_BAND * invested:
        return "wash"
    return "cashed" if net > 0 else "burned"


def select_results(candidates: list[dict], *, posted_today: list[bool],
                   daily_cap: int = RESULT_DAILY_CAP,
                   win_bias: float = RESULT_WIN_BIAS,
                   loss_notable_usd: float = RESULT_LOSS_NOTABLE_USD) -> list[dict]:
    """Pick which resolved calls to post today.

    candidates: dicts with keys is_win(bool), net_pl_usd(float),
    notability(float >= 0), plus any caller payload (e.g. 'id').
    posted_today: is_win flags already posted this ET day (cap + win-share).

    Rules: wins are always eligible; losses are eligible only if notable
    (>= loss_notable_usd). When a slot is free, force a win if the running
    win share is below win_bias; otherwise take whichever remaining item is
    the bigger story (higher notability). Deterministic.
    """
    slots = max(0, int(daily_cap) - len(posted_today))
    if slots <= 0:
        return []
    wins = sorted([c for c in candidates if c.get("is_win")],
                  key=lambda c: c.get("notability", 0.0), reverse=True)
    losses = sorted(
        [c for c in candidates
         if not c.get("is_win")
         and abs(float(c.get("net_pl_usd") or 0.0)) >= loss_notable_usd],
        key=lambda c: c.get("notability", 0.0), reverse=True)

    selected: list[dict] = []
    posted = list(posted_today)
    wi, li = 0, 0
    while len(selected) < slots and (wi < len(wins) or li < len(losses)):
        nxt_win = wins[wi] if wi < len(wins) else None
        nxt_loss = losses[li] if li < len(losses) else None
        total = len(posted)
        share = (sum(1 for w in posted if w) / total) if total else 0.0
        if nxt_loss is None:
            pick_win = True
        elif nxt_win is None:
            pick_win = False
        elif share < win_bias:
            pick_win = True  # below target -> must add a win
        else:
            pick_win = nxt_win.get("notability", 0.0) >= nxt_loss.get("notability", 0.0)
        if pick_win:
            selected.append(nxt_win); posted.append(True); wi += 1
        else:
            selected.append(nxt_loss); posted.append(False); li += 1
    return selected
```

Note: `posted_today=[]` gives `share=0.0 < win_bias`, so the first pick prefers a win — matching `test_win_bias_forces_win_when_share_below_target`.

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest test/test_result_selection.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add storybot/result_pipeline.py test/test_result_selection.py
git commit -m "feat(results): curated win-weighted selection with honesty floor"
```

---

## Task 3: `result_scorecard` chart renderer

**Files:**
- Modify: `storybot/charts.py` (add to `CHART_TYPES` ~line 33; add renderer after `render_wallet_record_card` ~line 146)
- Test: `test/test_result_scorecard.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_result_scorecard.py`:

```python
import storybot.charts as charts


def _data(verdict, net):
    return {
        "verdict": verdict,
        "net_pl_usd": net,
        "record_str": "3-1",
        "event_label": "Padres-Phillies Over 7.5 runs",
        "outcome_side": "Over 7.5 runs",
        "flagged_days_ago": 2,
    }


def test_result_scorecard_renders_png_bytes_for_each_verdict():
    for verdict, net in [("CASHED", 31000.0), ("BURNED", -28000.0),
                         ("WASH", 0.0)]:
        png = charts.render_result_scorecard(_data(verdict, net))
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_result_scorecard_is_registered_chart_type():
    assert "result_scorecard" in charts.CHART_TYPES
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest test/test_result_scorecard.py -v`
Expected: FAIL with `AttributeError: module 'storybot.charts' has no attribute 'render_result_scorecard'`

- [ ] **Step 3: Implement in `charts.py`**

3a. Add `"result_scorecard"` to the `CHART_TYPES` tuple (line 33). Open the file and append the string to the existing tuple, e.g.:

```python
CHART_TYPES = (
    "wallet_record_card",
    "fresh_wallet_card",
    "price_sparkline",
    "volume_bar",
    "cluster_card",
    "result_scorecard",
)
```

(Match the existing entries already present in the tuple — add only the new line.)

3b. Add the renderer immediately after `render_wallet_record_card` (after line 146):

```python
# ----------------------- result_scorecard -----------------------

class ResultScorecardData(TypedDict):
    verdict: str             # "CASHED" | "BURNED" | "MIXED" | "WASH"
    net_pl_usd: float        # signed
    record_str: str          # trade W-L, e.g. "3-1"
    event_label: str         # "Padres-Phillies Over 7.5 runs"
    outcome_side: str        # the side the cluster was on
    flagged_days_ago: int


def _draw_result_scorecard(ax, data: ResultScorecardData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    verdict = (data.get("verdict") or "WASH").upper()
    net = float(data.get("net_pl_usd") or 0.0)
    if verdict == "CASHED":
        color, mark = ACCENT, "✅"   # green check
    elif verdict == "BURNED":
        color, mark = LOSS, "❌"     # red cross
    else:
        color, mark = MUTED, "➖"    # neutral

    sign = "+" if net > 0 else ("-" if net < 0 else "")
    net_str = f"{sign}{_format_usd(abs(net))}" if verdict != "WASH" else "BROKE EVEN"

    ax.text(0.5, 0.74, f"{mark}  {verdict}", color=color, fontsize=58,
            ha="center", va="center", weight="bold")
    ax.text(0.5, 0.50, net_str, color=color, fontsize=72,
            ha="center", va="center", weight="bold")
    ax.text(0.5, 0.31, data.get("event_label") or "", color=FG, fontsize=26,
            ha="center", va="center")
    side = data.get("outcome_side") or ""
    record = data.get("record_str") or ""
    sub = f"Flagged side: {side}   ·   Trades: {record}" if side else f"Trades: {record}"
    ax.text(0.5, 0.20, sub, color=MUTED, fontsize=20, ha="center", va="center")
    days = int(data.get("flagged_days_ago") or 0)
    when = "today" if days <= 0 else (f"{days} day ago" if days == 1
                                      else f"{days} days ago")
    ax.text(0.5, 0.08, f"PolySpotter flagged this {when}", color=MUTED,
            fontsize=18, ha="center", va="center")


def render_result_scorecard(data: ResultScorecardData) -> bytes:
    fig, ax = _new_figure()
    _draw_result_scorecard(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest test/test_result_scorecard.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Eyeball the image once (manual, optional but recommended)**

Run:
```bash
source venv/bin/activate && python -c "
import storybot.charts as c
open('/tmp/scorecard.png','wb').write(c.render_result_scorecard({
 'verdict':'CASHED','net_pl_usd':31000.0,'record_str':'3-1',
 'event_label':'Padres-Phillies Over 7.5 runs','outcome_side':'Over 7.5 runs',
 'flagged_days_ago':2}))
print('wrote /tmp/scorecard.png')"
```
Open `/tmp/scorecard.png` and confirm the layout reads cleanly.

- [ ] **Step 6: Commit**

```bash
git add storybot/charts.py test/test_result_scorecard.py
git commit -m "feat(results): result_scorecard chart renderer"
```

---

## Task 4: Link-free result prompt + scorecard-data builder

**Files:**
- Modify: `storybot/result_pipeline.py` (`SYSTEM_PROMPT_RESULT`, `compose_result_tweet`, add `build_scorecard_data`, add `event_label_for`)
- Test: `test/test_result_selection.py` (extend)

- [ ] **Step 1: Write the failing test for `build_scorecard_data`**

Append to `test/test_result_selection.py`:

```python
def test_build_scorecard_data_maps_aggregate_to_card():
    aggregate = {"n_won": 3, "n_lost": 1, "net_pl_usd": 31000.0,
                 "total_invested_usd": 20000.0}
    card = rp.build_scorecard_data(
        aggregate, event_label="Padres-Phillies Over 7.5 runs",
        outcome_side="Over 7.5 runs", flagged_days_ago=2)
    assert card["verdict"] == "CASHED"
    assert card["record_str"] == "3-1"
    assert card["net_pl_usd"] == 31000.0
    assert card["event_label"] == "Padres-Phillies Over 7.5 runs"
    assert card["flagged_days_ago"] == 2
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest test/test_result_selection.py::test_build_scorecard_data_maps_aggregate_to_card -v`
Expected: FAIL with `AttributeError: ... 'build_scorecard_data'`

- [ ] **Step 3: Implement `build_scorecard_data` in `result_pipeline.py`**

Add near `classify_outcome`:

```python
def build_scorecard_data(aggregate: dict, *, event_label: str,
                         outcome_side: str, flagged_days_ago: int) -> dict:
    """Map an aggregate_result() dict to ResultScorecardData for the renderer."""
    verdict = classify_outcome(aggregate).upper()  # CASHED | BURNED | WASH
    return {
        "verdict": verdict,
        "net_pl_usd": float(aggregate.get("net_pl_usd") or 0.0),
        "record_str": f"{int(aggregate.get('n_won') or 0)}-"
                      f"{int(aggregate.get('n_lost') or 0)}",
        "event_label": event_label,
        "outcome_side": outcome_side,
        "flagged_days_ago": int(flagged_days_ago),
    }
```

- [ ] **Step 4: Drop the URL from the result prompt**

In `SYSTEM_PROMPT_RESULT`, remove the URL mechanics so result tweets ship link-free (the scorecard image is the payload). Make these edits:

- Delete the bullet line: `- alert_url: a polyspotter.com link to include verbatim at the end.`
- Replace the structure step `3. End with the polyspotter URL on its own line if it fits, else inline.` with:
  `3. No link. The scorecard image carries the brand — spend every character on the result.`
- Change `- Keep total under 240 characters (URL counts as 23).` to
  `- Keep total under 270 characters. No URL — it would be stripped.`
- Add to the Rules list: `- Do NOT include any URL; links are stripped before posting.`

- [ ] **Step 5: Drop `alert_url` from `compose_result_tweet`**

In `compose_result_tweet`, remove the `alert_url` parameter and the `"alert_url": alert_url` payload key. New signature and payload:

```python
def compose_result_tweet(llm_client, original_tweet: str, result: dict) -> str:
    """One LLM call to produce the link-free follow-up tweet text."""
    payload = {
        "original_tweet": original_tweet,
        "result": {
            "n_won": result["n_won"],
            "n_lost": result["n_lost"],
            "total_invested_usd": round(result["total_invested_usd"], 2),
            "total_payout_usd": round(result["total_payout_usd"], 2),
            "net_pl_usd": round(result["net_pl_usd"], 2),
            "by_market": [
                {"side_bet": v["side_bet"],
                 "winning_outcome": v["winning_outcome"],
                 "usd_invested": round(v["usd_invested"], 2),
                 "pl": round(v["pl"], 2),
                 "won": v["won"]}
                for v in result["by_market"].values()
            ],
        },
    }
    response = llm_client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT_RESULT,
        input=(
            f"{json.dumps(payload, default=str, indent=2)}\n\n"
            f"Reply with a JSON object matching the schema in the instructions."
        ),
        max_output_tokens=2000,
        reasoning={"effort": "low"},
        text={"format": {"type": "json_object"}},
    )
    content = response.output_text or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return ""
    return (parsed.get("tweet") or "").strip()
```

- [ ] **Step 6: Run the tests to confirm they pass**

Run: `pytest test/test_result_selection.py -v`
Expected: PASS (6 passed)

- [ ] **Step 7: Commit**

```bash
git add storybot/result_pipeline.py test/test_result_selection.py
git commit -m "feat(results): link-free result prompt + scorecard data builder"
```

---

## Task 5: Wire `result_pipeline.main()` to select, render, and draft

**Files:**
- Modify: `storybot/result_pipeline.py` (`process_tweet`, `main`, add a draft writer + scorecard png writer; dedup via `result_store.result_exists`)
- Test: covered by Task 2/4 pure tests + a manual DRY_RUN smoke run

This task changes orchestration only (no new pure logic), so it is verified by a DRY_RUN smoke run rather than a new unit test.

- [ ] **Step 1: Import the store and add draft/png writers**

At the top imports of `result_pipeline.py`, add:

```python
import storybot.result_store as result_store
import storybot.charts as charts
```

Add a drafts dir constant near `_RUN_OUTPUT_DIR`:

```python
_RESULT_DRAFTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "result_drafts")
```

Add writer helpers near `_save_artifact`:

```python
def _write_result_draft(tweet_id: str, text: str) -> str:
    os.makedirs(_RESULT_DRAFTS_DIR, exist_ok=True)
    path = os.path.join(_RESULT_DRAFTS_DIR, f"{tweet_id}.txt")
    with open(path, "w") as f:
        f.write(text)
    return path


def _write_scorecard_png(tweet_id: str, png: bytes) -> str:
    os.makedirs(_RUN_OUTPUT_DIR, exist_ok=True)
    path = os.path.join(_RUN_OUTPUT_DIR, f"result_{tweet_id}.png")
    with open(path, "wb") as f:
        f.write(png)
    return path
```

- [ ] **Step 2: Add dedup + notability to `process_tweet`**

In `process_tweet`, replace the artifact-existence dedup check at the top:

```python
    tweet_id = str(tweet["tweet_id"])
    if result_store.result_exists(tweet_id):
        return "skipped_dedup"
```

After computing `aggregate` (and before composing), build the scorecard inputs and stash them on the returned artifact. Replace the URL/compose block with:

```python
    meta = fetch_alert_meta(alert_ids)
    primary = meta.get(alert_ids[0]) or {}
    event_label = (primary.get("market_title")
                   or primary.get("event_slug") or "this market")
    # The side the cluster was on: dominant by_market side_bet.
    outcome_side = ""
    if aggregate["by_market"]:
        outcome_side = next(iter(aggregate["by_market"].values()))["side_bet"]
    flagged_days_ago = 0
    ta = tweet.get("tweeted_at")
    if hasattr(ta, "tzinfo"):
        when = ta if ta.tzinfo else ta.replace(tzinfo=timezone.utc)
        flagged_days_ago = (datetime.now(timezone.utc) - when).days

    result_tweet = compose_result_tweet(
        llm_client, tweet.get("tweet_text") or "", aggregate)

    scorecard = build_scorecard_data(
        aggregate, event_label=event_label, outcome_side=outcome_side,
        flagged_days_ago=flagged_days_ago)
    png = charts.render_result_scorecard(scorecard)
    png_path = _write_scorecard_png(tweet_id, png)
    draft_path = _write_result_draft(tweet_id, result_tweet) if result_tweet else None
```

Extend the saved `artifact` dict with the publish metadata (add these keys to the existing literal):

```python
        "outcome": classify_outcome(aggregate),
        "event_label": event_label,
        "outcome_side": outcome_side,
        "scorecard_png_path": png_path,
        "result_draft_path": draft_path,
        "alert_ids": alert_ids,
        "condition_ids": condition_ids,
```

(The artifact already has `aggregate`, `original_tweet`, `result_tweet`,
`posted_to_twitter: False` — keep those.)

- [ ] **Step 3: Apply curated selection in `main()`**

In `main()`, after `candidates = fetch_candidate_tweets()`, gate the loop through `select_results`. Because `process_tweet` needs the aggregate to know win/loss, do a lightweight pre-pass: compute the aggregate per candidate, attach `is_win`/`net_pl_usd`/`notability`, select, then process only the winners. Replace the `for tweet in candidates:` loop with:

```python
    now = datetime.now(timezone.utc)
    posted_today = result_store.todays_posted_outcomes(now)

    # Pre-pass: resolve + aggregate each candidate so selection can rank them.
    scored: list[dict] = []
    for tweet in candidates:
        tid = str(tweet["tweet_id"])
        if result_store.result_exists(tid):
            counters["skipped_dedup"] += 1
            continue
        agg = _aggregate_for_candidate(tweet)  # None if unresolved/no trades
        if agg is None:
            counters["skipped_unresolved"] += 1
            continue
        net = float(agg["net_pl_usd"])
        scored.append({
            "tweet": tweet, "aggregate": agg,
            "is_win": classify_outcome(agg) == "cashed",
            "net_pl_usd": net, "notability": abs(net),
        })

    chosen = select_results(scored, posted_today=posted_today)
    log("results_selected", candidates=len(scored), chosen=len(chosen))

    for item in chosen:
        tweet = item["tweet"]
        tweet_id = str(tweet["tweet_id"])
        try:
            outcome = process_tweet(llm_client, tweet)
            counters[outcome] = counters.get(outcome, 0) + 1
            log("tweet_processed", tweet_id=tweet_id, outcome=outcome)
        except Exception as exc:
            counters["errors"] += 1
            log("tweet_error", tweet_id=tweet_id,
                error=f"{type(exc).__name__}: {exc}")
```

Add the pre-pass helper (factor the resolve+aggregate out of `process_tweet` so both share it) near `process_tweet`:

```python
def _aggregate_for_candidate(tweet: dict) -> dict | None:
    """Resolve every market the tweet covered and aggregate P&L. Returns the
    aggregate dict, or None if any market is unresolved or there are no trades.
    Pure-ish: no LLM, no writes — safe to call in the selection pre-pass."""
    alert_ids = [int(i) for i in (tweet.get("alert_ids") or []) if i is not None]
    condition_ids = [c for c in (tweet.get("condition_ids") or []) if c]
    if not alert_ids or not condition_ids:
        return None
    resolutions: dict[str, dict] = {}
    for cid in condition_ids:
        res = _resolution_for_market(cid)
        if res is None:
            return None
        resolutions[cid] = res
    trades = fetch_alert_trades(alert_ids)
    if not trades:
        return None
    aggregate = aggregate_result(trades, resolutions)
    return aggregate if aggregate["n_trades"] > 0 else None
```

Then refactor `process_tweet` to call `_aggregate_for_candidate` instead of repeating the resolve/fetch/aggregate block (replace that block with `aggregate = _aggregate_for_candidate(tweet)` + the existing `skipped_*` guards). Keep `alert_ids`/`condition_ids` local recomputation for the artifact.

- [ ] **Step 4: DRY_RUN smoke test**

Run:
```bash
source venv/bin/activate && DRY_RUN=true python storybot/result_pipeline.py
```
Expected: logs `candidates_fetched`, `results_selected`, and for any chosen tweet prints the result line + writes `storybot/dry_runs/result_<id>.png`. No exceptions. (If there are no resolved candidates right now, `chosen=0` is a valid pass — the run exits 0.)

- [ ] **Step 5: Run the full storybot test suite**

Run: `pytest test/ -q`
Expected: PASS (no regressions; existing result_pipeline tests still green).

- [ ] **Step 6: Commit**

```bash
git add storybot/result_pipeline.py
git commit -m "feat(results): select+render+draft in result_pipeline (no posting yet)"
```

---

## Task 6: `publish_result.py` + loop wiring

**Files:**
- Create: `storybot/publish_result.py`
- Modify: `storybot/run_result_pipeline_loop.sh`
- Test: `test/test_publish_result.py`

- [ ] **Step 1: Write the failing test (validation + dedup guard, no real network)**

Create `test/test_publish_result.py`:

```python
import json

import storybot.publish_result as pub


def test_publish_skips_when_already_recorded(monkeypatch, tmp_path):
    # If result_store says this original tweet is already settled, do not post.
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: True)
    posted = {"called": False}
    monkeypatch.setattr(pub, "post_tweet",
                        lambda *a, **k: posted.__setitem__("called", True) or "x")
    rc = pub.publish(original_tweet_id="111", artifact={
        "original_tweet": "x", "result_tweet": "ok", "result_draft_path": None,
        "scorecard_png_path": None, "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 1, "n_lost": 0, "net_pl_usd": 5.0,
                      "total_invested_usd": 10.0},
        "outcome": "cashed", "event_label": "E",
    }, dry_run=True)
    assert rc == 0
    assert posted["called"] is False  # dedup short-circuits before posting


def test_publish_rejects_invalid_tweet(monkeypatch):
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: False)
    # A tweet with a URL must be rejected by validate_tweet.
    rc = pub.publish(original_tweet_id="222", artifact={
        "result_tweet": "Cashed +$31k https://polyspotter.com/alert/1",
        "result_draft_path": None, "scorecard_png_path": None,
        "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 1, "n_lost": 0, "net_pl_usd": 5.0,
                      "total_invested_usd": 10.0},
        "outcome": "cashed", "event_label": "E",
    }, dry_run=True)
    assert rc == 1  # validation failure
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest test/test_publish_result.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storybot.publish_result'`

- [ ] **Step 3: Implement `storybot/publish_result.py`**

```python
"""Publish a drafted result tweet (the settle half of the accountability loop).

Reads the artifact result_pipeline.py wrote, re-validates the (possibly
Claude-edited) draft, posts it with the scorecard PNG, and records a
result_tweets row. Mirrors publish_tweet.py.

Usage:
    python storybot/publish_result.py <original_tweet_id>

Exit codes:
    0  posted (or skipped as already-settled) — nothing left to do
    1  no artifact / validation failed / post raised
    2  bad argv
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import storybot.result_store as result_store
from bot_utils import log
from twitter_pipeline import validate_tweet
from tweet_utils import _build_twitter_api_v1, _build_twitter_client, post_tweet

_STORYBOT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIVE_RUNS_DIR = os.path.join(_STORYBOT_DIR, "live_runs")
_RESULT_DRAFTS_DIR = os.path.join(_STORYBOT_DIR, "result_drafts")

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def _artifact_path(original_tweet_id: str) -> str:
    return os.path.join(_LIVE_RUNS_DIR, f"result_{original_tweet_id}.json")


def _load_draft_text(artifact: dict) -> str:
    """Prefer the on-disk draft (Claude may have edited it); fall back to the
    artifact's composed result_tweet."""
    path = artifact.get("result_draft_path")
    if path and os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return (artifact.get("result_tweet") or "").strip()


def publish(*, original_tweet_id: str, artifact: dict, dry_run: bool) -> int:
    if result_store.result_exists(original_tweet_id):
        log("result_skip", original_tweet_id=original_tweet_id,
            reason="already recorded")
        return 0

    text = _load_draft_text(artifact)
    ok, err = validate_tweet(text)
    if not ok:
        log("result_validation_failed", original_tweet_id=original_tweet_id,
            error=err)
        return 1

    png_path = artifact.get("scorecard_png_path")
    media_png = None
    if png_path and os.path.exists(png_path):
        with open(png_path, "rb") as f:
            media_png = f.read()

    try:
        client = None if dry_run else _build_twitter_client()
        api_v1 = None if dry_run else _build_twitter_api_v1()
        result_tweet_id = post_tweet(
            text, twitter_client=client, twitter_api_v1=api_v1,
            media_png=media_png, dry_run=dry_run)
    except Exception as exc:
        log("result_post_error", original_tweet_id=original_tweet_id,
            error=f"{type(exc).__name__}: {exc}")
        return 1

    agg = artifact.get("aggregate") or {}
    try:
        result_store.record_result(
            original_tweet_id=original_tweet_id,
            result_tweet_id=result_tweet_id,
            alert_ids=artifact.get("alert_ids") or [],
            condition_ids=artifact.get("condition_ids") or [],
            n_won=int(agg.get("n_won") or 0),
            n_lost=int(agg.get("n_lost") or 0),
            net_pl_usd=float(agg.get("net_pl_usd") or 0.0),
            total_invested_usd=float(agg.get("total_invested_usd") or 0.0),
            outcome=artifact.get("outcome") or "wash",
            event_label=artifact.get("event_label"),
        )
    except Exception as exc:
        # Tweet is already live; record failure is soft (dedup may double-post
        # on the next run, so log loudly).
        log("result_record_error", original_tweet_id=original_tweet_id,
            result_tweet_id=result_tweet_id,
            error=f"{type(exc).__name__}: {exc}")

    log("result_posted", original_tweet_id=original_tweet_id,
        result_tweet_id=result_tweet_id)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python storybot/publish_result.py <original_tweet_id>",
              file=sys.stderr)
        return 2
    original_tweet_id = argv[1]
    path = _artifact_path(original_tweet_id)
    if not os.path.exists(path):
        log("result_no_artifact", original_tweet_id=original_tweet_id, path=path)
        return 1
    with open(path) as f:
        artifact = json.load(f)
    return publish(original_tweet_id=original_tweet_id, artifact=artifact,
                   dry_run=DRY_RUN)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `pytest test/test_publish_result.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the loop to compose → edit → publish**

Edit `storybot/run_result_pipeline_loop.sh`. Replace the comment header lines that say it does NOT post, and replace the single `python storybot/result_pipeline.py` invocation block with a compose-then-publish chain mirroring `run_twitter_pipeline_loop.sh`. The pipeline must print a parseable marker; add this line at the end of each composed tweet in `result_pipeline.process_tweet` (after the existing `print` block):

```python
    print(f"[result_pipeline] draft original_tweet_id={tweet_id}", flush=True)
```

Then in the loop script, replace the run block with:

```bash
    output=$(stdbuf -oL -eL python storybot/result_pipeline.py 2>&1 | tee -a "$LOG_FILE")
    status="${PIPESTATUS[0]}"

    if [[ "$status" -eq 0 ]]; then
        echo "$output" \
          | grep -oP '\[result_pipeline\] draft original_tweet_id=\K[a-f0-9]+' \
          | while read -r rid; do
            echo "[loop] result draft $rid — invoking claude to edit" | tee -a "$LOG_FILE"
            prompt="Review and edit the result tweet draft at @storybot/result_drafts/$rid.txt — edit the file directly. The full computed result (W/L, net P&L, per-market breakdown) is in @storybot/live_runs/result_$rid.json; the scorecard image that will attach is @storybot/live_runs/result_$rid.png. Verify every dollar/record number in the tweet matches the artifact's aggregate, keep it under 270 chars, no URLs (they're stripped), and stay neutral on wins and losses (no gloating, no excuses). publish_result.py runs right after you finish and re-validates."
            if claude -p "$prompt" --dangerously-skip-permissions 2>&1 | tee -a "$LOG_FILE"; then
                if python storybot/publish_result.py "$rid" 2>&1 | tee -a "$LOG_FILE"; then
                    rm -f "storybot/result_drafts/$rid.txt"
                    echo "[loop] published result $rid" | tee -a "$LOG_FILE"
                else
                    echo "[loop] publish_result failed for $rid — draft preserved" | tee -a "$LOG_FILE"
                fi
            else
                echo "[loop] claude edit failed for $rid — not publishing" | tee -a "$LOG_FILE"
            fi
        done
    fi
```

Also update the loop's header comment to note it now posts results.

- [ ] **Step 6: DRY_RUN end-to-end smoke (no real post)**

Run:
```bash
source venv/bin/activate
DRY_RUN=true python storybot/result_pipeline.py        # writes drafts + artifacts
# pick an original_tweet_id from storybot/result_drafts/ if any were produced:
ls storybot/result_drafts/ 2>/dev/null
# DRY_RUN post returns a dryrun- id and records nothing real:
DRY_RUN=true python storybot/publish_result.py <id>    # if a draft exists
```
Expected: `result_posted` logged with a `dryrun-...` id; exit 0. With no resolved candidates, the draft step simply produces none — that's a valid pass.

- [ ] **Step 7: Full test suite + commit**

Run: `pytest test/ -q`
Expected: PASS.

```bash
git add storybot/publish_result.py storybot/run_result_pipeline_loop.sh storybot/result_pipeline.py test/test_publish_result.py
git commit -m "feat(results): publish_result.py + loop wiring to post settle tweets"
```

---

## Final verification

- [ ] `pytest test/ -q` is green.
- [ ] `DRY_RUN=true python storybot/result_pipeline.py` runs clean.
- [ ] The `result_tweets` table exists in the deployed Postgres (apply `backend/schema.sql`). **Deploy note:** the table must be created in the Railway `polybot` (backend) Postgres before the loop runs live, or `result_store` calls will error. Apply the new DDL there as part of rollout.
- [ ] Before going fully live: run the loop with `DRY_RUN=true` for a cycle and read a few generated result drafts + scorecards to confirm voice/accuracy, then drop `DRY_RUN`.

## Self-review notes (coverage vs spec Component A)

- Curated win-weighted selection + honesty floor → Task 2 (`select_results`, `RESULT_LOSS_NOTABLE_USD`, `RESULT_WIN_BIAS=0.8`). ✅
- Drop URL / link-free result tweet → Task 4. ✅
- Result scorecard image → Task 3. ✅
- `publish_result.py` mirroring `publish_tweet.py` → Task 6. ✅
- `result_tweets` table as dedup + (future) scoreboard source → Task 1, replaces artifact-file dedup → Task 5 Step 2. ✅
- Separate post budget (own `RESULT_DAILY_CAP`, not the flag feed's cap) → Task 2 + Task 5 Step 3. ✅
- Loop chains compose → Claude edit → publish → Task 6 Step 5. ✅
- **Deliberate deferral within A:** peak-window timing gate on result posts
  (spec's "separate budgets" para). Results are far less time-sensitive than
  live flags, and `RESULT_DAILY_CAP` already bounds volume, so the first cut
  posts results on the hourly loop without a window gate. If results land at
  bad hours in practice, add a `_current_peak_window`-style guard at the top of
  `result_pipeline.main()` (one `if` + early return) as a fast follow — the
  helper already exists in `twitter_pipeline.py`.
- Deferred to later phases (NOT in this plan): scoreboard module (B), weekly leaderboard (C), track-record closer (light B). Documented in spec; the `result_tweets` table is built now so B reads it later with no migration.
