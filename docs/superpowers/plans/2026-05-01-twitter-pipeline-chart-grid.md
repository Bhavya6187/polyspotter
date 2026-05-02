# Twitter Pipeline Chart Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-chart attachment on twitter_pipeline tweets with a hero+tiles grid (one full-size hero panel + 3 stat tiles) inside the same 1200×675 canvas, so each tweet's image carries multiple supporting facts at a glance.

**Architecture:** Extract drawing logic from each existing renderer in `storybot/charts.py` into `_draw_X(ax, data)` helpers (so the same code can be reused inside a sub-region of a shared figure). Add a new `storybot/chart_grid.py` module that owns tile selection (deterministic, from facts_bundle), tile rendering, and grid composition. Wire it into `storybot/tweet_utils.prepare_chart` and add a small `image_tiles` field to the writer payload.

**Tech Stack:** Python 3.13, matplotlib (Agg backend), psycopg2, sqlite3, requests, pytest.

---

## Reference: spec

`docs/superpowers/specs/2026-05-01-twitter-pipeline-chart-grid-design.md` — read it before starting; this plan implements that spec.

## Working directory

All commands assume cwd is the repo root (`/home/bhavya/git/polybot`). Activate the venv before running tests: `source venv/bin/activate`. The bot expects to be run from `storybot/` so test files use `sys.path.insert(0, .../storybot)` to import its modules.

---

## Task 1: Refactor `wallet_record_card` — extract `_draw`, drop cluster footer

**Files:**
- Modify: `storybot/charts.py` (TypedDict `WalletRecordCardData`, function `render_wallet_record_card`, function `fetch_wallet_record_card_data`)
- Modify: `test/test_charts.py` (delete cluster-context upgrade tests around line 150-205)

**Why:** The personal subtitle on the hero now shows the wallet's *own* stake, not the cluster total. The dedicated tiles (CLUSTER $, LINKED ACCOUNTS) carry the cluster fact. Removing the cluster_size upgrade and its TypedDict field eliminates the duplicate-fact bug before the grid even ships.

- [ ] **Step 1: Verify existing tests pass before any change**

```bash
source venv/bin/activate
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 2: Update `WalletRecordCardData` TypedDict and the renderer**

In `storybot/charts.py`, replace the existing `WalletRecordCardData` definition (around line 74) and `render_wallet_record_card` (around line 94) with:

```python
class WalletRecordCardData(TypedDict):
    market_title: str
    record_str: str          # e.g. "29-4"
    win_pct: float           # 0..1
    bet_count: int
    wallet_age_days: int | None
    bet_size_usd: float
    outcome_side: str        # "Yes" / "Arsenal" / etc.


def _draw_wallet_record_card(ax, data: WalletRecordCardData) -> None:
    """Draw the wallet record card into the given Axes. The Axes' figure
    determines output size — used for both standalone 1200×675 renders and
    the 720×675 hero region of the grid."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

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
    ax.add_patch(Rectangle((0.1, bar_y), 0.8 * data["win_pct"], bar_h,
                           color=ACCENT, transform=ax.transAxes))
    ax.add_patch(Rectangle((0.1 + 0.8 * data["win_pct"], bar_y),
                           0.8 * (1 - data["win_pct"]), bar_h,
                           color=LOSS, transform=ax.transAxes))

    # Personal subtitle: bet size + outcome side. Drop "on" when side missing.
    side = (data.get("outcome_side") or "").strip()
    bet_str = _format_usd(data["bet_size_usd"])
    footer = f"{bet_str} on {side}" if side else f"{bet_str} bet"
    ax.text(0.5, 0.10, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")


def render_wallet_record_card(data: WalletRecordCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_wallet_record_card(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 3: Simplify `fetch_wallet_record_card_data` — drop cluster-context upgrade**

In the same file, around line 232-244 and the return-dict near line 271-280, remove the cluster-context bet-size upgrade and the `cluster_size` field. The full cleaned return dict should be:

```python
    return {
        "market_title": alert.get("market_title", ""),
        "record_str": f"{wins}-{losses}",
        "win_pct": profile["win_rate"],
        "bet_count": int(total_bets),
        "wallet_age_days": wallet_age_days,
        "bet_size_usd": float(bet_size),
        "outcome_side": outcome_side,
    }
```

Delete the `cluster_size_for_footer` block (around lines 233-243):

```python
    # Cluster-context override: when the cluster total dwarfs this wallet's
    # individual stake AND the cluster has 2+ linked accounts, the footer
    # tells the cluster story instead of the individual stake.
    cluster_size_for_footer: int | None = None
    if cluster_context:
        cluster_total = float(cluster_context.get("cluster_total_usd") or 0.0)
        cluster_size = cluster_context.get("cluster_size")
        if (cluster_total > bet_size
                and isinstance(cluster_size, int) and cluster_size >= 2):
            bet_size = cluster_total
            cluster_size_for_footer = cluster_size
```

Keep the `cluster_context` parameter on the signature (callers still pass it, will be unused after this change but stable signature avoids ripple). Update the docstring to remove the cluster-upgrade paragraph.

- [ ] **Step 4: Delete now-obsolete tests in `test/test_charts.py`**

Find and delete the tests that exercise cluster-context upgrade behavior. Open `test/test_charts.py` and remove any test whose body references `cluster_total_usd` and `cluster_size` together (around line 150-205). Test names will include things like "cluster_context", "cluster_size", "linked accounts" — delete each as a whole test function.

Verify deletion was complete:

```bash
grep -n "cluster_total_usd\|cluster_size" test/test_charts.py
```
Expected: no output.

- [ ] **Step 5: Run tests; expect green**

```bash
pytest test/test_charts.py -v
```
Expected: PASS. Existing renderer tests (`test_wallet_record_card_renders_png_at_canvas_size`, etc.) still produce 1200×675 PNGs because `render_wallet_record_card` still creates a full-canvas figure.

- [ ] **Step 6: Commit**

```bash
git add storybot/charts.py test/test_charts.py
git commit -m "$(cat <<'EOF'
charts: extract _draw_wallet_record_card; drop cluster footer upgrade

Hero now always shows the wallet's personal stake. Cluster facts move to
tiles in the upcoming chart grid (CLUSTER $, LINKED ACCOUNTS).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Refactor `fresh_wallet_card` — extract `_draw`

**Files:**
- Modify: `storybot/charts.py` (function `render_fresh_wallet_card` around line 299)

**Why:** Same shape change as Task 1 (split drawing into `_draw_X(ax, data)` so the grid can reuse it). No behavior change — fresh_wallet_card already renders only personal info.

- [ ] **Step 1: Verify existing tests pass**

```bash
source venv/bin/activate
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 2: Refactor `render_fresh_wallet_card`**

Replace the existing `render_fresh_wallet_card` (around line 299) with:

```python
def _draw_fresh_wallet_card(ax, data: FreshWalletCardData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Top: market title in muted grey
    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    # Hero number: wallet age in days, big green
    days = data["wallet_age_days"]
    ax.text(0.5, 0.62, f"{days}", color=ACCENT, fontsize=140, ha="center",
            va="center", fontweight="bold")

    # Subtitle
    label = "DAY OLD ACCOUNT" if days == 1 else "DAYS OLD ACCOUNT"
    ax.text(0.5, 0.38, label, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")
    ax.text(0.5, 0.30, "on Polymarket", color=MUTED, fontsize=16,
            ha="center", va="center")

    # Footer: bet size + outcome side (drop "on" when side is missing)
    side = (data.get("outcome_side") or "").strip()
    bet_str = _format_usd(data["bet_size_usd"])
    footer = f"{bet_str} on {side}" if side else f"{bet_str} bet"
    ax.text(0.5, 0.12, footer, color=FG, fontsize=24, ha="center", va="center",
            fontweight="bold")


def render_fresh_wallet_card(data: FreshWalletCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_fresh_wallet_card(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 3: Run tests; expect green**

```bash
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add storybot/charts.py
git commit -m "$(cat <<'EOF'
charts: extract _draw_fresh_wallet_card

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Refactor `volume_bar` — extract `_draw`

**Files:**
- Modify: `storybot/charts.py` (function `render_volume_bar` around line 509)

**Why:** Same refactor pattern. No behavior change.

- [ ] **Step 1: Verify existing tests pass**

```bash
source venv/bin/activate
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 2: Refactor `render_volume_bar`**

Replace the existing function with:

```python
def _draw_volume_bar(ax, data: VolumeBarData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.text(0.5, 0.92, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    mult = data["multiplier"]
    mult_label = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    ax.text(0.5, 0.72, mult_label, color=ACCENT, fontsize=120, ha="center",
            va="center", fontweight="bold")
    ax.text(0.5, 0.55, "today's volume vs. 7-day average", color=FG, fontsize=20,
            ha="center", va="center")

    today = max(data["today_volume_usd"], 1.0)
    baseline = max(data["baseline_avg_usd"], 1.0)
    today_w = 0.8
    baseline_w = max(0.04, today_w * (baseline / today))

    ax.add_patch(Rectangle((0.1, 0.32), baseline_w, 0.04, color=MUTED,
                           transform=ax.transAxes))
    ax.text(0.1 + baseline_w + 0.02, 0.34,
            f"7-day daily avg: {_format_usd(baseline)}",
            color=MUTED, fontsize=14, ha="left", va="center")

    ax.add_patch(Rectangle((0.1, 0.20), today_w, 0.06, color=ACCENT,
                           transform=ax.transAxes))
    ax.text(0.1 + today_w + 0.02, 0.23,
            f"today: {_format_usd(today)}",
            color=FG, fontsize=16, ha="left", va="center", fontweight="bold")


def render_volume_bar(data: VolumeBarData) -> bytes:
    fig, ax = _new_figure()
    _draw_volume_bar(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 3: Run tests; expect green**

```bash
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add storybot/charts.py
git commit -m "$(cat <<'EOF'
charts: extract _draw_volume_bar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Refactor `cluster_card` — extract `_draw`

**Files:**
- Modify: `storybot/charts.py` (function `render_cluster_card` around line 675)

**Why:** Same refactor pattern. No behavior change.

- [ ] **Step 1: Verify existing tests pass**

```bash
source venv/bin/activate
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 2: Refactor `render_cluster_card`**

Replace the existing function with:

```python
def _draw_cluster_card(ax, data: ClusterCardData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.text(0.5, 0.93, data["market_title"], color=MUTED, fontsize=18,
            ha="center", va="top", wrap=True)

    wallets = data["wallet_sizes"][:8]
    if not wallets:
        return
    max_size = max(w[1] for w in wallets) or 1.0
    bar_top = 0.78
    bar_h = 0.06
    spacing = 0.02
    for i, (name, size_usd) in enumerate(wallets):
        y = bar_top - i * (bar_h + spacing)
        w = 0.6 * (size_usd / max_size)
        ax.add_patch(Rectangle((0.1, y), w, bar_h, color=ACCENT,
                               transform=ax.transAxes))
        ax.text(0.09, y + bar_h / 2, name, color=FG, fontsize=14,
                ha="right", va="center")
        ax.text(0.1 + w + 0.01, y + bar_h / 2, _format_usd(size_usd),
                color=FG, fontsize=14, ha="left", va="center")

    side = (data.get("outcome_side") or "").strip()
    total_fmt = _format_usd(data["total_usd"])
    total_str = f"{total_fmt} on {side}" if side else f"{total_fmt} total"
    ax.text(0.5, 0.16, total_str, color=ACCENT, fontsize=28, ha="center",
            va="center", fontweight="bold")
    if data["shared_funder"]:
        funder = data["shared_funder"]
        funder_disp = funder[:6] + "…" + funder[-4:] if len(funder) > 12 else funder
        ax.text(0.5, 0.08, f"Shared funder: {funder_disp}", color=MUTED,
                fontsize=14, ha="center", va="center")


def render_cluster_card(data: ClusterCardData) -> bytes:
    fig, ax = _new_figure()
    _draw_cluster_card(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 3: Run tests; expect green**

```bash
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add storybot/charts.py
git commit -m "$(cat <<'EOF'
charts: extract _draw_cluster_card

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Refactor `price_sparkline` — extract `_draw`

**Files:**
- Modify: `storybot/charts.py` (function `render_price_sparkline` around line 987)

**Why:** Same refactor. price_sparkline is the only renderer that uses `fig.suptitle` (which lives on the figure, not the axes); inside the grid it has no figure of its own, so the suptitle becomes an `ax.text` call at the top of the axes.

- [ ] **Step 1: Verify existing tests pass**

```bash
source venv/bin/activate
pytest test/test_charts.py -v
```
Expected: PASS.

- [ ] **Step 2: Refactor `render_price_sparkline`**

Replace the existing function with:

```python
def _draw_price_sparkline(ax, data: PriceSparklineData) -> None:
    times = list(data["times"])
    prices = list(data["prices"])
    if len(times) < 2 or len(times) != len(prices):
        # Defensive — fetcher should have rejected this case.
        return

    # Title (drop the dash when side is missing). Place above the plot
    # using ax-relative text (replaces the prior fig.suptitle so this
    # works inside a sub-region of a shared figure).
    side = (data.get("outcome_side") or "").strip()
    title = f"{data['market_title']} — {side}" if side else data["market_title"]
    ax.set_title(title, color=MUTED, fontsize=18, pad=14)

    ax.plot(times, prices, color=ACCENT, linewidth=3)
    if data["trade_times"]:
        sizes = list(data["trade_sizes_usd"]) or [10_000] * len(data["trade_times"])
        scaled = [min(60 + s / 800, 240) for s in sizes]
        ax.scatter(list(data["trade_times"]), list(data["trade_prices"]),
                   s=scaled, color=FG, edgecolor=ACCENT, linewidth=2, zorder=5)

    pmin, pmax = min(prices), max(prices)
    pad = max((pmax - pmin) * 0.15, 0.01)
    ax.set_ylim(max(0, pmin - pad), min(1, pmax + pad))

    ax.set_yticks([prices[0], prices[-1]])
    ax.set_yticklabels(
        [f"{int(prices[0]*100)}c", f"{int(prices[-1]*100)}c"],
        color=FG, fontsize=14,
    )
    ax.set_xticks([times[0], times[-1]])
    ax.set_xticklabels(
        ["24h ago", "now"], color=MUTED, fontsize=12,
    )


def render_price_sparkline(data: PriceSparklineData) -> bytes:
    fig, ax = _new_figure()
    _draw_price_sparkline(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 3: Run tests; expect green**

```bash
pytest test/test_charts.py -v
```
Expected: PASS. The standalone render now uses `ax.set_title` instead of `fig.suptitle`, but the PNG dims are unchanged.

- [ ] **Step 4: Commit**

```bash
git add storybot/charts.py
git commit -m "$(cat <<'EOF'
charts: extract _draw_price_sparkline

Replaces fig.suptitle with ax.set_title so the same draw helper works
inside a shared-figure sub-region.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add `volume_multiplier_x` to facts_bundle

**Files:**
- Modify: `storybot/twitter_pipeline.py` (function `fetch_data_bundle`, function `build_facts_bundle`)
- Modify: `test/test_twitter_pipeline_facts_bundle.py`

**Why:** The VOLUME × tile needs the same baseline-vs-today multiplier the volume_bar hero already computes. Pulling it into facts_bundle once at stage 2 means tile selection is a pure function over the bundle (no extra fetch when the tile is shown), and the `volume_bar` hero can read from the bundle too.

- [ ] **Step 1: Write the failing test**

Append to `test/test_twitter_pipeline_facts_bundle.py`:

```python
def test_volume_multiplier_x_set_when_volume_spike_and_baseline_known(monkeypatch):
    """When has_volume_spike is True, fetch_data_bundle enriches the bundle
    with volume_multiplier_x using gamma 24h volume / sqlite 7-day baseline."""
    import twitter_pipeline
    import charts

    # Stub the two fetchers volume_bar already uses.
    monkeypatch.setattr(charts, "_fetch_gamma_volume24hr",
                        lambda cid: 120_000.0)
    monkeypatch.setattr(charts, "_fetch_baseline_avg_volume",
                        lambda cid: 10_000.0)
    # Stub trade-fetch + token-fetch — irrelevant to this test.
    # fetch_data_bundle imports these locally, so a monkeypatch on the
    # tweet_utils module attribute is picked up on the next call.
    import tweet_utils
    monkeypatch.setattr(tweet_utils, "fetch_alert_trades", lambda aid: [])
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", lambda cid: {})

    chosen_alert = {
        "id": 1,
        "condition_id": "0xabc",
        "signals": [{"strategy": "pre_event_volume_spike", "headline": "x"}],
    }
    bundle = twitter_pipeline.fetch_data_bundle([1], [chosen_alert])
    fb = bundle["facts_bundle"]
    assert fb["has_volume_spike"] is True
    assert fb["volume_multiplier_x"] == pytest.approx(12.0)


def test_volume_multiplier_x_none_when_no_volume_spike():
    import twitter_pipeline
    bundle = twitter_pipeline.build_facts_bundle([], [])
    assert bundle["has_volume_spike"] is False
    assert bundle["volume_multiplier_x"] is None
```

Add `import pytest` at the top of the test file if not present.

- [ ] **Step 2: Run tests to verify failure**

```bash
source venv/bin/activate
pytest test/test_twitter_pipeline_facts_bundle.py -v
```
Expected: FAIL with `KeyError: 'volume_multiplier_x'` on `test_volume_multiplier_x_none_when_no_volume_spike`.

- [ ] **Step 3: Add `volume_multiplier_x` to `build_facts_bundle`**

In `storybot/twitter_pipeline.py`, find `build_facts_bundle` (around line 304) and update the return dict:

```python
def build_facts_bundle(chosen_alerts: list[dict], trades: list[dict]) -> dict:
    """Derive a small dict of facts for downstream LLM stages to quote precisely.

    All fields gracefully degrade to null/0 when underlying data is missing.
    Note: volume_multiplier_x is enriched in fetch_data_bundle (it requires
    a gamma + sqlite fetch); build_facts_bundle alone leaves it None.
    """
    total_usd = sum(float(t.get("usdcSize") or 0.0) for t in trades)
    return {
        "distinct_wallets": _distinct_wallets(trades),
        "total_usd": total_usd,
        "trade_count": len(trades),
        "time_span_minutes": _time_span_minutes(trades),
        "biggest_price_move": _biggest_price_move(trades),
        "peak_hour_volume_usd": _peak_hour_volume_usd(trades),
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts, trades),
        "has_fresh_wallet": _extract_fresh_wallet(chosen_alerts, trades),
        "cluster_size": _cluster_size(chosen_alerts),
        "has_volume_spike": _has_volume_spike(chosen_alerts),
        "minutes_to_resolution": _minutes_to_resolution(chosen_alerts),
        "volume_multiplier_x": None,
    }
```

- [ ] **Step 4: Enrich in `fetch_data_bundle`**

In the same file, in `fetch_data_bundle` (around line 819), after `facts_bundle = build_facts_bundle(...)` is built into the return dict, compute and inject the multiplier when warranted. Replace the existing `return { ... }` with:

```python
    facts_bundle = build_facts_bundle(chosen, trades)
    if facts_bundle["has_volume_spike"]:
        # Use the same fetchers volume_bar uses, on the cluster's primary
        # condition_id (first chosen alert that has one). One gamma call +
        # one sqlite read per tweet; cheap.
        import charts
        cid = next((a.get("condition_id") for a in chosen if a.get("condition_id")), None)
        if cid:
            try:
                today = charts._fetch_gamma_volume24hr(cid)
                baseline = charts._fetch_baseline_avg_volume(cid)
                if today > 0 and baseline and baseline > 0:
                    facts_bundle["volume_multiplier_x"] = today / baseline
            except Exception as exc:
                from bot_utils import log
                log("volume_multiplier_fetch_error",
                    error=f"{type(exc).__name__}: {exc}")

    return {
        "chosen_alerts": chosen,
        "trades": trades,
        "token_map": token_map,
        "facts_bundle": facts_bundle,
    }
```

- [ ] **Step 5: Run tests; expect green**

```bash
pytest test/test_twitter_pipeline_facts_bundle.py -v
```
Expected: PASS. The pre-existing `test_empty_inputs_produce_zeroed_bundle` still passes — `volume_multiplier_x` defaults to `None`, which is the expected zeroed shape.

If the test that monkeypatches `tweet_utils.fetch_alert_trades` errors on import path resolution, replace with the import path that matches how the existing tests in this file structure their imports (peek at the other tests in the file for reference).

- [ ] **Step 6: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_facts_bundle.py
git commit -m "$(cat <<'EOF'
twitter_pipeline: add volume_multiplier_x to facts_bundle

Computed at stage 2 when has_volume_spike. Used by the upcoming chart
grid's VOLUME × tile, and a future home for the volume_bar hero.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Create `chart_grid.py` — `TileSpec` + `select_tiles`

**Files:**
- Create: `storybot/chart_grid.py`
- Create: `test/test_chart_grid_select_tiles.py`

**Why:** Tile selection is pure-function over `facts_bundle` + hero_type. Putting it in its own module keeps `charts.py` from sprawling further past 1220 lines, and the unit-test surface is small and table-driven.

- [ ] **Step 1: Write the failing tests**

Create `test/test_chart_grid_select_tiles.py`:

```python
"""Unit tests for chart_grid.select_tiles — pure function over facts_bundle."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402


def _bundle(**overrides):
    """Default-zero bundle, overridable per test."""
    base = {
        "distinct_wallets": 0,
        "total_usd": 0.0,
        "trade_count": 0,
        "time_span_minutes": 0,
        "biggest_price_move": None,
        "peak_hour_volume_usd": None,
        "has_sharp_wallet": None,
        "has_fresh_wallet": None,
        "cluster_size": None,
        "has_volume_spike": False,
        "minutes_to_resolution": None,
        "volume_multiplier_x": None,
    }
    base.update(overrides)
    return base


def test_clock_wins_when_set():
    fb = _bundle(minutes_to_resolution=11, total_usd=50_000)
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert [t.kind for t in tiles][0] == "clock"


def test_dedup_sharp_record_when_hero_is_wallet_record_card():
    fb = _bundle(has_sharp_wallet={"record": "24-1", "win_pct": 0.96})
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert "sharp_record" not in [t.kind for t in tiles]


def test_dedup_cluster_tiles_when_hero_is_cluster_card():
    fb = _bundle(total_usd=200_000, cluster_size=7)
    tiles = chart_grid.select_tiles("cluster_card", fb)
    kinds = [t.kind for t in tiles]
    assert "cluster_total" not in kinds
    assert "linked_accounts" not in kinds


def test_dedup_volume_when_hero_is_volume_bar():
    fb = _bundle(has_volume_spike=True, volume_multiplier_x=12.0)
    tiles = chart_grid.select_tiles("volume_bar", fb)
    assert "volume_x" not in [t.kind for t in tiles]


def test_dedup_price_when_hero_is_price_sparkline():
    fb = _bundle(biggest_price_move={"from": 0.32, "to": 0.41})
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert "price_move" not in [t.kind for t in tiles]


def test_cluster_total_dropped_below_threshold():
    fb = _bundle(total_usd=10_000)  # below $25k
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    assert "cluster_total" not in [t.kind for t in tiles]


def test_price_move_dropped_below_threshold():
    fb = _bundle(biggest_price_move={"from": 0.50, "to": 0.51})  # 1c, < 3c
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert "price_move" not in [t.kind for t in tiles]


def test_priority_order_caps_at_three():
    """All eight tiles eligible — only the top 3 by priority should appear."""
    fb = _bundle(
        minutes_to_resolution=11,             # 1: clock
        total_usd=200_000,                    # 2: cluster_total
        has_volume_spike=True,                # 3: volume_x
        volume_multiplier_x=12.0,
        biggest_price_move={"from": 0.30, "to": 0.40},  # 4: price_move
        cluster_size=7,                       # 5: linked_accounts
        has_sharp_wallet={"record": "24-1"},  # 6: sharp_record
        has_fresh_wallet={"wallet": "0xa"},   # 7: fresh_wallet
        distinct_wallets=15,                  # 8: wallets
    )
    tiles = chart_grid.select_tiles("price_sparkline", fb)
    # price_sparkline hero suppresses price_move at slot 4, but slot 4 was
    # never going to fit anyway — top 3 are clock, cluster_total, volume_x.
    assert [t.kind for t in tiles] == ["clock", "cluster_total", "volume_x"]


def test_zero_eligible_returns_empty_list():
    fb = _bundle()
    tiles = chart_grid.select_tiles("wallet_record_card", fb)
    assert tiles == []
```

- [ ] **Step 2: Run tests to verify failure**

```bash
source venv/bin/activate
pytest test/test_chart_grid_select_tiles.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'chart_grid'`.

- [ ] **Step 3: Create `storybot/chart_grid.py`**

```python
"""Chart grid: tile selection, tile rendering, and grid composition.

The grid replaces the single chart attachment for twitter_pipeline.py.
Layout: hero panel (~720×675) on the left + 3 stat tiles (~480×225 each)
stacked on the right, all inside one 1200×675 figure.

Tile selection is deterministic, driven by facts_bundle. Hero choice
remains the LLM's job (twitter_pipeline.pick_chart). See
docs/superpowers/specs/2026-05-01-twitter-pipeline-chart-grid-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TileSpec:
    """Describes one stat tile to be drawn into the right column."""
    kind: str          # "clock" | "cluster_total" | ...
    big: str           # "11 MIN" / "$220K" / "12×" — large display value
    label: str         # "to tip" / "cluster flow" / "usual volume"
    accent: bool       # True → ACCENT (green); False → FG (white)


# ---------- thresholds ----------
CLUSTER_TOTAL_MIN_USD = 25_000
PRICE_MOVE_MIN_DELTA = 0.03
LINKED_ACCOUNTS_MIN = 3
WALLETS_FALLBACK_MIN = 5


# ---------- per-tile builders. Return TileSpec or None. ----------

def _tile_clock(fb: dict) -> TileSpec | None:
    m = fb.get("minutes_to_resolution")
    if m is None:
        return None
    if m < 720:
        return TileSpec("clock", f"{m} MIN", "to close/tip", accent=True)
    hours = m // 60
    return TileSpec("clock", f"{hours}h", "to close", accent=True)


def _tile_cluster_total(fb: dict, hero: str) -> TileSpec | None:
    if hero == "cluster_card":
        return None
    total = float(fb.get("total_usd") or 0.0)
    if total < CLUSTER_TOTAL_MIN_USD:
        return None
    return TileSpec("cluster_total", _fmt_usd_big(total), "cluster flow", accent=False)


def _tile_volume_x(fb: dict, hero: str) -> TileSpec | None:
    if hero == "volume_bar":
        return None
    if not fb.get("has_volume_spike"):
        return None
    mult = fb.get("volume_multiplier_x")
    if mult is None or mult <= 0:
        return None
    big = f"{mult:.0f}×" if mult >= 10 else f"{mult:.1f}×"
    return TileSpec("volume_x", big, "usual volume", accent=True)


def _tile_price_move(fb: dict, hero: str) -> TileSpec | None:
    if hero == "price_sparkline":
        return None
    move = fb.get("biggest_price_move")
    if not move:
        return None
    delta = abs(float(move["to"]) - float(move["from"]))
    if delta < PRICE_MOVE_MIN_DELTA:
        return None
    big = f"{int(round(float(move['from'])*100))}¢ → {int(round(float(move['to'])*100))}¢"
    return TileSpec("price_move", big, "price move", accent=float(move["to"]) >= float(move["from"]))


def _tile_linked_accounts(fb: dict, hero: str) -> TileSpec | None:
    if hero == "cluster_card":
        return None
    n = fb.get("cluster_size")
    if n is None or n < LINKED_ACCOUNTS_MIN:
        return None
    return TileSpec("linked_accounts", f"{n} wallets", "one funder", accent=False)


def _tile_sharp_record(fb: dict, hero: str) -> TileSpec | None:
    if hero == "wallet_record_card":
        return None
    sw = fb.get("has_sharp_wallet")
    if not sw:
        return None
    return TileSpec("sharp_record", str(sw.get("record") or ""),
                    "sharp wallet", accent=True)


def _tile_fresh_wallet(fb: dict, hero: str) -> TileSpec | None:
    if hero == "fresh_wallet_card":
        return None
    fw = fb.get("has_fresh_wallet")
    if not fw:
        return None
    days = fw.get("wallet_age_days")
    if days is None:
        return None
    return TileSpec("fresh_wallet", f"{days} DAY", "old account", accent=True)


def _tile_wallets(fb: dict) -> TileSpec | None:
    n = fb.get("distinct_wallets") or 0
    if n < WALLETS_FALLBACK_MIN:
        return None
    return TileSpec("wallets", f"{n}", "accounts on event", accent=False)


# ---------- public API ----------

def select_tiles(hero_type: str, facts_bundle: dict) -> list[TileSpec]:
    """Return up to 3 TileSpecs in priority order. Filters by per-tile
    threshold + hero-dedup; takes the first 3 that pass."""
    candidates = [
        _tile_clock(facts_bundle),
        _tile_cluster_total(facts_bundle, hero_type),
        _tile_volume_x(facts_bundle, hero_type),
        _tile_price_move(facts_bundle, hero_type),
        _tile_linked_accounts(facts_bundle, hero_type),
        _tile_sharp_record(facts_bundle, hero_type),
        _tile_fresh_wallet(facts_bundle, hero_type),
        _tile_wallets(facts_bundle),
    ]
    return [c for c in candidates if c is not None][:3]


# ---------- helpers ----------

def _fmt_usd_big(amount: float) -> str:
    """Same as charts._format_usd but caps the K-suffix to 0 decimals."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"
```

- [ ] **Step 4: Run tests; expect green**

```bash
pytest test/test_chart_grid_select_tiles.py -v
```
Expected: PASS, all 9 tests.

- [ ] **Step 5: Commit**

```bash
git add storybot/chart_grid.py test/test_chart_grid_select_tiles.py
git commit -m "$(cat <<'EOF'
chart_grid: add TileSpec + select_tiles

Pure-function tile selection driven by facts_bundle, with hero-dedup
baked into each tile's threshold check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add `_draw_tile` renderer

**Files:**
- Modify: `storybot/chart_grid.py` (add `_draw_tile`)
- Create: `test/test_chart_grid_draw_tile.py`

**Why:** Each stat tile is a giant number + label inside its own Axes. Same drawing primitives the renderers in `charts.py` use (`ax.text`, `Rectangle` for an accent line). Keeping it next to `select_tiles` is fine — same module, same concerns.

- [ ] **Step 1: Write the failing test**

Create `test/test_chart_grid_draw_tile.py`:

```python
"""Smoke tests for chart_grid._draw_tile and the standalone tile render."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402


def test_render_tile_produces_valid_png():
    """Standalone render of a single tile produces a 480×225 PNG."""
    spec = chart_grid.TileSpec("clock", "11 MIN", "to tip", accent=True)
    png = chart_grid.render_tile(spec)
    assert isinstance(png, bytes)
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (chart_grid.TILE_W_PX, chart_grid.TILE_H_PX)


def test_render_tile_handles_long_big_label():
    """Long big-label (e.g. price move "32¢ → 41¢") should still render."""
    spec = chart_grid.TileSpec("price_move", "32¢ → 41¢", "price move", accent=True)
    png = chart_grid.render_tile(spec)
    img = Image.open(BytesIO(png))
    assert img.size == (chart_grid.TILE_W_PX, chart_grid.TILE_H_PX)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
source venv/bin/activate
pytest test/test_chart_grid_draw_tile.py -v
```
Expected: FAIL with `AttributeError: module 'chart_grid' has no attribute 'render_tile'`.

- [ ] **Step 3: Add `_draw_tile` and `render_tile`**

Append to `storybot/chart_grid.py`:

```python
import matplotlib
matplotlib.use("Agg")
from io import BytesIO
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


# Same colors as charts.py — kept duplicated to avoid an import cycle.
_BG = "#0E1117"
_FG = "#FFFFFF"
_ACCENT = "#22C55E"
_MUTED = "#9CA3AF"

TILE_W_PX = 480
TILE_H_PX = 225
_DPI = 100


def _draw_tile(ax, spec: TileSpec) -> None:
    """Draw a stat tile into the given Axes. Two text rows (big number,
    label) and a 2px accent underline at the bottom."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor(_BG)
    for spine in ax.spines.values():
        spine.set_visible(False)

    big_color = _ACCENT if spec.accent else _FG
    # Auto-shrink the big text when it has more than ~6 chars (e.g. "32¢ → 41¢").
    big = spec.big
    fontsize_big = 80 if len(big) <= 6 else 56
    ax.text(0.5, 0.62, big, color=big_color, fontsize=fontsize_big,
            ha="center", va="center", fontweight="bold")

    ax.text(0.5, 0.28, spec.label, color=_MUTED, fontsize=22,
            ha="center", va="center")

    # Thin accent underline at the bottom — visual rhythm between tile rows.
    accent_color = _ACCENT if spec.accent else _MUTED
    ax.add_patch(Rectangle((0.20, 0.06), 0.60, 0.012,
                           color=accent_color, transform=ax.transAxes))


def render_tile(spec: TileSpec) -> bytes:
    """Standalone tile render at 480×225. Used for tests + render_all_charts."""
    fig = Figure(figsize=(TILE_W_PX / _DPI, TILE_H_PX / _DPI), dpi=_DPI)
    fig.patch.set_facecolor(_BG)
    ax = fig.add_subplot(111)
    _draw_tile(ax, spec)
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests; expect green**

```bash
pytest test/test_chart_grid_draw_tile.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/chart_grid.py test/test_chart_grid_draw_tile.py
git commit -m "$(cat <<'EOF'
chart_grid: add _draw_tile + standalone render_tile

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Add `compose_chart` — full grid composition

**Files:**
- Modify: `storybot/chart_grid.py` (add `compose_chart`)
- Create: `test/test_chart_grid_compose.py`

**Why:** The single function that bridges chart picker output, deterministic tile selection, and per-hero `_draw_X` into one PNG. Lives in `chart_grid.py` next to its dependencies.

- [ ] **Step 1: Write the failing test**

Create `test/test_chart_grid_compose.py`:

```python
"""Smoke tests for chart_grid.compose_chart — assembles hero + tiles into 1200×675."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import chart_grid  # noqa: E402
import charts  # noqa: E402


def _wallet_record_data():
    return {
        "market_title": "Lakers vs Rockets: O/U 206.5",
        "record_str": "24-1",
        "win_pct": 0.96,
        "bet_count": 25,
        "wallet_age_days": 412,
        "bet_size_usd": 7_000,
        "outcome_side": "Under",
    }


def test_compose_chart_produces_canvas_sized_png():
    fb = {
        "minutes_to_resolution": 214,
        "total_usd": 220_000,
        "cluster_size": 7,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.60, "to": 0.62},
        "has_sharp_wallet": {"record": "24-1"},
        "has_fresh_wallet": None,
        "distinct_wallets": 15,
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=_wallet_record_data()):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc", "market_title": "Lakers vs Rockets"},
            facts_bundle=fb,
            cluster_context={"cluster_total_usd": 220_000, "cluster_size": 7},
        )
    assert png is not None
    img = Image.open(BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_compose_chart_zero_tiles_falls_back_to_single_chart():
    """No tiles pass thresholds → fall back to the existing single-chart layout."""
    fb = {  # everything zeroed
        "minutes_to_resolution": None,
        "total_usd": 0,
        "cluster_size": None,
        "has_volume_spike": False,
        "volume_multiplier_x": None,
        "biggest_price_move": None,
        "has_sharp_wallet": None,
        "has_fresh_wallet": None,
        "distinct_wallets": 0,
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=_wallet_record_data()):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc"},
            facts_bundle=fb,
        )
    img = Image.open(BytesIO(png))
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)


def test_compose_chart_hero_fetch_returns_none_returns_none():
    fb = {"minutes_to_resolution": 11, "total_usd": 200_000, "cluster_size": 7}
    with patch.object(charts, "fetch_wallet_record_card_data", return_value=None):
        png = chart_grid.compose_chart(
            hero_type="wallet_record_card",
            alert={"id": 1, "wallet": "0xabc"},
            facts_bundle=fb,
        )
    assert png is None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
source venv/bin/activate
pytest test/test_chart_grid_compose.py -v
```
Expected: FAIL with `AttributeError: module 'chart_grid' has no attribute 'compose_chart'`.

- [ ] **Step 3: Add `compose_chart` to `storybot/chart_grid.py`**

Append:

```python
HERO_W_PX = 720
CANVAS_W_PX = 1200
CANVAS_H_PX = 675

# Hero-type → (fetcher, _draw helper) inside charts.py. Mirror of
# charts._CHART_REGISTRY but with the _draw helpers from this refactor.
def _hero_registry():
    import charts
    return {
        "wallet_record_card": (charts.fetch_wallet_record_card_data,
                               charts._draw_wallet_record_card),
        "fresh_wallet_card":  (charts.fetch_fresh_wallet_card_data,
                               charts._draw_fresh_wallet_card),
        "volume_bar":         (charts.fetch_volume_bar_data,
                               charts._draw_volume_bar),
        "cluster_card":       (charts.fetch_cluster_card_data,
                               charts._draw_cluster_card),
        "price_sparkline":    (charts.fetch_price_sparkline_data,
                               charts._draw_price_sparkline),
    }


def compose_chart(*, hero_type: str, alert: dict, facts_bundle: dict,
                  cluster_context: dict | None = None,
                  params: dict | None = None) -> bytes | None:
    """Assemble hero + 3 stat tiles into a 1200×675 PNG.

    Returns None when the hero fetcher returns None (caller falls back to
    "no chart attached"). When zero tiles pass thresholds, renders the
    hero across the full 1200×675 canvas (single-chart fallback).
    """
    registry = _hero_registry()
    pair = registry.get(hero_type)
    if pair is None:
        return None
    fetcher, draw_hero = pair

    try:
        if hero_type == "wallet_record_card":
            data = fetcher(alert, cluster_context=cluster_context, params=params)
        else:
            data = fetcher(alert, params=params)
    except Exception:
        return None
    if data is None:
        return None

    tiles = select_tiles(hero_type, facts_bundle)

    fig = Figure(figsize=(CANVAS_W_PX / _DPI, CANVAS_H_PX / _DPI), dpi=_DPI)
    fig.patch.set_facecolor(_BG)

    if not tiles:
        # Fallback: hero spans the full canvas (existing single-chart layout).
        ax_full = fig.add_axes((0, 0, 1, 1))
        try:
            draw_hero(ax_full, data)
        except Exception:
            return None
        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
        return buf.getvalue()

    # Hero region: left HERO_W_PX wide, full height.
    hero_w_frac = HERO_W_PX / CANVAS_W_PX
    ax_hero = fig.add_axes((0, 0, hero_w_frac, 1))
    try:
        draw_hero(ax_hero, data)
    except Exception:
        return None

    # Tile column: 3 vertically stacked regions on the right.
    col_x = hero_w_frac
    col_w = 1.0 - hero_w_frac
    n_slots = 3
    slot_h = 1.0 / n_slots
    for i, spec in enumerate(tiles):
        # Slot 0 is the TOP slot — figure y goes 0 (bottom) to 1 (top).
        y_bottom = 1.0 - (i + 1) * slot_h
        ax_tile = fig.add_axes((col_x, y_bottom, col_w, slot_h))
        _draw_tile(ax_tile, spec)

    # Dividers: thin MUTED lines between hero/tiles and between tile slots.
    # Use figure-level Line2D so they sit above the axes without being
    # clipped by axes spines.
    from matplotlib.lines import Line2D
    fig.add_artist(Line2D([hero_w_frac, hero_w_frac], [0, 1],
                          color=_MUTED, linewidth=1, alpha=0.3))
    for i in range(1, n_slots):
        y = 1.0 - i * slot_h
        fig.add_artist(Line2D([hero_w_frac, 1.0], [y, y],
                              color=_MUTED, linewidth=1, alpha=0.3))

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=_BG, dpi=_DPI)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests; expect green**

```bash
pytest test/test_chart_grid_compose.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add storybot/chart_grid.py test/test_chart_grid_compose.py
git commit -m "$(cat <<'EOF'
chart_grid: add compose_chart (hero + 3 tiles, single matplotlib figure)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Wire `compose_chart` into `tweet_utils.prepare_chart`

**Files:**
- Modify: `storybot/tweet_utils.py` (function `prepare_chart` around line 240)
- Modify: `storybot/twitter_pipeline.py` (the `prepare_chart(...)` call site around line 1035)

**Why:** This is the integration point. After this task, twitter_pipeline ships grid images instead of single charts. articlebot continues to use `charts.render_chart_for_alert` directly (untouched), so its single-chart workflow is unaffected.

- [ ] **Step 1: Verify the existing tests still pass before edit**

```bash
source venv/bin/activate
pytest test/test_twitter_simple_prepare_chart.py -v
```
Expected: PASS. (These tests exercise the existing single-chart code path; they continue to live alongside the new path because articlebot still uses the single-chart path.)

- [ ] **Step 2: Add a new entry point `prepare_chart_grid`**

In `storybot/tweet_utils.py`, find `prepare_chart` (around line 240). Leave it untouched (articlebot still calls it). Append a new function below it:

```python
def prepare_chart_grid(chart_type: str, alert: dict, *,
                       facts_bundle: dict,
                       cluster_context: dict | None = None) -> bytes | None:
    """Render a hero+tiles grid for one alert. Returns PNG bytes or None.
    Never raises.

    Used by twitter_pipeline. articlebot continues to call prepare_chart
    (single-chart) until/unless we choose to migrate it later.
    """
    if not alert:
        return None
    enrich_alert_for_charts(alert)
    try:
        import chart_grid
        return chart_grid.compose_chart(
            hero_type=chart_type,
            alert=alert,
            facts_bundle=facts_bundle,
            cluster_context=cluster_context,
        )
    except Exception as exc:
        log("chart_grid_render_error",
            error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=alert.get("id"))
        return None
```

- [ ] **Step 3: Switch `twitter_pipeline.main` to the grid path**

In `storybot/twitter_pipeline.py`, find the `prepare_chart` call site near line 1035. Change the import and call:

```python
    from tweet_utils import (
        _build_twitter_api_v1, _build_twitter_client,
        filter_posted_alerts, post_tweet, prepare_chart_grid, record_tweet,
        strip_polyspotter_url,
    )
```

(replace `prepare_chart` with `prepare_chart_grid` in the import).

Then update the call site (around line 1035):

```python
    chart_png = (prepare_chart_grid(chart_pick["chart_type"], target_alert,
                                    facts_bundle=bundle["facts_bundle"],
                                    cluster_context=cluster_context)
                 if target_alert else None)
```

- [ ] **Step 4: Add an integration test**

Create `test/test_twitter_pipeline_grid.py`:

```python
"""End-to-end test: prepare_chart_grid composes a 1200x675 PNG."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402
import tweet_utils  # noqa: E402


def test_prepare_chart_grid_returns_canvas_sized_png():
    alert = {"id": 1, "wallet": "0xabc", "market_title": "Lakers vs Rockets",
             "total_usd": 7_000}
    facts_bundle = {
        "minutes_to_resolution": 214,
        "total_usd": 220_000,
        "cluster_size": 7,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.60, "to": 0.62},
        "has_sharp_wallet": {"record": "24-1"},
        "has_fresh_wallet": None,
        "distinct_wallets": 15,
    }
    fake_data = {
        "market_title": "Lakers vs Rockets: O/U 206.5",
        "record_str": "24-1",
        "win_pct": 0.96,
        "bet_count": 25,
        "wallet_age_days": 412,
        "bet_size_usd": 7_000,
        "outcome_side": "Under",
    }
    with patch.object(charts, "fetch_wallet_record_card_data",
                      return_value=fake_data):
        png = tweet_utils.prepare_chart_grid(
            "wallet_record_card", alert, facts_bundle=facts_bundle,
            cluster_context={"cluster_total_usd": 220_000, "cluster_size": 7},
        )
    assert png is not None
    img = Image.open(BytesIO(png))
    assert img.size == (charts.CANVAS_W_PX, charts.CANVAS_H_PX)
```

- [ ] **Step 5: Run tests; expect green**

```bash
pytest test/test_twitter_pipeline_grid.py test/test_twitter_simple_prepare_chart.py -v
```
Expected: PASS for both. The original prepare_chart tests still pass because that function is untouched.

- [ ] **Step 6: Commit**

```bash
git add storybot/tweet_utils.py storybot/twitter_pipeline.py test/test_twitter_pipeline_grid.py
git commit -m "$(cat <<'EOF'
twitter_pipeline: ship hero+tiles grid via prepare_chart_grid

twitter_pipeline.main now calls compose_chart through tweet_utils;
articlebot continues to call the single-chart prepare_chart unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Add `image_tiles` to writer payload + prompt addendum

**Files:**
- Modify: `storybot/twitter_pipeline.py` (function `_writer_user_message`, function `write_tweet`/`write_tweet_with_retry`, `SYSTEM_PROMPT_WRITER`, function `main`)

**Why:** The writer should know what tiles will appear in the image so it doesn't waste tweet characters listing the same facts. One-sentence prompt addition; minor payload change.

- [ ] **Step 1: Verify existing writer-validation tests pass**

```bash
source venv/bin/activate
pytest test/test_twitter_pipeline_validation.py -v
```
Expected: PASS.

- [ ] **Step 2: Add `image_tiles` to `_writer_user_message`**

In `storybot/twitter_pipeline.py`, find `_writer_user_message` (around line 708) and update its signature + body:

```python
def _writer_user_message(chosen_alerts: list[dict], event_summary: str,
                         bundle: dict, chart_pick: dict,
                         image_tiles: list[str] | None = None) -> str:
    from bot_utils import _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
        "chart_type": chart_pick.get("chart_type"),
        "hook_anchor": chart_pick.get("hook_anchor"),
        "image_tiles": image_tiles or [],
    }
    return json.dumps(payload, default=str, indent=2)
```

- [ ] **Step 3: Thread `image_tiles` through `write_tweet` and `write_tweet_with_retry`**

In the same file, update `write_tweet`'s signature + body (around line 722):

```python
def write_tweet(llm_client, chosen_alerts: list[dict], event_summary: str,
                bundle: dict, chart_pick: dict, *,
                image_tiles: list[str] | None = None,
                usage: dict | None = None,
                prior_error: str | None = None) -> dict:
    """Stage 4: compose the tweet. Caller invokes this twice if validation fails."""
    from bot_utils import MODEL, _accumulate_usage
    messages = [{"role": "system", "content": SYSTEM_PROMPT_WRITER}]
    user_payload = _writer_user_message(chosen_alerts, event_summary, bundle,
                                        chart_pick, image_tiles=image_tiles)
    if prior_error:
        user_payload = (
            f"Your previous tweet failed validation: {prior_error}. Regenerate.\n\n"
            + user_payload
        )
    messages.append({"role": "user", "content": user_payload})
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=1,
        max_completion_tokens=8000,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"tweet": "", "_parse_error": f"invalid JSON: {exc}"}
```

Update `write_tweet_with_retry`'s signature + body (around line 753):

```python
def write_tweet_with_retry(llm_client, chosen_alerts, event_summary, bundle,
                           chart_pick, *,
                           image_tiles: list[str] | None = None,
                           usage=None) -> tuple[dict, str | None, int]:
    """Run stage 4 once; on validation failure, retry once with the error fed back."""
    from bot_utils import log
    attempt = 1
    out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                      image_tiles=image_tiles, usage=usage)
    if out.get("_parse_error"):
        log("validation_retry", error=out["_parse_error"])
        attempt = 2
        out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                          image_tiles=image_tiles, usage=usage,
                          prior_error=out["_parse_error"])
        if out.get("_parse_error"):
            return out, out["_parse_error"], attempt
        ok, err = validate_tweet(out.get("tweet", ""))
        return (out, None, attempt) if ok else (out, err, attempt)

    ok, err = validate_tweet(out.get("tweet", ""))
    if ok:
        return out, None, attempt
    log("validation_retry", error=err)
    attempt = 2
    out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                      image_tiles=image_tiles, usage=usage, prior_error=err)
    if out.get("_parse_error"):
        return out, out["_parse_error"], attempt
    ok, err = validate_tweet(out.get("tweet", ""))
    return (out, None, attempt) if ok else (out, err, attempt)
```

- [ ] **Step 4: Add prompt addendum**

In `storybot/twitter_pipeline.py`, find `SYSTEM_PROMPT_WRITER` (around line 513). It's an f-string, so any literal `{` or `}` in the addendum must be doubled. Insert this paragraph just before the `## Audience` section header:

```
## Image grid
The chart shipped with this tweet is a grid: a hero panel (corresponding
to chart_type) plus up to 3 stat tiles drawn from {{CLOCK, CLUSTER $,
LINKED ACCOUNTS, VOLUME ×, PRICE MOVE, SHARP RECORD, FRESH WALLET}}. The
active tile list is in image_tiles. Don't waste tweet characters listing
tile facts unless they're load-bearing for the lede shape.
```

The literal `f"""..."""` string already uses `{{` `}}` for JSON brace examples lower down, so this pattern is consistent with the rest of the prompt. After f-string evaluation, the rendered prompt the LLM sees will have single braces.

- [ ] **Step 5: Wire `image_tiles` through `main`**

In `storybot/twitter_pipeline.py`, in `main` (around line 998), compute the tile-kind list before stage 4 and pass it through:

```python
    # Stage 4
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=4)
    import chart_grid
    image_tiles_kinds = [t.kind for t in chart_grid.select_tiles(
        chart_pick["chart_type"], bundle["facts_bundle"])]
    try:
        decision, err, attempts = write_tweet_with_retry(
            llm_client, bundle["chosen_alerts"], pick["event_summary"],
            bundle["facts_bundle"], chart_pick,
            image_tiles=image_tiles_kinds, usage=usage_totals)
```

(only the `import chart_grid`, the new `image_tiles_kinds = ...` line, and the new `image_tiles=image_tiles_kinds` arg are additions — the rest of the block is unchanged.)

- [ ] **Step 6: Update writer-validation tests where they call `write_tweet`/`_writer_user_message`**

```bash
grep -n "_writer_user_message\|write_tweet(" test/test_twitter_pipeline_validation.py
```

For any call site that doesn't pass `image_tiles`, it still works because the param is optional. No required updates unless a test asserts the payload's *exact* JSON shape. Run:

```bash
pytest test/test_twitter_pipeline_validation.py test/test_twitter_pipeline_pick_chart.py -v
```
Expected: PASS. If any test asserts the exact keys of the writer payload, update it to expect `image_tiles` as well.

- [ ] **Step 7: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_validation.py
git commit -m "$(cat <<'EOF'
twitter_pipeline: tell writer which tiles ship with the tweet

Adds image_tiles to the stage-4 payload + a one-paragraph addendum to
the writer system prompt: don't list tile facts that are already in the
image.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Extend `render_all_charts.py` with grid combinations

**Files:**
- Modify: `storybot/render_all_charts.py`

**Why:** Visual sanity-check before shipping. The script lets us preview the new grids next to the existing single charts so we can catch typography problems at a glance.

The existing script reads ONE alert from postgres (latest with a signal, or `python render_all_charts.py <alert_id>`) and renders every chart type against it. We add a parallel loop that calls `compose_chart` per hero type with a synthetic facts_bundle so the tile rendering is exercised.

- [ ] **Step 1: Append grid rendering to `storybot/render_all_charts.py`**

Inside `main`, after the existing `for chart_type in (...)` loop and before `return 0`, add:

```python
    # Grid renders — preview hero + 3 stat tiles for each hero type. Uses
    # a synthetic facts_bundle so tiles exercise their renderers regardless
    # of which signals fired on this specific alert.
    fb = {
        "minutes_to_resolution": 214,
        "total_usd": 220_000,
        "cluster_size": 7,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.60, "to": 0.62},
        "has_sharp_wallet": {"record": "24-1", "win_pct": 0.96,
                             "wallet": alert.get("wallet") or "0xabc",
                             "alert_id": alert["id"], "bet_usd": 7_000},
        "has_fresh_wallet": None,
        "distinct_wallets": 15,
        "trade_count": 30, "time_span_minutes": 129,
        "peak_hour_volume_usd": 140_000,
    }
    import chart_grid
    for hero_type in ("wallet_record_card", "fresh_wallet_card", "volume_bar",
                      "cluster_card", "price_sparkline"):
        png = chart_grid.compose_chart(
            hero_type=hero_type, alert=alert, facts_bundle=fb,
            cluster_context={"cluster_total_usd": fb["total_usd"],
                             "cluster_size": fb["cluster_size"]},
        )
        out = OUTPUT_DIR / f"grid_{hero_type}_{alert['id']}.png"
        if png is None:
            print(f"  grid_{hero_type}: SKIPPED (fetcher returned None)")
            continue
        out.write_bytes(png)
        print(f"  grid_{hero_type}: wrote {out} ({len(png)} bytes)")
```

- [ ] **Step 2: Run the script**

```bash
source venv/bin/activate
cd storybot && python render_all_charts.py
```
Expected: writes existing per-chart PNGs plus 5 new `grid_<hero>_<alert>.png` files into `storybot/dry_runs/`.

- [ ] **Step 3: Eyeball the output**

```bash
ls storybot/dry_runs/grid_*.png
```

Open one (or use Read on it). Confirm:
- 1200×675 dimensions.
- Hero on the left (looks the same as the standalone single chart, just narrower).
- Up to 3 stat tiles stacked on the right.
- Thin grey divider between hero column and tile column, and between tile rows.

If type sizing or spacing looks wrong, tweak `chart_grid._draw_tile`'s fontsize / y-coordinate constants and re-run.

- [ ] **Step 4: Commit**

```bash
git add storybot/render_all_charts.py
git commit -m "$(cat <<'EOF'
render_all_charts: preview the hero+tiles grid per hero type

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

Once all tasks are complete:

- [ ] **Run the full scanner test suite**

```bash
source venv/bin/activate
pytest -v
```
Expected: PASS.

- [ ] **Dry-run the pipeline end-to-end**

```bash
source venv/bin/activate
DRY_RUN=true python storybot/twitter_pipeline.py
```

Inspect `storybot/dry_runs/twitter_pipeline_<run_id>.png`. The image should be 1200×675 with hero on the left and 1–3 stat tiles stacked on the right. If only one tile shows up, that's expected for thin events; the grid-vs-fallback decision is data-driven.

- [ ] **Check the transcript**

```bash
cat storybot/dry_runs/twitter_pipeline_<run_id>.json | jq '.stages."4_writer".decision'
```

Confirm the tweet doesn't redundantly list facts already shown as tiles (e.g. if CLOCK tile is shown, the tweet shouldn't open with "With 11 minutes to tip" — though it MAY, if timing is the lede shape).

That's the full implementation. The grid ships gracefully degraded when data is thin (single-chart fallback), so a partial-data event still produces a valid tweet+image.
