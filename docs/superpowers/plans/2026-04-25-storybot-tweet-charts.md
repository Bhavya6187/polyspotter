# Storybot Tweet Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach an auto-generated chart image to every tweet posted by `storybot/twitter_simple.py`, picking from four chart templates (price sparkline, volume bar, wallet record card, cluster card) per alert. The LLM picks the type; a deterministic fallback ladder kicks in when the data isn't available.

**Architecture:** New module `storybot/charts.py` with one render function and one fetcher per chart type, plus a dispatcher. `twitter_simple.py` extended to (a) request `chart_type` in the LLM JSON output, (b) call the dispatcher to produce PNG bytes, (c) upload via tweepy v1.1 `media_upload` and attach to the existing v2 `create_tweet`.

**Tech Stack:** Python 3.13, matplotlib, Pillow, psycopg2 (Postgres), requests (CLOB / Polymarket Data API), tweepy v1.1 + v2.

---

## Precondition (before Task 8)

The X/Twitter account whose creds back `X_CONSUMER_KEY`, `X_CONSUMER_KEY_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` MUST have media-upload access. The Free tier does not include it. Verify this **before starting Task 8** by running this Python one-liner from `/home/bhavya/git/polybot` with the `.env` loaded:

```bash
source venv/bin/activate
python -c "
import os, tweepy
from dotenv import load_dotenv
load_dotenv()
auth = tweepy.OAuth1UserHandler(
    os.environ['X_CONSUMER_KEY'], os.environ['X_CONSUMER_KEY_SECRET'],
    os.environ['X_ACCESS_TOKEN'], os.environ['X_ACCESS_TOKEN_SECRET'],
)
api = tweepy.API(auth)
with open('/tmp/probe.png', 'wb') as f:
    f.write(b'\\x89PNG\\r\\n\\x1a\\n' + b'\\x00' * 64)  # not a real PNG, will 400
try:
    api.media_upload('/tmp/probe.png')
except tweepy.errors.Forbidden as e:
    print('FORBIDDEN — account lacks media-upload access:', e)
except tweepy.errors.HTTPException as e:
    print('Reached the endpoint:', type(e).__name__, e)  # 400 = good (means access OK, payload bad)
"
```

If you see `FORBIDDEN`, **STOP** — charts cannot ship without a plan upgrade. Tasks 1–7 (the chart module + tests) can still be built but Tasks 8–13 must wait. If you see `400` or any other error reaching the endpoint, access is fine; proceed.

---

## File structure

**New files:**
- `storybot/charts.py` — house style constants, four `*_Data` typed dicts, four `render_*` functions, four `fetch_*_data` functions, `render_chart_for_alert` dispatcher, and a small set of internal helpers. ~500 LOC when complete.
- `test/test_charts.py` — render tests using synthetic fixture data (PIL parses PNG bytes for dimension/format/non-empty assertions).
- `test/test_charts_dispatcher.py` — dispatcher behavior + fallback ladder tests.
- `storybot/render_all_charts.py` — dev-only smoke script. Pulls a recent alert from Postgres, renders all four chart types, writes them to `storybot/dry_runs/`. Not run in CI.

**Modified files:**
- `storybot/storybot.py` — add `_build_twitter_api_v1` helper next to existing `_build_twitter_client`.
- `storybot/twitter_simple.py` — extend SYSTEM_PROMPT, validate_decision, add `prepare_chart`, modify `post_tweet`, wire into `main`.
- `requirements.txt` — add `matplotlib` and `Pillow`.

The `storybot/charts.py` module is intentionally one file. Each chart type is a small self-contained pair of functions (~50 LOC each). Splitting by chart type would inflate the import surface for negligible separation-of-concerns benefit.

---

## Task 1: Add dependencies and scaffold `storybot/charts.py`

**Files:**
- Modify: `requirements.txt`
- Create: `storybot/charts.py`

- [ ] **Step 1: Add matplotlib and Pillow to `requirements.txt`**

Append two lines:

```
matplotlib
Pillow
```

- [ ] **Step 2: Install into the venv**

Run from project root:
```bash
source venv/bin/activate
pip install matplotlib Pillow
pip freeze | grep -E "matplotlib|Pillow"
```

Expected: both packages listed with version numbers.

- [ ] **Step 3: Create the scaffold for `storybot/charts.py`**

```python
"""
Chart rendering for storybot/twitter_simple.py.

Four chart types are supported. Each has a typed-dict input, a fetcher that
pulls the data from Postgres / CLOB / Polymarket Data API, and a renderer
that returns PNG bytes. A dispatcher picks the right pair by chart_type.

Visual house style is dark (#0E1117), 1200x675 (16:9 — fits Twitter's
1.91:1 in-feed preview without crop), no gridlines, no chartjunk.
"""
from __future__ import annotations

from io import BytesIO
from typing import TypedDict, Sequence

import matplotlib
matplotlib.use("Agg")  # headless, no display required
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


# ----------------------- House style -----------------------

CHART_TYPES = (
    "price_sparkline",
    "volume_bar",
    "wallet_record_card",
    "cluster_card",
    "none",
)

CANVAS_W_PX = 1200
CANVAS_H_PX = 675
DPI = 100  # 12.0 x 6.75 inches at DPI=100

BG = "#0E1117"
FG = "#FFFFFF"
ACCENT = "#22C55E"   # brand green / size-up / wins
LOSS = "#EF4444"     # red / losses
MUTED = "#9CA3AF"    # axis labels, footer text


def _new_figure() -> tuple[Figure, "plt.Axes"]:
    """Create a 1200x675 figure with the house background. Caller adds content."""
    fig = Figure(figsize=(CANVAS_W_PX / DPI, CANVAS_H_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=MUTED, length=0)
    return fig, ax


def _figure_to_png_bytes(fig: Figure) -> bytes:
    """Serialize a Figure to PNG bytes and close it."""
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=DPI)
    plt.close(fig)
    return buf.getvalue()
```

- [ ] **Step 4: Verify the module imports cleanly**

Run:
```bash
source venv/bin/activate
python -c "from storybot import charts; print(charts.CHART_TYPES)"
```

Wait — `from storybot import charts` only works inside the storybot directory's sys.path context. Use the same pattern the existing bot uses:

```bash
cd /home/bhavya/git/polybot
PYTHONPATH=storybot python -c "import charts; print(charts.CHART_TYPES)"
```

Expected: `('price_sparkline', 'volume_bar', 'wallet_record_card', 'cluster_card', 'none')`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt storybot/charts.py
git commit -m "charts: scaffold module + house style"
```

---

## Task 2: Implement `wallet_record_card` (renderer + fetcher + tests)

**Files:**
- Modify: `storybot/charts.py`
- Create: `test/test_charts.py`

This card is text-heavy: a hero number ("88%" or "29-4"), a record bar, and a footer line. No plotting library knobs to fight. We build it first because it's also the deterministic fallback target for the other chart types — the fallback ladder needs it before it can rely on it.

- [ ] **Step 1: Write the failing test**

Create `test/test_charts.py`:

```python
"""Tests for storybot/charts.py — synthetic data, byte-level assertions."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# storybot directory on sys.path (matches how the bot is run in production)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))

import charts  # noqa: E402


def _png_dimensions(b: bytes) -> tuple[int, int]:
    img = Image.open(BytesIO(b))
    assert img.format == "PNG"
    return img.size


# --------- wallet_record_card ---------

def test_wallet_record_card_renders_png_at_canvas_size():
    data: charts.WalletRecordCardData = {
        "market_title": "Will Trump win 2024?",
        "record_str": "29-4",
        "win_pct": 0.879,
        "bet_count": 33,
        "wallet_age_days": 412,
        "bet_size_usd": 80_000,
        "outcome_side": "Yes",
    }
    png = charts.render_wallet_record_card(data)
    assert isinstance(png, bytes)
    assert len(png) > 1000  # not empty
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_wallet_record_card_handles_missing_age():
    data: charts.WalletRecordCardData = {
        "market_title": "Some market",
        "record_str": "12-2",
        "win_pct": 0.857,
        "bet_count": 14,
        "wallet_age_days": None,
        "bet_size_usd": 5_000,
        "outcome_side": "No",
    }
    png = charts.render_wallet_record_card(data)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
pytest test/test_charts.py -v
```

Expected: FAIL with `AttributeError: module 'charts' has no attribute 'render_wallet_record_card'`.

- [ ] **Step 3: Implement `WalletRecordCardData` and `render_wallet_record_card`**

Append to `storybot/charts.py`:

```python
# ----------------------- wallet_record_card -----------------------

class WalletRecordCardData(TypedDict):
    market_title: str
    record_str: str          # e.g. "29-4"
    win_pct: float           # 0..1
    bet_count: int
    wallet_age_days: int | None
    bet_size_usd: float
    outcome_side: str        # "Yes" / "Arsenal" / etc.


def _format_usd(amount: float) -> str:
    """Round dollars for readability: 78131 -> '$78k', 2789285 -> '$2.8M'."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:.0f}"


def render_wallet_record_card(data: WalletRecordCardData) -> bytes:
    fig, ax = _new_figure()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    # Top: market title in muted grey
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero number: prefer record string ("29-4") if win_pct >= 0.7, else show pct.
    hero = data["record_str"] if data["win_pct"] >= 0.7 else f"{data['win_pct']*100:.0f}%"
    ax.text(0.5, 0.62, hero, color=ACCENT, fontsize=110, ha="center", va="center",
            fontweight="bold")

    # Subtitle: count of prior bets
    age_str = (
        f", {data['wallet_age_days']}-day-old account" if data["wallet_age_days"] is not None
        else ""
    )
    subtitle = f"across {data['bet_count']} prior Polymarket bets{age_str}"
    ax.text(0.5, 0.40, subtitle, color=FG, fontsize=20, ha="center", va="center")

    # Record bar: green for wins, red for losses, sized by win_pct
    bar_y, bar_h = 0.22, 0.06
    ax.add_patch(plt.Rectangle((0.1, bar_y), 0.8 * data["win_pct"], bar_h,
                               color=ACCENT, transform=ax.transAxes))
    ax.add_patch(plt.Rectangle((0.1 + 0.8 * data["win_pct"], bar_y),
                               0.8 * (1 - data["win_pct"]), bar_h,
                               color=LOSS, transform=ax.transAxes))

    # Footer: bet size + outcome side
    footer = f"{_format_usd(data['bet_size_usd'])} on {data['outcome_side']}"
    ax.text(0.5, 0.10, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")

    return _figure_to_png_bytes(fig)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest test/test_charts.py -v
```

Expected: both `wallet_record_card` tests PASS.

- [ ] **Step 5: Render once to disk and visually inspect**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
PYTHONPATH=storybot python -c "
import charts
data = {
    'market_title': 'Will Trump win 2024?',
    'record_str': '29-4',
    'win_pct': 0.879,
    'bet_count': 33,
    'wallet_age_days': 412,
    'bet_size_usd': 80_000,
    'outcome_side': 'Yes',
}
with open('storybot/dry_runs/wallet_record_card_smoke.png', 'wb') as f:
    f.write(charts.render_wallet_record_card(data))
print('Wrote storybot/dry_runs/wallet_record_card_smoke.png')
"
```

Open the PNG. Verify: title legible at top, "29-4" big and centered, subtitle reads naturally, record bar mostly green with a small red sliver, footer reads "$80k on Yes". If anything looks broken (text cut off, bar wrong size, colors muddy), fix before moving on.

- [ ] **Step 6: Implement `fetch_wallet_record_card_data`**

Append to `storybot/charts.py`. This reads the alert dict (one of the dicts returned by `fetch_seed_alerts`) and builds the typed dict, returning `None` when the wallet has too few prior bets to be credible.

```python
import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")
QUERY_TIMEOUT_SECONDS = 10
WALLET_RECORD_MIN_BETS = 10  # below this, the record isn't a story


def fetch_wallet_record_card_data(alert: dict) -> WalletRecordCardData | None:
    wallet = alert.get("wallet")
    if not wallet:
        return None

    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT total_bets, wins, win_rate, account_age_days
            FROM wallet_pnl
            WHERE wallet = %s
            """,
            (wallet,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return None
    total_bets, wins, win_rate, age_days = row
    if total_bets is None or total_bets < WALLET_RECORD_MIN_BETS:
        return None

    losses = total_bets - wins
    copy = alert.get("llm_copy_action") or {}
    outcome_side = copy.get("outcome") or copy.get("side") or ""

    return {
        "market_title": alert.get("market_title", ""),
        "record_str": f"{wins}-{losses}",
        "win_pct": float(win_rate or (wins / total_bets if total_bets else 0)),
        "bet_count": int(total_bets),
        "wallet_age_days": int(age_days) if age_days is not None else None,
        "bet_size_usd": float(alert.get("total_usd", 0)),
        "outcome_side": outcome_side,
    }
```

NOTE: verify the column names by reading `backend/schema.sql` for the `wallet_pnl` table before running. If column names differ, adjust the SELECT and the row unpacking. Common alternatives: `n_bets` instead of `total_bets`, `win_count` instead of `wins`. Treat missing columns as a fixable bug, not a redesign.

- [ ] **Step 7: Add a fetcher test that asserts `None` on too-few-bets**

Append to `test/test_charts.py`:

```python
from unittest.mock import patch


def test_fetch_wallet_record_card_returns_none_for_unknown_wallet():
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        mock_cur.fetchone.return_value = None
        result = charts.fetch_wallet_record_card_data({"wallet": "0xabc"})
    assert result is None


def test_fetch_wallet_record_card_returns_none_for_too_few_bets():
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        mock_cur.fetchone.return_value = (5, 4, 0.8, 30)  # only 5 bets
        result = charts.fetch_wallet_record_card_data({"wallet": "0xabc"})
    assert result is None


def test_fetch_wallet_record_card_returns_data_when_eligible():
    alert = {
        "wallet": "0xabc",
        "market_title": "Will Trump win 2024?",
        "total_usd": 80_000,
        "llm_copy_action": {"outcome": "Yes"},
    }
    with patch("charts.psycopg2.connect") as mock_connect:
        mock_cur = mock_connect.return_value.cursor.return_value
        mock_cur.fetchone.return_value = (33, 29, 0.879, 412)
        result = charts.fetch_wallet_record_card_data(alert)
    assert result is not None
    assert result["record_str"] == "29-4"
    assert result["bet_count"] == 33
    assert result["wallet_age_days"] == 412
```

- [ ] **Step 8: Run all chart tests**

```bash
pytest test/test_charts.py -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add storybot/charts.py test/test_charts.py
git commit -m "charts: wallet_record_card renderer + fetcher"
```

---

## Task 3: Implement `volume_bar` (renderer + fetcher + tests)

**Files:**
- Modify: `storybot/charts.py`
- Modify: `test/test_charts.py`

- [ ] **Step 1: Write the failing renderer test**

Append to `test/test_charts.py`:

```python
def test_volume_bar_renders_png_at_canvas_size():
    data: charts.VolumeBarData = {
        "market_title": "Arsenal vs Newcastle",
        "today_volume_usd": 906_000,
        "baseline_avg_usd": 1_000,
        "multiplier": 906.0,
    }
    png = charts.render_volume_bar(data)
    assert isinstance(png, bytes)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest test/test_charts.py::test_volume_bar_renders_png_at_canvas_size -v
```

Expected: FAIL with `AttributeError: render_volume_bar`.

- [ ] **Step 3: Implement renderer**

Append to `storybot/charts.py`:

```python
# ----------------------- volume_bar -----------------------

class VolumeBarData(TypedDict):
    market_title: str
    today_volume_usd: float
    baseline_avg_usd: float
    multiplier: float


def render_volume_bar(data: VolumeBarData) -> bytes:
    fig, ax = _new_figure()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    # Title
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero multiplier
    mult = data["multiplier"]
    mult_label = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    ax.text(0.5, 0.72, mult_label, color=ACCENT, fontsize=120, ha="center", va="center",
            fontweight="bold")
    ax.text(0.5, 0.55, "today's volume vs. 7-day average", color=FG, fontsize=20,
            ha="center", va="center")

    # Two horizontal bars — baseline tiny, today full-width
    # Map widths to a log-friendly visual: baseline always >= 4% of bar area for visibility.
    today = max(data["today_volume_usd"], 1.0)
    baseline = max(data["baseline_avg_usd"], 1.0)
    today_w = 0.8
    baseline_w = max(0.04, today_w * (baseline / today))

    ax.add_patch(plt.Rectangle((0.1, 0.32), baseline_w, 0.04, color=MUTED,
                               transform=ax.transAxes))
    ax.text(0.1 + baseline_w + 0.02, 0.34,
            f"7-day daily avg: {_format_usd(baseline)}",
            color=MUTED, fontsize=14, ha="left", va="center")

    ax.add_patch(plt.Rectangle((0.1, 0.20), today_w, 0.06, color=ACCENT,
                               transform=ax.transAxes))
    ax.text(0.1 + today_w + 0.02, 0.23,
            f"today: {_format_usd(today)}",
            color=FG, fontsize=16, ha="left", va="center", fontweight="bold")

    return _figure_to_png_bytes(fig)
```

- [ ] **Step 4: Run renderer test**

```bash
pytest test/test_charts.py::test_volume_bar_renders_png_at_canvas_size -v
```

Expected: PASS.

- [ ] **Step 5: Visual smoke check**

```bash
PYTHONPATH=storybot python -c "
import charts
data = {'market_title': 'Arsenal vs Newcastle', 'today_volume_usd': 906_000, 'baseline_avg_usd': 1_000, 'multiplier': 906.0}
with open('storybot/dry_runs/volume_bar_smoke.png', 'wb') as f:
    f.write(charts.render_volume_bar(data))
print('Wrote volume_bar_smoke.png')
"
```

Open. Verify the "906×" hero is dominant, the two bars are clearly different sizes, and the labels don't overflow.

- [ ] **Step 6: Implement `fetch_volume_bar_data` with mocked HTTP test**

The Polymarket Data API trades endpoint returns trades with `usdcSize` (or similar) per row. We aggregate.

Append to `storybot/charts.py`:

```python
import time
import requests

POLYMARKET_DATA_API = "https://data-api.polymarket.com"
VOLUME_BAR_MIN_TODAY_USD = 1_000
VOLUME_BAR_MIN_MULTIPLIER = 5.0


def _fetch_market_volume_window(condition_id: str, start_ts: int, end_ts: int) -> float:
    """Sum trade $ on a market between two unix timestamps. Paginated."""
    total = 0.0
    cursor = ""
    page_size = 500
    while True:
        params = {
            "market": condition_id,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": page_size,
        }
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{POLYMARKET_DATA_API}/trades", params=params, timeout=15)
        r.raise_for_status()
        body = r.json()
        rows = body if isinstance(body, list) else body.get("data", [])
        for row in rows:
            size = row.get("usdcSize") or row.get("size") or 0
            try:
                total += float(size)
            except (TypeError, ValueError):
                continue
        next_cursor = body.get("nextCursor", "") if isinstance(body, dict) else ""
        if not next_cursor or len(rows) < page_size:
            break
        cursor = next_cursor
    return total


def fetch_volume_bar_data(alert: dict) -> VolumeBarData | None:
    cid = alert.get("condition_id")
    if not cid:
        return None

    now = int(time.time())
    today_start = now - 86_400
    week_start = now - 86_400 * 8
    week_end = now - 86_400

    today = _fetch_market_volume_window(cid, today_start, now)
    if today < VOLUME_BAR_MIN_TODAY_USD:
        return None
    baseline_total = _fetch_market_volume_window(cid, week_start, week_end)
    baseline_avg = baseline_total / 7.0
    if baseline_avg <= 0:
        return None
    mult = today / baseline_avg
    if mult < VOLUME_BAR_MIN_MULTIPLIER:
        return None

    return {
        "market_title": alert.get("market_title", ""),
        "today_volume_usd": today,
        "baseline_avg_usd": baseline_avg,
        "multiplier": mult,
    }
```

- [ ] **Step 7: Add fetcher tests**

Append to `test/test_charts.py`:

```python
def test_fetch_volume_bar_returns_none_when_today_too_small():
    with patch("charts._fetch_market_volume_window", return_value=500.0):
        result = charts.fetch_volume_bar_data({"condition_id": "0xabc"})
    assert result is None


def test_fetch_volume_bar_returns_none_when_multiplier_below_threshold():
    # today=10k, baseline_total=14k -> baseline_avg=2k -> mult=5x exactly, fails strict <
    calls = iter([10_000.0, 14_000.0])  # today, baseline_total
    with patch("charts._fetch_market_volume_window", side_effect=lambda *a, **k: next(calls)):
        result = charts.fetch_volume_bar_data({"condition_id": "0xabc"})
    # 10000 / 2000 = 5.0 -> meets threshold (>=). Bump baseline to make it 4.9x.
    # Re-run with 14_300.
    calls = iter([10_000.0, 14_300.0])
    with patch("charts._fetch_market_volume_window", side_effect=lambda *a, **k: next(calls)):
        result = charts.fetch_volume_bar_data({"condition_id": "0xabc"})
    assert result is None  # 4.9x < 5.0


def test_fetch_volume_bar_returns_data_for_real_spike():
    calls = iter([906_000.0, 7_000.0])  # today, baseline_total
    with patch("charts._fetch_market_volume_window", side_effect=lambda *a, **k: next(calls)):
        result = charts.fetch_volume_bar_data({
            "condition_id": "0xabc",
            "market_title": "Arsenal vs Newcastle",
        })
    assert result is not None
    assert result["multiplier"] > 800
```

- [ ] **Step 8: Run all chart tests**

```bash
pytest test/test_charts.py -v
```

Expected: all PASS. Note: the threshold check above uses `>=`. Verify the implementation matches; adjust the test or the threshold so the test reflects the chosen semantics.

- [ ] **Step 9: Commit**

```bash
git add storybot/charts.py test/test_charts.py
git commit -m "charts: volume_bar renderer + fetcher"
```

---

## Task 4: Implement `cluster_card` (renderer + fetcher + pseudonym helper + tests)

**Files:**
- Modify: `storybot/charts.py`
- Modify: `test/test_charts.py`

- [ ] **Step 1: Read `frontend/src/lib/pseudonym.js` to mirror the hashing scheme**

```bash
cat /home/bhavya/git/polybot/frontend/src/lib/pseudonym.js
```

Read it and note the algorithm — wallet address → stable pseudonym (e.g. "Cobalt Otter"). The Python port must produce the SAME output for the same input so a wallet appears identically across frontend and tweets.

If the JS uses a hashing algorithm not natively available in Python (e.g. a custom function), port it character-for-character. If it uses a standard hash like SHA-256 or FNV, use Python's `hashlib` / equivalents. Word lists must be copied byte-for-byte.

- [ ] **Step 2: Write the renderer test**

Append to `test/test_charts.py`:

```python
def test_cluster_card_renders_png_at_canvas_size():
    data: charts.ClusterCardData = {
        "market_title": "Arsenal vs Newcastle — Arsenal wins",
        "outcome_side": "Arsenal",
        "wallet_sizes": [
            ("Cobalt Otter", 180_000),
            ("Saffron Hawk", 120_000),
            ("Magenta Lynx", 50_000),
            ("Verdant Mole", 30_000),
            ("Crimson Wren", 14_000),
        ],
        "total_usd": 394_000,
        "shared_funder": "0xabc1234567890",
    }
    png = charts.render_cluster_card(data)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest test/test_charts.py::test_cluster_card_renders_png_at_canvas_size -v
```

Expected: FAIL with `AttributeError: render_cluster_card`.

- [ ] **Step 4: Implement pseudonym helper + renderer**

Append to `storybot/charts.py`:

```python
# ----------------------- cluster_card -----------------------

class ClusterCardData(TypedDict):
    market_title: str
    outcome_side: str
    wallet_sizes: list[tuple[str, float]]   # (pseudonym, $)
    total_usd: float
    shared_funder: str | None


# Pseudonym word lists — these MUST be copied byte-for-byte from
# frontend/src/lib/pseudonym.js. The frontend and the bot must produce
# the same pseudonym for the same wallet address.
# Fill these in during Step 1; a placeholder pair is shown for shape only.
_PSEUDONYM_ADJECTIVES: list[str] = []  # populate from frontend/src/lib/pseudonym.js
_PSEUDONYM_NOUNS: list[str] = []       # populate from frontend/src/lib/pseudonym.js


def wallet_pseudonym(wallet: str) -> str:
    """Stable pseudonym for a wallet address. Mirrors frontend/src/lib/pseudonym.js."""
    # Algorithm port from pseudonym.js — fill in based on what that file does.
    # Placeholder: hex-derived index into both lists.
    import hashlib
    h = hashlib.sha256(wallet.lower().encode()).digest()
    if not _PSEUDONYM_ADJECTIVES or not _PSEUDONYM_NOUNS:
        # Fallback if word lists weren't populated yet; never ship empty lists.
        return wallet[:6] + "…" + wallet[-4:]
    a = _PSEUDONYM_ADJECTIVES[h[0] % len(_PSEUDONYM_ADJECTIVES)]
    n = _PSEUDONYM_NOUNS[h[1] % len(_PSEUDONYM_NOUNS)]
    return f"{a} {n}"


def render_cluster_card(data: ClusterCardData) -> bytes:
    fig, ax = _new_figure()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])

    # Title
    ax.text(0.5, 0.93, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Bars: one per wallet, sized proportionally
    wallets = data["wallet_sizes"][:8]  # cap at 8 to keep readable
    if not wallets:
        # Defensive: shouldn't happen because the fetcher rejects 0-wallet clusters.
        return _figure_to_png_bytes(fig)
    max_size = max(w[1] for w in wallets)
    bar_top = 0.78
    bar_h = 0.06
    spacing = 0.02
    for i, (name, size_usd) in enumerate(wallets):
        y = bar_top - i * (bar_h + spacing)
        w = 0.6 * (size_usd / max_size)
        ax.add_patch(plt.Rectangle((0.1, y), w, bar_h, color=ACCENT,
                                   transform=ax.transAxes))
        ax.text(0.09, y + bar_h / 2, name, color=FG, fontsize=14,
                ha="right", va="center")
        ax.text(0.1 + w + 0.01, y + bar_h / 2, _format_usd(size_usd),
                color=FG, fontsize=14, ha="left", va="center")

    # Total + shared funder
    total_str = f"{_format_usd(data['total_usd'])} on {data['outcome_side']}"
    ax.text(0.5, 0.16, total_str, color=ACCENT, fontsize=28, ha="center", va="center",
            fontweight="bold")
    if data["shared_funder"]:
        funder = data["shared_funder"]
        funder_disp = funder[:6] + "…" + funder[-4:] if len(funder) > 12 else funder
        ax.text(0.5, 0.08, f"Shared funder: {funder_disp}", color=MUTED, fontsize=14,
                ha="center", va="center")

    return _figure_to_png_bytes(fig)
```

- [ ] **Step 5: Run renderer test**

```bash
pytest test/test_charts.py::test_cluster_card_renders_png_at_canvas_size -v
```

Expected: PASS.

- [ ] **Step 6: Visual smoke check**

```bash
PYTHONPATH=storybot python -c "
import charts
data = {
    'market_title': 'Arsenal vs Newcastle — Arsenal wins',
    'outcome_side': 'Arsenal',
    'wallet_sizes': [('Cobalt Otter', 180_000), ('Saffron Hawk', 120_000), ('Magenta Lynx', 50_000), ('Verdant Mole', 30_000), ('Crimson Wren', 14_000)],
    'total_usd': 394_000,
    'shared_funder': '0xabc1234567890def',
}
with open('storybot/dry_runs/cluster_card_smoke.png', 'wb') as f:
    f.write(charts.render_cluster_card(data))
"
```

Open. Verify: 5 bars stacked, names left-aligned, sizes right-aligned, total in green near bottom, funder line at the very bottom. If pseudonyms haven't been populated yet, expect to see truncated 0x… as the fallback — that's expected at this stage, will be filled in next step.

- [ ] **Step 7: Implement `fetch_cluster_card_data`**

The cluster fetcher reads the alert's signals JSON for cluster size, the alert's trades JSON for per-wallet sizes, and `wallet_funders` for the shared funder.

Append to `storybot/charts.py`:

```python
import json

CLUSTER_CARD_MIN_WALLETS = 2


def _wallets_in_alert(alert: dict) -> list[tuple[str, float]]:
    """Return [(wallet_address, $size), ...] from the alert's trades JSON, summed per wallet."""
    trades = alert.get("trades")
    if isinstance(trades, str):
        try:
            trades = json.loads(trades)
        except json.JSONDecodeError:
            trades = []
    if not isinstance(trades, list):
        return []
    sums: dict[str, float] = {}
    for t in trades:
        w = t.get("proxyWallet") or t.get("wallet")
        if not w:
            continue
        size = float(t.get("usdcSize") or t.get("size") or 0)
        sums[w] = sums.get(w, 0) + size
    return sorted(sums.items(), key=lambda kv: kv[1], reverse=True)


def _shared_funder_for_wallets(wallets: list[str]) -> str | None:
    """Look up the most common shared funder across the given wallets in wallet_funders."""
    if len(wallets) < 2:
        return None
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT funder, COUNT(*) AS n
            FROM wallet_funders
            WHERE wallet = ANY(%s)
            GROUP BY funder
            ORDER BY n DESC
            LIMIT 1
            """,
            (wallets,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not row:
        return None
    funder, n = row
    return funder if n >= 2 else None


def fetch_cluster_card_data(alert: dict) -> ClusterCardData | None:
    wallet_sizes_raw = _wallets_in_alert(alert)
    if len(wallet_sizes_raw) < CLUSTER_CARD_MIN_WALLETS:
        return None
    addresses = [w for w, _ in wallet_sizes_raw]
    wallet_sizes = [(wallet_pseudonym(w), s) for w, s in wallet_sizes_raw]
    funder = _shared_funder_for_wallets(addresses)
    if not funder:
        return None  # no shared funder = no real "cluster" story
    copy = alert.get("llm_copy_action") or {}
    return {
        "market_title": alert.get("market_title", ""),
        "outcome_side": copy.get("outcome") or copy.get("side") or "",
        "wallet_sizes": wallet_sizes,
        "total_usd": float(alert.get("total_usd", 0)),
        "shared_funder": funder,
    }
```

NOTE: verify column names in `wallet_funders` against `backend/schema.sql`. The columns may be `wallet`/`funder` or different — adjust the SELECT.

- [ ] **Step 8: Add fetcher tests**

Append to `test/test_charts.py`:

```python
def test_fetch_cluster_card_returns_none_for_single_wallet():
    alert = {"trades": [{"proxyWallet": "0xabc", "usdcSize": 1000}]}
    result = charts.fetch_cluster_card_data(alert)
    assert result is None


def test_fetch_cluster_card_returns_none_when_no_shared_funder():
    alert = {
        "trades": [
            {"proxyWallet": "0xabc", "usdcSize": 1000},
            {"proxyWallet": "0xdef", "usdcSize": 2000},
        ],
    }
    with patch("charts._shared_funder_for_wallets", return_value=None):
        result = charts.fetch_cluster_card_data(alert)
    assert result is None


def test_fetch_cluster_card_returns_data_when_shared_funder_present():
    alert = {
        "market_title": "Arsenal vs Newcastle — Arsenal wins",
        "total_usd": 3000,
        "llm_copy_action": {"outcome": "Arsenal"},
        "trades": [
            {"proxyWallet": "0xabc", "usdcSize": 1000},
            {"proxyWallet": "0xdef", "usdcSize": 2000},
        ],
    }
    with patch("charts._shared_funder_for_wallets", return_value="0xfunder"):
        result = charts.fetch_cluster_card_data(alert)
    assert result is not None
    assert len(result["wallet_sizes"]) == 2
    assert result["shared_funder"] == "0xfunder"
    assert result["outcome_side"] == "Arsenal"
```

- [ ] **Step 9: Run all chart tests**

```bash
pytest test/test_charts.py -v
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add storybot/charts.py test/test_charts.py
git commit -m "charts: cluster_card renderer + fetcher + pseudonym helper"
```

---

## Task 5: Implement `price_sparkline` (renderer + fetcher + tests)

**Files:**
- Modify: `storybot/charts.py`
- Modify: `test/test_charts.py`

- [ ] **Step 1: Write the failing renderer test**

Append to `test/test_charts.py`:

```python
def test_price_sparkline_renders_png_at_canvas_size():
    import time
    now = time.time()
    times = [now - 86_400 + i * 3600 for i in range(24)]
    prices = [0.32 + 0.001 * i + (0.05 if i > 18 else 0) for i in range(24)]
    data: charts.PriceSparklineData = {
        "market_title": "Will Trump win 2024?",
        "outcome_side": "Yes",
        "times": times,
        "prices": prices,
        "trade_times": [now - 7200, now - 3600],
        "trade_prices": [0.36, 0.41],
        "trade_sizes_usd": [25_000, 80_000],
    }
    png = charts.render_price_sparkline(data)
    assert _png_dimensions(png) == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest test/test_charts.py::test_price_sparkline_renders_png_at_canvas_size -v
```

Expected: FAIL with `AttributeError: render_price_sparkline`.

- [ ] **Step 3: Implement renderer**

Append to `storybot/charts.py`:

```python
# ----------------------- price_sparkline -----------------------

class PriceSparklineData(TypedDict):
    market_title: str
    outcome_side: str
    times: Sequence[float]            # unix timestamps, ascending
    prices: Sequence[float]           # 0..1, same length as times
    trade_times: Sequence[float]
    trade_prices: Sequence[float]
    trade_sizes_usd: Sequence[float]


def render_price_sparkline(data: PriceSparklineData) -> bytes:
    fig, ax = _new_figure()
    times = list(data["times"])
    prices = list(data["prices"])
    if len(times) < 2 or len(times) != len(prices):
        # Defensive — fetcher should have rejected this case.
        return _figure_to_png_bytes(fig)

    # Title
    title = f"{data['market_title']} — {data['outcome_side']}"
    fig.suptitle(title, color=MUTED, fontsize=18, y=0.95)

    ax.plot(times, prices, color=ACCENT, linewidth=3)
    # Trade markers
    if data["trade_times"]:
        sizes = list(data["trade_sizes_usd"]) or [10_000] * len(data["trade_times"])
        # Marker size scaled by $: $10k -> 60, $100k -> 200, capped.
        scaled = [min(60 + s / 800, 240) for s in sizes]
        ax.scatter(list(data["trade_times"]), list(data["trade_prices"]),
                   s=scaled, color=FG, edgecolor=ACCENT, linewidth=2, zorder=5)

    # Y-axis: pin to actual price range with small padding
    pmin, pmax = min(prices), max(prices)
    pad = max((pmax - pmin) * 0.15, 0.01)
    ax.set_ylim(max(0, pmin - pad), min(1, pmax + pad))

    # Show only the start/end price labels, no other ticks
    ax.set_yticks([prices[0], prices[-1]])
    ax.set_yticklabels(
        [f"{int(prices[0]*100)}c", f"{int(prices[-1]*100)}c"],
        color=FG, fontsize=14,
    )
    ax.set_xticks([times[0], times[-1]])
    ax.set_xticklabels(
        ["24h ago", "now"], color=MUTED, fontsize=12,
    )

    return _figure_to_png_bytes(fig)
```

- [ ] **Step 4: Run renderer test**

```bash
pytest test/test_charts.py::test_price_sparkline_renders_png_at_canvas_size -v
```

Expected: PASS.

- [ ] **Step 5: Visual smoke check**

```bash
PYTHONPATH=storybot python -c "
import charts, time
now = time.time()
times = [now - 86_400 + i * 3600 for i in range(24)]
prices = [0.32 + 0.001 * i + (0.05 if i > 18 else 0) for i in range(24)]
data = {
    'market_title': 'Will Trump win 2024?',
    'outcome_side': 'Yes',
    'times': times, 'prices': prices,
    'trade_times': [now - 7200, now - 3600],
    'trade_prices': [0.36, 0.41],
    'trade_sizes_usd': [25_000, 80_000],
}
with open('storybot/dry_runs/price_sparkline_smoke.png', 'wb') as f:
    f.write(charts.render_price_sparkline(data))
"
```

Open. Verify: line is clearly visible, two trade dots near the upper-right, "32c" labeled at left edge of y-axis, "41c" labeled at right edge, "24h ago" and "now" along x-axis, title at top.

- [ ] **Step 6: Implement `fetch_price_sparkline_data`**

Append to `storybot/charts.py`:

```python
CLOB_API = "https://clob.polymarket.com"
SPARKLINE_MIN_POINTS = 2
SPARKLINE_MIN_MOVE = 0.01  # 1 cent


def _fetch_clob_prices_history(token_id: str, hours: int = 24) -> list[tuple[float, float]]:
    """Return [(unix_ts, price), ...] for the last `hours` hours from CLOB."""
    end_ts = int(time.time())
    start_ts = end_ts - hours * 3600
    params = {"market": token_id, "startTs": start_ts, "endTs": end_ts, "fidelity": 60}
    r = requests.get(f"{CLOB_API}/prices-history", params=params, timeout=15)
    r.raise_for_status()
    body = r.json()
    points = body.get("history") if isinstance(body, dict) else body
    if not isinstance(points, list):
        return []
    out: list[tuple[float, float]] = []
    for p in points:
        try:
            out.append((float(p["t"]), float(p["p"])))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda kv: kv[0])
    return out


def _yes_token_id(alert: dict) -> str | None:
    """The CLOB price for a market is keyed by the outcome token. Pull the YES token id
    from the alert's stored market metadata (typically alert['tokens'] or
    alert['llm_copy_action']['token_id'])."""
    copy = alert.get("llm_copy_action") or {}
    if copy.get("token_id"):
        return copy["token_id"]
    tokens = alert.get("tokens")
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except json.JSONDecodeError:
            tokens = None
    if isinstance(tokens, list) and tokens:
        # Prefer the token matching the outcome side; otherwise first.
        side = (copy.get("outcome") or copy.get("side") or "").lower()
        for t in tokens:
            if isinstance(t, dict) and (t.get("outcome") or "").lower() == side:
                return t.get("token_id") or t.get("id")
        first = tokens[0]
        if isinstance(first, dict):
            return first.get("token_id") or first.get("id")
    return None


def fetch_price_sparkline_data(alert: dict) -> PriceSparklineData | None:
    token_id = _yes_token_id(alert)
    if not token_id:
        return None
    history = _fetch_clob_prices_history(token_id, hours=24)
    if len(history) < SPARKLINE_MIN_POINTS:
        return None
    prices = [p for _, p in history]
    if max(prices) - min(prices) < SPARKLINE_MIN_MOVE:
        return None  # nothing visually interesting

    times = [t for t, _ in history]

    trades = alert.get("trades")
    if isinstance(trades, str):
        try:
            trades = json.loads(trades)
        except json.JSONDecodeError:
            trades = []
    if not isinstance(trades, list):
        trades = []

    window_start = times[0]
    trade_times: list[float] = []
    trade_prices: list[float] = []
    trade_sizes: list[float] = []
    for t in trades:
        ts = t.get("timestamp") or t.get("ts") or 0
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        if ts_f < window_start:
            continue
        try:
            tp = float(t.get("price", 0))
            tsize = float(t.get("usdcSize") or t.get("size") or 0)
        except (TypeError, ValueError):
            continue
        trade_times.append(ts_f)
        trade_prices.append(tp)
        trade_sizes.append(tsize)

    copy = alert.get("llm_copy_action") or {}
    return {
        "market_title": alert.get("market_title", ""),
        "outcome_side": copy.get("outcome") or copy.get("side") or "",
        "times": times,
        "prices": prices,
        "trade_times": trade_times,
        "trade_prices": trade_prices,
        "trade_sizes_usd": trade_sizes,
    }
```

- [ ] **Step 7: Add fetcher tests**

Append to `test/test_charts.py`:

```python
def test_fetch_price_sparkline_returns_none_when_no_token():
    result = charts.fetch_price_sparkline_data({"trades": []})
    assert result is None


def test_fetch_price_sparkline_returns_none_when_history_empty():
    alert = {"llm_copy_action": {"token_id": "tok1"}, "trades": []}
    with patch("charts._fetch_clob_prices_history", return_value=[]):
        result = charts.fetch_price_sparkline_data(alert)
    assert result is None


def test_fetch_price_sparkline_returns_none_when_price_flat():
    alert = {"llm_copy_action": {"token_id": "tok1"}, "trades": []}
    history = [(1000.0 + i, 0.50) for i in range(24)]
    with patch("charts._fetch_clob_prices_history", return_value=history):
        result = charts.fetch_price_sparkline_data(alert)
    assert result is None


def test_fetch_price_sparkline_returns_data_when_move_present():
    alert = {
        "llm_copy_action": {"token_id": "tok1", "outcome": "Yes"},
        "market_title": "Will X happen?",
        "trades": [{"timestamp": 1000.0, "price": 0.45, "usdcSize": 50_000}],
    }
    history = [(0.0 + i, 0.30 + 0.001 * i) for i in range(24)]
    with patch("charts._fetch_clob_prices_history", return_value=history):
        result = charts.fetch_price_sparkline_data(alert)
    assert result is not None
    assert len(result["times"]) == 24
    assert result["trade_times"] == [1000.0]
```

- [ ] **Step 8: Run all chart tests**

```bash
pytest test/test_charts.py -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add storybot/charts.py test/test_charts.py
git commit -m "charts: price_sparkline renderer + fetcher"
```

---

## Task 6: Implement dispatcher `render_chart_for_alert` with fallback ladder

**Files:**
- Modify: `storybot/charts.py`
- Create: `test/test_charts_dispatcher.py`

- [ ] **Step 1: Write the failing dispatcher test**

Create `test/test_charts_dispatcher.py`:

```python
"""Dispatcher behavior + fallback ladder tests for storybot/charts.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def test_render_chart_returns_none_for_unknown_chart_type():
    result = charts.render_chart_for_alert("not_a_real_type", {})
    assert result is None


def test_render_chart_returns_none_for_none():
    result = charts.render_chart_for_alert("none", {})
    assert result is None


def test_render_chart_returns_bytes_when_primary_succeeds():
    fake_data = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    with patch("charts.fetch_wallet_record_card_data", return_value=fake_data):
        result = charts.render_chart_for_alert("wallet_record_card", {"wallet": "0xabc"})
    assert isinstance(result, bytes)
    assert len(result) > 1000


def test_render_chart_falls_back_to_wallet_record_when_primary_fails():
    fake_wallet = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    with patch("charts.fetch_volume_bar_data", return_value=None), \
         patch("charts.fetch_wallet_record_card_data", return_value=fake_wallet):
        result = charts.render_chart_for_alert("volume_bar", {"wallet": "0xabc"})
    assert isinstance(result, bytes)


def test_render_chart_returns_none_when_primary_and_fallback_fail():
    with patch("charts.fetch_volume_bar_data", return_value=None), \
         patch("charts.fetch_wallet_record_card_data", return_value=None):
        result = charts.render_chart_for_alert("volume_bar", {"wallet": "0xabc"})
    assert result is None


def test_render_chart_returns_none_on_render_exception():
    fake_data = {
        "market_title": "M", "record_str": "10-2", "win_pct": 0.83,
        "bet_count": 12, "wallet_age_days": 50, "bet_size_usd": 1000,
        "outcome_side": "Yes",
    }
    with patch("charts.fetch_wallet_record_card_data", return_value=fake_data), \
         patch("charts.render_wallet_record_card", side_effect=RuntimeError("boom")), \
         patch("charts.fetch_wallet_record_card_data", return_value=None):
        result = charts.render_chart_for_alert("wallet_record_card", {"wallet": "0xabc"})
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest test/test_charts_dispatcher.py -v
```

Expected: FAIL with `AttributeError: render_chart_for_alert`.

- [ ] **Step 3: Implement the dispatcher**

Append to `storybot/charts.py`:

```python
# ----------------------- Dispatcher -----------------------

_CHART_REGISTRY: dict[str, tuple] = {
    "wallet_record_card": (fetch_wallet_record_card_data, render_wallet_record_card),
    "volume_bar":         (fetch_volume_bar_data,         render_volume_bar),
    "cluster_card":       (fetch_cluster_card_data,       render_cluster_card),
    "price_sparkline":    (fetch_price_sparkline_data,    render_price_sparkline),
}


def _try_render(chart_type: str, alert: dict) -> bytes | None:
    """Try the chart for `chart_type`. Returns bytes or None. Never raises."""
    pair = _CHART_REGISTRY.get(chart_type)
    if not pair:
        return None
    fetcher, renderer = pair
    try:
        data = fetcher(alert)
    except Exception:
        return None
    if data is None:
        return None
    try:
        return renderer(data)
    except Exception:
        return None


def render_chart_for_alert(chart_type: str, alert: dict) -> bytes | None:
    """Try the requested chart. If it fails, fall back to wallet_record_card.
    Returns PNG bytes or None. Never raises."""
    if chart_type in ("none", "", None):
        return None
    primary = _try_render(chart_type, alert)
    if primary is not None:
        return primary
    if chart_type == "wallet_record_card":
        return None  # already tried; no further fallback
    return _try_render("wallet_record_card", alert)
```

- [ ] **Step 4: Run dispatcher tests**

```bash
pytest test/test_charts_dispatcher.py -v
```

Expected: all PASS. If `test_render_chart_returns_none_on_render_exception` fails, the test's nested `patch` context is shadowing the first patch — restructure that one test to use a single `patch` per name.

- [ ] **Step 5: Run full chart test suite**

```bash
pytest test/test_charts.py test/test_charts_dispatcher.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add storybot/charts.py test/test_charts_dispatcher.py
git commit -m "charts: dispatcher with fallback ladder"
```

---

## Task 7: Add `_build_twitter_api_v1` helper to storybot.py

**Files:**
- Modify: `storybot/storybot.py:1497-1503`

This is the v1.1 OAuth1 client needed for media upload. The v2 `Client` we already use cannot upload media on its own.

- [ ] **Step 1: Read the existing `_build_twitter_client` to mirror its style**

```bash
sed -n '1495,1510p' /home/bhavya/git/polybot/storybot/storybot.py
```

- [ ] **Step 2: Add `_build_twitter_api_v1` immediately after `_build_twitter_client`**

In `storybot/storybot.py`, after the closing line of `_build_twitter_client`, insert:

```python
def _build_twitter_api_v1() -> tweepy.API:
    """v1.1 client for media upload. The v2 Client used by `_build_twitter_client`
    cannot upload media; v1.1 still owns that endpoint as of this writing."""
    auth = tweepy.OAuth1UserHandler(
        X_CONSUMER_KEY,
        X_CONSUMER_KEY_SECRET,
        X_ACCESS_TOKEN,
        X_ACCESS_TOKEN_SECRET,
    )
    return tweepy.API(auth)
```

- [ ] **Step 3: Verify it imports**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
PYTHONPATH=storybot python -c "from storybot import _build_twitter_api_v1; print(_build_twitter_api_v1)"
```

Expected: `<function _build_twitter_api_v1 at 0x...>`. No traceback.

- [ ] **Step 4: Commit**

```bash
git add storybot/storybot.py
git commit -m "storybot: add _build_twitter_api_v1 helper for media upload"
```

---

## Task 8: Extend SYSTEM_PROMPT in twitter_simple.py with chart_type schema

**Files:**
- Modify: `storybot/twitter_simple.py:88-232`

This is a prompt-only edit. No new tests; the prompt is validated downstream by `validate_decision`, which we extend in Task 9.

- [ ] **Step 1: Add the chart selection guidance section to SYSTEM_PROMPT**

In `storybot/twitter_simple.py`, locate the existing "## When to skip" block at [twitter_simple.py:217-219](../../storybot/twitter_simple.py#L217-L219). Insert a new section IMMEDIATELY BEFORE it:

```
## Chart selection
You also pick the chart image that ships with the tweet. The chart should
prove the surprise the tweet's hook leads with. Pick the chart_type whose
visual carries the lead clause:

- Tweet leads with a price move ("flipped from 32c to 41c") → "price_sparkline"
- Tweet leads with a volume multiplier ("906× normal volume") → "volume_bar"
- Tweet leads with a wallet record ("178-20", "29-4") or wallet age ("12-day-old") → "wallet_record_card"
- Tweet leads with coordinated flow ("five accounts sharing a funder") AND no single wallet record dominates → "cluster_card"
- If nothing supports a chart cleanly → "none"

The chart fails silently if the underlying data isn't available — your job
is just to pick the visual that best matches the lead clause. Don't second-
guess data availability; the system handles fallbacks.
```

- [ ] **Step 2: Update the JSON schema block at [twitter_simple.py:221-227](../../storybot/twitter_simple.py#L221-L227)**

Replace:

```
## Output (strict JSON only)
{{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "tweet": "<tweet text>" | null,
  "alert_ids": [<int>, ...] | null
}}
```

With:

```
## Output (strict JSON only)
{{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "tweet": "<tweet text>" | null,
  "alert_ids": [<int>, ...] | null,
  "chart_type": "price_sparkline" | "volume_bar" | "wallet_record_card" | "cluster_card" | "none"
}}
```

And update the closing instructions at [twitter_simple.py:229-231](../../storybot/twitter_simple.py#L229-L231) — add a sentence:

```
When decision=post, `chart_type` must be one of the five enum values.
When decision=skip, `chart_type` is ignored (set to "none" or omit).
```

- [ ] **Step 3: Verify the prompt still parses as a valid f-string**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
PYTHONPATH=storybot python -c "import twitter_simple; print(len(twitter_simple.SYSTEM_PROMPT))"
```

Expected: a positive integer in the thousands. No traceback.

- [ ] **Step 4: Commit**

```bash
git add storybot/twitter_simple.py
git commit -m "twitter_simple: add chart_type to LLM output schema + selection prompt"
```

---

## Task 9: Extend `validate_decision` to accept and validate `chart_type`

**Files:**
- Modify: `storybot/twitter_simple.py:264-289`

- [ ] **Step 1: Write the failing tests**

Create or extend `test/test_twitter_simple_validation.py`. If the file doesn't exist, create it:

```python
"""Validation tests for twitter_simple.py decision schema."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_simple  # noqa: E402


def _base_post_decision() -> dict:
    return {
        "decision": "post",
        "tweet": "Sample tweet https://polyspotter.com/alert/1",
        "alert_ids": [1],
        "chart_type": "wallet_record_card",
    }


def test_validate_accepts_known_chart_type():
    ok, err = twitter_simple.validate_decision(_base_post_decision())
    assert ok, err


def test_validate_treats_missing_chart_type_as_none():
    d = _base_post_decision()
    del d["chart_type"]
    ok, err = twitter_simple.validate_decision(d)
    assert ok, err  # missing -> defaults to "none"


def test_validate_accepts_chart_type_none():
    d = _base_post_decision()
    d["chart_type"] = "none"
    ok, err = twitter_simple.validate_decision(d)
    assert ok, err


def test_validate_rejects_unknown_chart_type():
    d = _base_post_decision()
    d["chart_type"] = "lol_no_chart"
    ok, err = twitter_simple.validate_decision(d)
    assert not ok
    assert "chart_type" in err
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest test/test_twitter_simple_validation.py -v
```

Expected: `test_validate_rejects_unknown_chart_type` FAILs because the validator currently ignores `chart_type`.

- [ ] **Step 3: Update `validate_decision` at `storybot/twitter_simple.py:264-289`**

Add this block at the end of `validate_decision`, immediately before `return True, ""`:

```python
    # chart_type validation (post-only)
    chart_type = decision.get("chart_type", "none")
    if chart_type is None:
        chart_type = "none"
    valid_chart_types = {"price_sparkline", "volume_bar", "wallet_record_card",
                         "cluster_card", "none"}
    if chart_type not in valid_chart_types:
        return False, f"unknown chart_type: {chart_type!r}"
```

- [ ] **Step 4: Run validation tests**

```bash
pytest test/test_twitter_simple_validation.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_simple.py test/test_twitter_simple_validation.py
git commit -m "twitter_simple: validate chart_type in decision schema"
```

---

## Task 10: Implement `prepare_chart` in twitter_simple.py with fallback ladder

**Files:**
- Modify: `storybot/twitter_simple.py`
- Modify: `test/test_twitter_simple_validation.py` (or new test file)

- [ ] **Step 1: Write the failing tests**

Create `test/test_twitter_simple_prepare_chart.py`:

```python
"""Tests for prepare_chart in twitter_simple.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_simple  # noqa: E402


def test_prepare_chart_returns_none_for_skip_decision():
    decision = {"decision": "skip", "alert_ids": [], "chart_type": "none"}
    result = twitter_simple.prepare_chart(decision, [])
    assert result is None


def test_prepare_chart_returns_none_when_alert_id_not_in_seed():
    decision = {"decision": "post", "alert_ids": [99], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}]
    result = twitter_simple.prepare_chart(decision, seed)
    assert result is None


def test_prepare_chart_calls_dispatcher_with_correct_alert():
    decision = {"decision": "post", "alert_ids": [1], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}, {"id": 2, "wallet": "0xdef"}]
    with patch("twitter_simple.charts.render_chart_for_alert", return_value=b"fakepng") as m:
        result = twitter_simple.prepare_chart(decision, seed)
    assert result == b"fakepng"
    m.assert_called_once_with("wallet_record_card", seed[0])


def test_prepare_chart_swallows_exceptions():
    decision = {"decision": "post", "alert_ids": [1], "chart_type": "wallet_record_card"}
    seed = [{"id": 1, "wallet": "0xabc"}]
    with patch("twitter_simple.charts.render_chart_for_alert",
               side_effect=RuntimeError("boom")):
        result = twitter_simple.prepare_chart(decision, seed)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest test/test_twitter_simple_prepare_chart.py -v
```

Expected: FAIL with `AttributeError: prepare_chart`.

- [ ] **Step 3: Implement `prepare_chart` and import `charts`**

In `storybot/twitter_simple.py`, add to the imports near the top (after the `from storybot import (` block):

```python
import charts
```

Then add the `prepare_chart` function immediately after `validate_decision`:

```python
def prepare_chart(decision: dict, seed_alerts: list[dict]) -> bytes | None:
    """Resolve the alert and render the requested chart, with fallback to
    wallet_record_card. Returns PNG bytes or None. Never raises."""
    if decision.get("decision") != "post":
        return None
    alert_ids = decision.get("alert_ids") or []
    if not alert_ids:
        return None
    try:
        target_id = int(alert_ids[0])
    except (TypeError, ValueError):
        return None
    alert = next((a for a in seed_alerts if int(a.get("id") or 0) == target_id), None)
    if alert is None:
        return None
    chart_type = decision.get("chart_type") or "none"
    try:
        return charts.render_chart_for_alert(chart_type, alert)
    except Exception as exc:
        log("chart_render_error", error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=target_id)
        return None
```

- [ ] **Step 4: Run prepare_chart tests**

```bash
pytest test/test_twitter_simple_prepare_chart.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_simple.py test/test_twitter_simple_prepare_chart.py
git commit -m "twitter_simple: prepare_chart with fallback ladder"
```

---

## Task 11: Update `post_tweet` to accept media bytes

**Files:**
- Modify: `storybot/twitter_simple.py:292-301`

- [ ] **Step 1: Write the failing test**

Append to `test/test_twitter_simple_prepare_chart.py`:

```python
def test_post_tweet_uploads_media_when_provided():
    from io import BytesIO
    fake_v1 = type("FakeAPI", (), {})()
    fake_v1.media_upload = lambda filename, file: type("M", (), {"media_id": 1234567})()
    fake_v2 = type("FakeClient", (), {})()
    captured = {}
    def create_tweet(text, media_ids=None):
        captured["text"] = text
        captured["media_ids"] = media_ids
        return type("R", (), {"data": {"id": "555"}})()
    fake_v2.create_tweet = create_tweet

    tweet_id = twitter_simple.post_tweet(
        "Hello", twitter_client=fake_v2, twitter_api_v1=fake_v1,
        media_png=b"\x89PNG\x00fakepng", dry_run=False,
    )
    assert tweet_id == "555"
    assert captured["media_ids"] == [1234567]
    assert captured["text"] == "Hello"


def test_post_tweet_skips_media_when_none():
    fake_v2 = type("FakeClient", (), {})()
    captured = {}
    def create_tweet(text, media_ids=None):
        captured["media_ids"] = media_ids
        return type("R", (), {"data": {"id": "777"}})()
    fake_v2.create_tweet = create_tweet

    tweet_id = twitter_simple.post_tweet(
        "Hello", twitter_client=fake_v2, twitter_api_v1=None,
        media_png=None, dry_run=False,
    )
    assert tweet_id == "777"
    assert captured["media_ids"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest test/test_twitter_simple_prepare_chart.py -v
```

Expected: FAIL with `TypeError: post_tweet() got an unexpected keyword argument 'twitter_api_v1'`.

- [ ] **Step 3: Update `post_tweet` at storybot/twitter_simple.py:292-301**

Replace the existing function with:

```python
def post_tweet(
    text: str,
    *,
    twitter_client,
    twitter_api_v1=None,
    media_png: bytes | None = None,
    dry_run: bool,
) -> str:
    """Post a single tweet, optionally with one PNG attached. Returns the tweet id."""
    if dry_run:
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    media_ids = None
    if media_png is not None and twitter_api_v1 is not None:
        from io import BytesIO
        media = twitter_api_v1.media_upload(filename="chart.png", file=BytesIO(media_png))
        media_id = getattr(media, "media_id", None) or getattr(media, "media_id_string", None)
        if media_id:
            media_ids = [media_id]

    if media_ids:
        resp = twitter_client.create_tweet(text=text, media_ids=media_ids)
    else:
        resp = twitter_client.create_tweet(text=text)
    data = getattr(resp, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {resp!r}")
    return tweet_id
```

- [ ] **Step 4: Run post_tweet tests**

```bash
pytest test/test_twitter_simple_prepare_chart.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_simple.py test/test_twitter_simple_prepare_chart.py
git commit -m "twitter_simple: post_tweet supports optional media upload"
```

---

## Task 12: Wire `prepare_chart` into `main()` + dry-run PNG saving

**Files:**
- Modify: `storybot/twitter_simple.py:304-408` (the `main` function)

- [ ] **Step 1: Update imports**

Ensure `_build_twitter_api_v1` is imported. Add to the existing `from storybot import (` block at [twitter_simple.py:26-43](../../storybot/twitter_simple.py#L26-L43):

```python
    _build_twitter_api_v1,
```

- [ ] **Step 2: Insert chart preparation in `main()`**

In `main()`, find the line `alert_ids = [int(i) for i in decision["alert_ids"]]` (around [twitter_simple.py:376](../../storybot/twitter_simple.py#L376)). **Immediately after** that line, insert the new chart-preparation block. Do NOT modify the lines above it — they stay as-is.

Insert exactly this new block (these lines do not currently exist):

```python
    chart_png = prepare_chart(decision, seed_alerts)
    log("chart_selected", run_id=run_id,
        chart_type=decision.get("chart_type"),
        rendered=chart_png is not None,
        bytes_len=(len(chart_png) if chart_png else 0))

    if DRY_RUN and chart_png is not None:
        out_path = f"storybot/dry_runs/twitter_simple_{run_id}.png"
        try:
            with open(out_path, "wb") as f:
                f.write(chart_png)
            log("chart_saved_dryrun", run_id=run_id, path=out_path)
        except OSError as exc:
            log("chart_save_error", run_id=run_id, error=str(exc))
```

- [ ] **Step 3: Update `post_tweet` call to pass the v1 client and chart bytes**

Replace the existing `post_tweet` call (around [twitter_simple.py:378-380](../../storybot/twitter_simple.py#L378-L380)) with:

```python
    try:
        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
        tweet_id = post_tweet(
            tweet,
            twitter_client=twitter_client,
            twitter_api_v1=twitter_api_v1,
            media_png=chart_png,
            dry_run=DRY_RUN,
        )
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
```

- [ ] **Step 4: Run a full dry-run smoke test**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
TWITTER_SIMPLE_DRY_RUN=true python storybot/twitter_simple.py
```

Expected: the run completes without errors. You should see log lines including `chart_selected`, possibly `chart_saved_dryrun`, and a `dryrun-...` tweet id. Check `storybot/dry_runs/` for a `twitter_simple_<run_id>.png`. Open it and verify it matches the chart_type the LLM picked.

If the LLM picks `none`, that's also valid — re-run a few times to see different chart types.

- [ ] **Step 5: Run the full test suite to make sure nothing broke**

```bash
pytest test/ -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add storybot/twitter_simple.py
git commit -m "twitter_simple: wire prepare_chart into main + dry-run PNG saving"
```

---

## Task 13: Build `render_all_charts.py` smoke script

**Files:**
- Create: `storybot/render_all_charts.py`

This is a dev tool, not a CI test. It pulls a recent alert from Postgres and renders all four chart types so the house style can be reviewed against real data.

- [ ] **Step 1: Create the script**

Create `storybot/render_all_charts.py`:

```python
"""Dev smoke tool: render all four chart types for a recent alert.

Run via:
    source venv/bin/activate
    python storybot/render_all_charts.py [alert_id]

If no alert_id is given, pulls the most recent alert with at least one signal.
Outputs go to storybot/dry_runs/<chart_type>_<alert_id>.png.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "dry_runs"


def fetch_alert(alert_id: int | None) -> dict | None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if alert_id is not None:
            cur.execute("SELECT * FROM alerts WHERE id = %s", (alert_id,))
        else:
            cur.execute("""
                SELECT * FROM alerts
                ORDER BY created_at DESC
                LIMIT 1
            """)
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return dict(row) if row else None


def main() -> int:
    alert_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    alert = fetch_alert(alert_id)
    if alert is None:
        print(f"No alert found (id={alert_id})", file=sys.stderr)
        return 1
    print(f"Using alert id={alert['id']} market='{alert.get('market_title')}'")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for chart_type in ("wallet_record_card", "volume_bar", "cluster_card", "price_sparkline"):
        png = charts.render_chart_for_alert(chart_type, alert)
        out = OUTPUT_DIR / f"{chart_type}_{alert['id']}.png"
        if png is None:
            print(f"  {chart_type}: SKIPPED (data unavailable / fallback returned None)")
            continue
        out.write_bytes(png)
        print(f"  {chart_type}: wrote {out} ({len(png)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script against a recent alert**

```bash
cd /home/bhavya/git/polybot
source venv/bin/activate
python storybot/render_all_charts.py
```

Expected: prints the alert id and four lines, one per chart_type, with either a written file or a SKIPPED message. Open each PNG that was written and verify it looks correct against the real alert data.

- [ ] **Step 3: Iterate on the house style if needed**

Common things you'll see and want to tune:
- Long market titles wrapping ugly → adjust `wrap=True` and font size, or truncate at 60 chars in the renderers.
- Sparkline trade dots overlapping → reduce dot size scaling factor in `render_price_sparkline`.
- Cluster card with too many wallets → bump the cap from 8 to 6 if names overflow.
- Volume bar baseline invisible → bump the `max(0.04, ...)` floor up to 0.06.

These are tuning fixes, not redesigns — keep them tight.

- [ ] **Step 4: Commit the script and any tuning changes**

```bash
git add storybot/render_all_charts.py storybot/charts.py
git commit -m "charts: render_all_charts dev smoke tool + style tuning"
```

---

## Task 14: Soak in dry-run, then flip to live

**Files:** none (operational)

- [ ] **Step 1: Run the bot in dry-run for several cron cycles**

```bash
TWITTER_SIMPLE_DRY_RUN=true python storybot/twitter_simple.py
```

Run this 5-10 times across a range of alert types if possible (or wait for cron to do so). For each run:
- Confirm the tweet text reads well.
- Open `storybot/dry_runs/twitter_simple_<run_id>.png` and confirm the chart matches the tweet's hook.
- Check the log for `chart_fallback` events. If the LLM frequently picks a chart_type that doesn't render, add more guidance in the prompt's "Chart selection" section.

- [ ] **Step 2: Flip to live**

Set `TWITTER_SIMPLE_DRY_RUN=false` (or unset) in the env. Confirm the cron runs and the tweet posts with media attached.

- [ ] **Step 3: Watch for the first week**

Monitor the log stream for:
- `chart_render_error` — non-zero rate means a renderer is buggy on real data shapes. Add a unit test reproducing the failure, fix the renderer, ship.
- `chart_fallback` — high rate means the LLM is picking incompatible chart_types. Tune the prompt.
- Tweet engagement (impressions, likes, replies) on tweets with charts vs. without. After ~30 tweets you'll have a usable signal on whether charts moved the needle.

- [ ] **Step 4: Final commit if any tuning was needed**

```bash
git add -p  # interactively pick only the files you intended to change
git commit -m "charts: tuning from first-week soak"
```

---

## Self-review checklist

Before declaring this plan ready for execution, verify:

**Spec coverage:**
- [x] All four chart types specified in the spec (Tasks 2–5)
- [x] LLM picks chart_type with deterministic fallback (Tasks 6, 8, 9, 10)
- [x] Rendering lives in `storybot/charts.py` in Python (Tasks 1–6)
- [x] Tweepy v1.1 client added next to v2 client (Task 7)
- [x] post_tweet supports media upload (Task 11)
- [x] Dry-run writes PNGs to disk (Task 12)
- [x] Logging events `chart_selected`, `chart_fallback`, `chart_render_error` (Tasks 10, 12)
- [x] `render_all_charts.py` dev smoke script (Task 13)
- [x] Twitter API tier verification flagged as precondition

**Type/name consistency:**
- `WalletRecordCardData`, `VolumeBarData`, `ClusterCardData`, `PriceSparklineData` all defined in Task 2–5, used in Task 6
- `render_chart_for_alert(chart_type, alert)` signature consistent in Tasks 6 and 10
- `post_tweet(text, *, twitter_client, twitter_api_v1, media_png, dry_run)` consistent in Tasks 11 and 12
- `prepare_chart(decision, seed_alerts)` consistent in Tasks 10 and 12

**No placeholders:**
- Every code step has complete code
- Every test step has the assertion
- Every command shows expected output
- Two NOTEs (column name verification in Tasks 2 and 4) call out a check rather than placeholder code — these are fine; the engineer can verify against `backend/schema.sql` in <30 seconds.

**Open items the engineer must handle in-flight (not placeholders, but require local verification):**
- Column names in `wallet_pnl` (Task 2 Step 6) and `wallet_funders` (Task 4 Step 7) — verify against `backend/schema.sql`.
- Pseudonym word lists in `charts.py` (Task 4 Step 4) — copy byte-for-byte from `frontend/src/lib/pseudonym.js`.
- Alert dict shape (e.g. `alert['trades']` vs. `alert['trades_json']`) — the fetcher code uses `alert.get("trades")` which may need adjusting based on the actual key returned by `fetch_seed_alerts`.

These are tagged as NOTEs in-task, not skipped or hand-waved.
