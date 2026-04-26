# Twitter Pipeline Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new Twitter bot at `storybot/twitter_pipeline.py` that runs a 4-stage pipeline (3 LLM calls + 1 deterministic data fetch) instead of the single LLM call used by `storybot/twitter_simple.py`. Both bots coexist.

**Architecture:** Stage 1 LLM picks an event-cluster (or skips). Stage 2 (deterministic) fetches trades + Gamma tokens and derives a small `facts_bundle`. Stage 3 LLM picks a chart_type + hook_anchor. Stage 4 LLM writes the tweet, with one retry on validation failure. Reusable helpers (chart prep, dedup, posting) are extracted from `twitter_simple.py` into `tweet_utils.py` so both bots share them.

**Tech Stack:** Python 3.13, Azure OpenAI (gpt-5.4 via env), psycopg2 (Postgres), sqlite3 (`polybot.db`), tweepy, matplotlib (already wired into `charts.py`), pytest, `requests` for Gamma.

**Spec:** [docs/superpowers/specs/2026-04-26-twitter-pipeline-bot-design.md](../specs/2026-04-26-twitter-pipeline-bot-design.md)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `storybot/tweet_utils.py` | Modify | Hold all reusable Twitter mechanics: dedup, chart prep, posting, link strip. |
| `storybot/twitter_simple.py` | Modify | Drop helpers now in `tweet_utils`; import from there. No behavior change. |
| `storybot/twitter_pipeline.py` | Create | New 4-stage bot. Each stage is one function. `main()` orchestrates. |
| `test/test_twitter_simple_prepare_chart.py` | Modify | Update patch targets (`twitter_simple._fetch_alert_trades` → `tweet_utils.fetch_alert_trades`, etc.). |
| `test/test_twitter_pipeline_facts_bundle.py` | Create | Unit tests for the deterministic facts-bundle builder. |
| `test/test_twitter_pipeline_validation.py` | Create | Tests for `validate_tweet` + the writer-retry path. |

The new bot file (`twitter_pipeline.py`) holds three `SYSTEM_PROMPT_*` constants and four stage functions (`pick_event`, `fetch_data_bundle`, `pick_chart`, `write_tweet`) plus `main()`. Estimated ~450 LOC. If it grows past ~600, split the prompts into a `twitter_pipeline_prompts.py` sibling — but don't pre-empt.

---

## Task 1: Extract shared helpers from `twitter_simple.py` into `tweet_utils.py`

**Goal:** Refactor without changing runtime behavior. Both bots will import from `tweet_utils`.

**Files:**
- Modify: `storybot/tweet_utils.py`
- Modify: `storybot/twitter_simple.py`
- Modify: `test/test_twitter_simple_prepare_chart.py`

- [ ] **Step 1: Add the helpers to `tweet_utils.py` (renamed without leading underscore where they become public).**

Append to [storybot/tweet_utils.py](storybot/tweet_utils.py) (after `record_tweet`):

```python
import json
import re

import requests

from bot_utils import GAMMA_BASE_URL, log


# --- URL helpers -------------------------------------------------------------

_POLYSPOTTER_URL_STRIP_RE = re.compile(
    r"\s*https://polyspotter\.com/(?:market|wallet|alert|tag)/\S+"
)


def strip_polyspotter_url(tweet: str) -> str:
    """Remove polyspotter.com deep links (and any leading whitespace) before posting."""
    return _POLYSPOTTER_URL_STRIP_RE.sub("", tweet).rstrip()


# --- Dedup ------------------------------------------------------------------

def already_tweeted_ids(alert_ids: list[int]) -> set[int]:
    """Return the subset of alert_ids that already have a row in tweeted_alerts."""
    if not alert_ids:
        return set()
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            ([int(i) for i in alert_ids],),
        )
        rows = cur.fetchall()
        cur.close()
        return {int(r[0]) for r in rows}
    finally:
        conn.close()


def filter_posted_alerts(seed_alerts: list[dict]) -> list[dict]:
    """Drop seed alerts that have already been tweeted (by any bot)."""
    ids = [int(a["id"]) for a in seed_alerts if a.get("id") is not None]
    posted = already_tweeted_ids(ids)
    return [a for a in seed_alerts if int(a.get("id") or 0) not in posted]


# --- Chart prep -------------------------------------------------------------

def fetch_alert_trades(alert_id: int) -> list[dict]:
    """Fetch all trades for one alert from Postgres alert_trades, shaped like the Polymarket Data API."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wallet, outcome, side, usd_value, size, price,
                   EXTRACT(EPOCH FROM trade_timestamp) AS ts,
                   transaction_hash
            FROM alert_trades WHERE alert_id = %s
            """,
            (alert_id,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    out = []
    for w, oc, sd, usd, sz, pr, ts, txh in rows:
        out.append({
            "wallet": w,
            "outcome": oc,
            "side": sd,
            "usdcSize": float(usd) if usd is not None else 0.0,
            "size": float(sz) if sz is not None else 0.0,
            "price": float(pr) if pr is not None else 0.0,
            "timestamp": float(ts) if ts is not None else 0.0,
            "transaction_hash": txh,
        })
    return out


def fetch_market_tokens(condition_id: str) -> dict[str, str]:
    """Live Gamma fetch: return {outcome_name: token_id}. Empty dict on failure."""
    if not condition_id:
        return {}
    try:
        r = requests.get(
            f"{GAMMA_BASE_URL}/markets",
            params=[("condition_ids", condition_id)],
            timeout=QUERY_TIMEOUT_SECONDS * 2,
        )
        r.raise_for_status()
        markets = r.json()
        if not markets:
            return {}
        m = markets[0]
        outcomes = m.get("outcomes")
        token_ids = m.get("clobTokenIds")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if not (isinstance(outcomes, list) and isinstance(token_ids, list)):
            return {}
        return {o: t for o, t in zip(outcomes, token_ids) if o and t}
    except Exception as exc:
        log("market_tokens_fetch_error",
            condition_id=condition_id,
            error=f"{type(exc).__name__}: {exc}")
        return {}


def enrich_alert_for_charts(alert: dict) -> None:
    """Populate alert['trades'] and alert['token_id'] in-place. Failures are silent."""
    alert_id = alert.get("id")
    if alert_id is None:
        return
    try:
        alert["trades"] = fetch_alert_trades(int(alert_id))
    except Exception as exc:
        log("alert_trades_fetch_error",
            alert_id=alert_id, error=f"{type(exc).__name__}: {exc}")
        alert["trades"] = []

    cid = alert.get("condition_id")
    if not cid:
        return
    copy = alert.get("llm_copy_action") or {}
    if isinstance(copy, str):
        try:
            copy = json.loads(copy)
        except json.JSONDecodeError:
            copy = {}
    side = copy.get("outcome") or copy.get("side")
    if not side:
        return
    tokens = fetch_market_tokens(cid)
    if side in tokens:
        alert["token_id"] = tokens[side]


def prepare_chart(chart_type: str, alert: dict) -> bytes | None:
    """Render a chart for one alert. Returns PNG bytes or None. Never raises.

    Caller is responsible for resolving which alert + chart_type to render.
    """
    if not alert:
        return None
    enrich_alert_for_charts(alert)
    try:
        import charts  # local import to keep tweet_utils import-light at module load
        return charts.render_chart_for_alert(chart_type, alert)
    except Exception as exc:
        log("chart_render_error",
            error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=alert.get("id"))
        return None


# --- Posting ----------------------------------------------------------------

def post_tweet(
    text: str,
    *,
    twitter_client,
    twitter_api_v1=None,
    media_png: bytes | None = None,
    dry_run: bool,
) -> str:
    """Post a single tweet, optionally with one PNG attached. Returns the tweet id."""
    import uuid
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

Note the **API change**: in the old `twitter_simple.prepare_chart(decision, seed_alerts)`, the function took the whole decision dict and resolved the alert internally. In the new `tweet_utils.prepare_chart(chart_type, alert)`, the caller resolves the alert. This is a deliberate simplification — both bots will benefit, and `twitter_simple` already has `decision` and `seed_alerts` in scope so the resolution can move to its caller.

- [ ] **Step 2: Update `twitter_simple.py` to use the new helpers.**

In [storybot/twitter_simple.py](storybot/twitter_simple.py):

Replace the imports block (lines 27-50) with:
```python
from bot_utils import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    MODEL,
    QUERY_TIMEOUT_SECONDS,
    _accumulate_usage,
    _compact_alert_for_picker,
    fetch_seed_alerts,
    log,
)
from tweet_utils import (
    TWEET_MAX_CHARS,
    TWEET_URL_CHARS,
    _BANNED_TWEET_PHRASES,
    _POLYSPOTTER_URL_RE,
    _build_twitter_api_v1,
    _build_twitter_client,
    _tweet_length,
    enrich_alert_for_charts,
    fetch_alert_trades,
    fetch_market_tokens,
    filter_posted_alerts,
    post_tweet,
    prepare_chart as _render_alert_chart,
    record_tweet,
    strip_polyspotter_url,
)
```

Delete from `twitter_simple.py`:
- `_POLYSPOTTER_URL_STRIP_RE` and `_strip_polyspotter_url` (now in tweet_utils as `strip_polyspotter_url`)
- `_already_tweeted_ids` and `filter_posted_alerts` (now in tweet_utils)
- `_fetch_alert_trades`, `_fetch_market_tokens`, `enrich_alert_for_charts` (now in tweet_utils)
- `post_tweet` (now in tweet_utils)
- The old `prepare_chart` function (replaced — see next step)

Replace `prepare_chart` in twitter_simple with a thin wrapper that does the alert-resolution old code did:
```python
def prepare_chart(decision: dict, seed_alerts: list[dict]) -> bytes | None:
    """Resolve the alert from decision.alert_ids[0] and render the chart."""
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
    return _render_alert_chart(chart_type, alert)
```

Update `_strip_polyspotter_url(decision["tweet"])` call site to `strip_polyspotter_url(...)`.

- [ ] **Step 3: Update `test/test_twitter_simple_prepare_chart.py` patch targets.**

Replace patches that reference the old underscore names. Concretely:
- `patch("twitter_simple._fetch_alert_trades", ...)` → `patch("tweet_utils.fetch_alert_trades", ...)`
- `patch("twitter_simple._fetch_market_tokens", ...)` → `patch("tweet_utils.fetch_market_tokens", ...)`
- `patch("twitter_simple.enrich_alert_for_charts", ...)` → `patch("tweet_utils.enrich_alert_for_charts", ...)`
- `patch("twitter_simple.charts.render_chart_for_alert", ...)` → `patch("tweet_utils.charts.render_chart_for_alert", ...)` *for tests asserting through the new wrapper*; for tests that still call `twitter_simple.prepare_chart`, patch the wrapper's dependency — the cleanest is `patch("twitter_simple._render_alert_chart", ...)`.

For the `test_enrich_alert_*` and `test_post_tweet_*` tests: they should now call `tweet_utils.enrich_alert_for_charts` and `tweet_utils.post_tweet` directly. Update the imports at top:
```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_simple  # noqa: E402
import tweet_utils  # noqa: E402
```

And update each call site accordingly. (The behavior under test is unchanged.)

- [ ] **Step 4: Run the full test suite and confirm green.**

Run: `source venv/bin/activate && pytest test/ -q`
Expected: all tests pass (including all `test_twitter_simple_*` tests).

- [ ] **Step 5: Smoke-test `twitter_simple` in dry-run mode.**

Run: `source venv/bin/activate && TWITTER_SIMPLE_DRY_RUN=true python storybot/twitter_simple.py`
Expected: prints structured log lines, ends with `run_end` event. No tracebacks. Either skips (no story) or posts a dry-run tweet (id starts with `dryrun-`).

- [ ] **Step 6: Commit.**

```bash
git add storybot/tweet_utils.py storybot/twitter_simple.py test/test_twitter_simple_prepare_chart.py
git commit -m "Extract shared helpers from twitter_simple into tweet_utils

No behavior change. Both twitter_simple and the upcoming
twitter_pipeline bot will share these helpers."
```

---

## Task 2: Add the `facts_bundle` builder + tests

**Goal:** Implement the deterministic transform from `(chosen_alerts, trades) → facts_bundle`. Pure function, no I/O — testable in isolation.

**Files:**
- Create: `storybot/twitter_pipeline.py`
- Create: `test/test_twitter_pipeline_facts_bundle.py`

- [ ] **Step 1: Create the new bot file with just the facts-bundle builder.**

Create [storybot/twitter_pipeline.py](storybot/twitter_pipeline.py):

```python
"""
4-stage Twitter bot: event picker → deterministic data fetch → chart picker → writer.

Run via cron:
    python storybot/twitter_pipeline.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone


def _parse_iso(value) -> datetime | None:
    """Parse a Postgres-shaped timestamp into an aware datetime, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _extract_sharp_wallet(chosen_alerts: list[dict]) -> dict | None:
    """Try llm_copy_action first; fall back to wallet_pnl SQLite lookup if a
    win_rate_tracking signal exists but no record string is in the payload."""
    for a in chosen_alerts:
        copy = a.get("llm_copy_action") or {}
        if isinstance(copy, str):
            try:
                copy = json.loads(copy)
            except json.JSONDecodeError:
                copy = {}
        record = copy.get("wallet_record") or copy.get("record")
        win_pct = copy.get("win_pct") or copy.get("win_rate")
        if record and a.get("wallet"):
            return {
                "wallet": a["wallet"],
                "record": str(record),
                "win_pct": float(win_pct) if win_pct is not None else None,
            }

    # Fallback: any alert has a win_rate_tracking signal? Ask wallet_pnl.
    for a in chosen_alerts:
        signals = a.get("signals") or []
        if not any((s.get("strategy") == "win_rate_tracking") for s in signals):
            continue
        wallet = a.get("wallet")
        if not wallet:
            continue
        try:
            from bot_utils import query_sqlite
            rows = query_sqlite(
                f"SELECT wins, losses, win_rate FROM wallet_pnl "
                f"WHERE wallet = '{wallet}' LIMIT 1"
            )
        except Exception:
            rows = []
        if rows:
            r = rows[0]
            wins, losses = r.get("wins"), r.get("losses")
            wr = r.get("win_rate")
            if wins is not None and losses is not None:
                return {
                    "wallet": wallet,
                    "record": f"{wins}-{losses}",
                    "win_pct": float(wr) if wr is not None else None,
                }
    return None


def _cluster_size(chosen_alerts: list[dict]) -> int | None:
    """Largest cluster_size implied by wallet_clustering or concentrated_one_sided signals."""
    sizes = []
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") in ("wallet_clustering", "concentrated_one_sided"):
                # severity is roughly the cluster size for these strategies.
                sev = s.get("severity")
                if isinstance(sev, (int, float)) and sev > 0:
                    sizes.append(int(sev))
    return max(sizes) if sizes else None


def _has_volume_spike(chosen_alerts: list[dict]) -> bool:
    for a in chosen_alerts:
        for s in a.get("signals") or []:
            if s.get("strategy") == "pre_event_volume_spike":
                return True
    return False


def _minutes_to_resolution(chosen_alerts: list[dict]) -> int | None:
    """Smallest positive (resolution_time - now) in minutes, across chosen alerts."""
    now = datetime.now(timezone.utc)
    best = None
    for a in chosen_alerts:
        when = _parse_iso(a.get("game_start_time")) or _parse_iso(a.get("event_end_estimate"))
        if when is None:
            continue
        delta_min = int((when - now).total_seconds() // 60)
        if delta_min < 0:
            continue
        if best is None or delta_min < best:
            best = delta_min
    return best


def _dominant_outcome(trades: list[dict]) -> str | None:
    """Outcome with the largest USD share of the trades."""
    if not trades:
        return None
    totals: Counter = Counter()
    for t in trades:
        oc = t.get("outcome")
        if oc:
            totals[oc] += float(t.get("usdcSize") or 0.0)
    if not totals:
        return None
    return totals.most_common(1)[0][0]


def _biggest_price_move(trades: list[dict]) -> dict | None:
    """First→last price on the dominant outcome. None if <2 trades on that outcome."""
    outcome = _dominant_outcome(trades)
    if outcome is None:
        return None
    sub = [t for t in trades if t.get("outcome") == outcome and t.get("price") is not None]
    sub.sort(key=lambda t: float(t.get("timestamp") or 0.0))
    if len(sub) < 2:
        return None
    return {"from": float(sub[0]["price"]), "to": float(sub[-1]["price"])}


def _peak_hour_volume_usd(trades: list[dict]) -> float | None:
    """Max USD across rolling 60-minute windows. None if 0 trades."""
    if not trades:
        return None
    sorted_t = sorted(trades, key=lambda t: float(t.get("timestamp") or 0.0))
    best = 0.0
    left = 0
    running = 0.0
    for right in range(len(sorted_t)):
        running += float(sorted_t[right].get("usdcSize") or 0.0)
        while (float(sorted_t[right].get("timestamp") or 0.0)
               - float(sorted_t[left].get("timestamp") or 0.0)) > 3600:
            running -= float(sorted_t[left].get("usdcSize") or 0.0)
            left += 1
        if running > best:
            best = running
    return best if best > 0 else None


def _time_span_minutes(trades: list[dict]) -> int:
    if not trades:
        return 0
    times = [float(t.get("timestamp") or 0.0) for t in trades if t.get("timestamp")]
    if not times:
        return 0
    return int((max(times) - min(times)) // 60)


def _distinct_wallets(trades: list[dict]) -> int:
    return len({t.get("wallet") for t in trades if t.get("wallet")})


def build_facts_bundle(chosen_alerts: list[dict], trades: list[dict]) -> dict:
    """Derive a small dict of facts for downstream LLM stages to quote precisely.

    All fields gracefully degrade to null/0 when underlying data is missing.
    """
    total_usd = sum(float(t.get("usdcSize") or 0.0) for t in trades)
    return {
        "distinct_wallets": _distinct_wallets(trades),
        "total_usd": total_usd,
        "trade_count": len(trades),
        "time_span_minutes": _time_span_minutes(trades),
        "biggest_price_move": _biggest_price_move(trades),
        "peak_hour_volume_usd": _peak_hour_volume_usd(trades),
        "has_sharp_wallet": _extract_sharp_wallet(chosen_alerts),
        "cluster_size": _cluster_size(chosen_alerts),
        "has_volume_spike": _has_volume_spike(chosen_alerts),
        "minutes_to_resolution": _minutes_to_resolution(chosen_alerts),
    }


if __name__ == "__main__":
    import sys
    print("twitter_pipeline.py: main() not implemented yet", file=sys.stderr)
    sys.exit(1)
```

- [ ] **Step 2: Write the failing tests for `build_facts_bundle`.**

Create [test/test_twitter_pipeline_facts_bundle.py](test/test_twitter_pipeline_facts_bundle.py):

```python
"""Tests for the deterministic facts_bundle builder in twitter_pipeline.py."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


def _trade(*, wallet="0xa", outcome="Yes", usd=100.0, price=0.5, ts=None):
    return {
        "wallet": wallet, "outcome": outcome, "side": "BUY",
        "usdcSize": usd, "size": 200.0, "price": price,
        "timestamp": float(ts if ts is not None else time.time()),
        "transaction_hash": "0xdead",
    }


def test_empty_inputs_produce_zeroed_bundle():
    b = twitter_pipeline.build_facts_bundle([], [])
    assert b["distinct_wallets"] == 0
    assert b["total_usd"] == 0
    assert b["trade_count"] == 0
    assert b["time_span_minutes"] == 0
    assert b["biggest_price_move"] is None
    assert b["peak_hour_volume_usd"] is None
    assert b["has_sharp_wallet"] is None
    assert b["cluster_size"] is None
    assert b["has_volume_spike"] is False
    assert b["minutes_to_resolution"] is None


def test_distinct_wallets_and_total_usd():
    trades = [
        _trade(wallet="0xa", usd=100),
        _trade(wallet="0xb", usd=200),
        _trade(wallet="0xa", usd=300),
    ]
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["distinct_wallets"] == 2
    assert b["total_usd"] == 600
    assert b["trade_count"] == 3


def test_biggest_price_move_uses_dominant_outcome():
    # 80% of USD is on "Yes" (price moves 0.32 → 0.41).
    # 20% on "No" (price moves wildly, but ignored).
    trades = [
        _trade(outcome="Yes", usd=400, price=0.32, ts=1000),
        _trade(outcome="Yes", usd=400, price=0.41, ts=2000),
        _trade(outcome="No", usd=200, price=0.10, ts=3000),
        _trade(outcome="No", usd=200, price=0.90, ts=4000),
    ]
    b = twitter_pipeline.build_facts_bundle([], trades)
    move = b["biggest_price_move"]
    assert move == {"from": 0.32, "to": 0.41}


def test_biggest_price_move_none_with_single_trade():
    trades = [_trade(outcome="Yes", usd=100, price=0.5, ts=1000)]
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["biggest_price_move"] is None


def test_peak_hour_volume_uses_60min_rolling_window():
    # Two clusters: 5 trades within 30 min totaling 5000, then a single
    # trade 2 hours later. Peak should be the 5000.
    base = 1_700_000_000
    trades = [_trade(usd=1000, ts=base + 60 * i) for i in range(5)]
    trades.append(_trade(usd=200, ts=base + 7200))
    b = twitter_pipeline.build_facts_bundle([], trades)
    assert b["peak_hour_volume_usd"] == 5000


def test_volume_spike_signal_lifted_from_alerts():
    alerts = [{"signals": [{"strategy": "pre_event_volume_spike", "severity": 5}]}]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_volume_spike"] is True


def test_cluster_size_lifted_from_wallet_clustering_severity():
    alerts = [{
        "signals": [
            {"strategy": "wallet_clustering", "severity": 4},
            {"strategy": "concentrated_one_sided", "severity": 6},
        ]
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["cluster_size"] == 6


def test_sharp_wallet_from_llm_copy_action():
    alerts = [{
        "wallet": "0xfeed",
        "llm_copy_action": {"wallet_record": "29-4", "win_pct": 0.88},
        "signals": [],
    }]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_sharp_wallet"] == {
        "wallet": "0xfeed", "record": "29-4", "win_pct": 0.88,
    }


def test_sharp_wallet_falls_back_to_wallet_pnl(monkeypatch):
    # No record in llm_copy_action; signals indicate win_rate_tracking;
    # query_sqlite returns a real row.
    alerts = [{
        "wallet": "0xfeed",
        "llm_copy_action": {},
        "signals": [{"strategy": "win_rate_tracking", "severity": 8}],
    }]
    captured = {}
    def fake_query(sql):
        captured["sql"] = sql
        return [{"wins": 178, "losses": 20, "win_rate": 0.899}]
    import bot_utils
    monkeypatch.setattr(bot_utils, "query_sqlite", fake_query)
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert b["has_sharp_wallet"]["record"] == "178-20"
    assert b["has_sharp_wallet"]["wallet"] == "0xfeed"
    assert b["has_sharp_wallet"]["win_pct"] == 0.899
    assert "0xfeed" in captured["sql"]


def test_minutes_to_resolution_uses_nearest_future_time():
    in_30 = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    in_120 = (datetime.now(timezone.utc) + timedelta(minutes=120)).isoformat()
    alerts = [
        {"game_start_time": in_120},
        {"game_start_time": in_30},
    ]
    b = twitter_pipeline.build_facts_bundle(alerts, [])
    assert 28 <= b["minutes_to_resolution"] <= 31
```

- [ ] **Step 3: Run the tests and confirm they pass.**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_facts_bundle.py -v`
Expected: all 10 tests pass.

- [ ] **Step 4: Commit.**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_facts_bundle.py
git commit -m "Add facts_bundle builder for twitter_pipeline bot

Pure-function deterministic transform from (chosen_alerts, trades)
to a small dict of precise facts (price moves, volume, sharp wallet
record, cluster size, etc.) that the chart picker and writer can
quote without re-deriving."
```

---

## Task 3: Add the stage 2 fetch orchestrator

**Goal:** Stitch trades + tokens + facts_bundle together into one function `fetch_data_bundle(alert_ids, seed_alerts) -> dict` that the main loop calls.

**Files:**
- Modify: `storybot/twitter_pipeline.py`

- [ ] **Step 1: Add `fetch_data_bundle` to `twitter_pipeline.py`.**

Append to [storybot/twitter_pipeline.py](storybot/twitter_pipeline.py) after the helpers:

```python
def _select_chosen_alerts(alert_ids: list[int], seed_alerts: list[dict]) -> list[dict]:
    """Filter seed_alerts down to those whose id is in alert_ids."""
    wanted = {int(i) for i in alert_ids}
    return [a for a in seed_alerts if int(a.get("id") or 0) in wanted]


def fetch_data_bundle(alert_ids: list[int], seed_alerts: list[dict]) -> dict:
    """Stage 2: fetch trades + Gamma tokens for chosen alerts, build facts_bundle.

    Returns: {chosen_alerts, trades, token_map, facts_bundle}.
    Failures are absorbed — missing trades become [], missing tokens become {}.
    """
    from tweet_utils import fetch_alert_trades, fetch_market_tokens
    from bot_utils import log

    chosen = _select_chosen_alerts(alert_ids, seed_alerts)

    trades: list[dict] = []
    for aid in alert_ids:
        try:
            trades.extend(fetch_alert_trades(int(aid)))
        except Exception as exc:
            log("alert_trades_fetch_error",
                alert_id=aid, error=f"{type(exc).__name__}: {exc}")

    token_map: dict[str, str] = {}
    seen_cids: set[str] = set()
    for a in chosen:
        cid = a.get("condition_id")
        if not cid or cid in seen_cids:
            continue
        seen_cids.add(cid)
        token_map.update(fetch_market_tokens(cid))

    return {
        "chosen_alerts": chosen,
        "trades": trades,
        "token_map": token_map,
        "facts_bundle": build_facts_bundle(chosen, trades),
    }
```

- [ ] **Step 2: Add a unit test that mocks the helpers.**

Append to [test/test_twitter_pipeline_facts_bundle.py](test/test_twitter_pipeline_facts_bundle.py):

```python
def test_fetch_data_bundle_collects_trades_per_alert(monkeypatch):
    seed = [
        {"id": 1, "condition_id": "0xabc"},
        {"id": 2, "condition_id": "0xabc"},  # same market, dedup tokens
        {"id": 3, "condition_id": "0xdef"},
    ]
    calls_trades = []
    calls_tokens = []
    def fake_trades(aid):
        calls_trades.append(int(aid))
        return [_trade(wallet=f"0x{aid:02x}", usd=100)]
    def fake_tokens(cid):
        calls_tokens.append(cid)
        return {"Yes": f"tok-{cid}-yes"}

    import tweet_utils
    monkeypatch.setattr(tweet_utils, "fetch_alert_trades", fake_trades)
    monkeypatch.setattr(tweet_utils, "fetch_market_tokens", fake_tokens)

    bundle = twitter_pipeline.fetch_data_bundle([1, 2, 3], seed)

    assert calls_trades == [1, 2, 3]
    assert sorted(calls_tokens) == sorted(["0xabc", "0xdef"])  # deduped
    assert len(bundle["chosen_alerts"]) == 3
    assert len(bundle["trades"]) == 3
    assert bundle["token_map"] == {
        "Yes": "tok-0xdef-yes"  # last write wins; just assert key exists
    } or "Yes" in bundle["token_map"]
    assert "facts_bundle" in bundle
    assert bundle["facts_bundle"]["distinct_wallets"] == 3
```

- [ ] **Step 3: Run the tests.**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_facts_bundle.py -v`
Expected: 11 tests pass.

- [ ] **Step 4: Commit.**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_facts_bundle.py
git commit -m "Add fetch_data_bundle stage 2 orchestrator"
```

---

## Task 4: Stage 1 — event picker LLM

**Goal:** First LLM call. Picks one event-cluster (or skips) and returns alert_ids + a one-paragraph framing.

**Files:**
- Modify: `storybot/twitter_pipeline.py`
- Create: `test/test_twitter_pipeline_pick_event.py`

- [ ] **Step 1: Add the `SYSTEM_PROMPT_EVENT_PICKER` constant and `pick_event` function.**

Append to [storybot/twitter_pipeline.py](storybot/twitter_pipeline.py):

```python
SYSTEM_PROMPT_EVENT_PICKER = """You pick the single best event-cluster from \
the last ~3 hours of Polymarket alerts to tweet about, or skip if nothing \
stands out. You DO NOT write the tweet — that's a later stage.

You see up to 20 compact alerts, sorted by composite_score, each with its
top signals (strategy + severity + headline), market, wallet, $ size, event,
tags, and timing.

## Your job
1. Find the strongest *story*. A story = one event with one or more alerts
   that share a thesis. Multiple alerts on the same event_slug or
   condition_id usually belong together. A single alert is also fine if
   the signal is strong enough on its own.
2. Decide skip vs post:
   - skip if all alerts are small, generic, or lack a clear narrative
   - post if there's a real surprise: a sharp wallet, coordinated flow,
     a price/volume move, late-game timing, etc.
3. If posting, return the alert_ids that belong to that one event-cluster
   and a one-paragraph event_summary that frames what's surprising.

## Output (strict JSON only)
{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "alert_ids": [<int>, ...] | null,
  "event_summary": "<paragraph>" | null
}

When decision=post:
- alert_ids must be 1+ real IDs from the list shown to you, all sharing one event.
- event_summary must be a short paragraph (2-4 sentences) describing the event,
  the cluster, and the single most surprising fact. Plain English. No tweet
  voice yet. Downstream stages use this as framing.

When decision=skip, alert_ids and event_summary should be null.
"""


def pick_event(llm_client, seed_alerts: list[dict], *, usage: dict | None = None) -> dict:
    """Stage 1: pick an event-cluster to tweet about, or skip."""
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_EVENT_PICKER},
            {"role": "user", "content": user_msg},
        ],
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
        return {"decision": "skip", "reason": f"invalid JSON: {exc}",
                "alert_ids": None, "event_summary": None}


def validate_event_pick(pick: dict, seed_alerts: list[dict]) -> tuple[bool, str]:
    """Sanity-check stage 1 output. Returns (ok, error_message)."""
    d = pick.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"
    ids = pick.get("alert_ids") or []
    if not isinstance(ids, list) or not ids:
        return False, "alert_ids must be a non-empty list when posting"
    try:
        wanted = {int(i) for i in ids}
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {ids!r}"
    seed_ids = {int(a.get("id") or 0) for a in seed_alerts}
    missing = wanted - seed_ids
    if missing:
        return False, f"alert_ids not in seed: {sorted(missing)}"
    summary = pick.get("event_summary")
    if not isinstance(summary, str) or not summary.strip():
        return False, "event_summary must be a non-empty string when posting"
    return True, ""
```

- [ ] **Step 2: Write tests for `pick_event` and `validate_event_pick`.**

Create [test/test_twitter_pipeline_pick_event.py](test/test_twitter_pipeline_pick_event.py):

```python
"""Tests for stage 1 (event picker) of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


class FakeChat:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        msg = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(
            choices=[choice],
            usage=SimpleNamespace(
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(completions=FakeChat(content))


def _seed():
    return [
        {"id": 10, "event_slug": "e1", "wallet": "0xa"},
        {"id": 11, "event_slug": "e1", "wallet": "0xb"},
        {"id": 12, "event_slug": "e2", "wallet": "0xc"},
    ]


def test_pick_event_returns_skip_when_model_says_skip():
    client = FakeClient(json.dumps({
        "decision": "skip", "reason": "all alerts small",
        "alert_ids": None, "event_summary": None,
    }))
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "skip"


def test_pick_event_parses_post_decision():
    client = FakeClient(json.dumps({
        "decision": "post", "reason": "two alerts on same event",
        "alert_ids": [10, 11],
        "event_summary": "Two accounts piled into the same outcome.",
    }))
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "post"
    assert out["alert_ids"] == [10, 11]


def test_pick_event_swallows_bad_json_into_skip():
    client = FakeClient("this is not json")
    out = twitter_pipeline.pick_event(client, _seed())
    assert out["decision"] == "skip"
    assert "invalid JSON" in out["reason"]


def test_validate_accepts_valid_skip():
    ok, err = twitter_pipeline.validate_event_pick(
        {"decision": "skip", "reason": "x"}, _seed())
    assert ok, err


def test_validate_accepts_valid_post():
    pick = {"decision": "post", "alert_ids": [10, 11],
            "event_summary": "blah"}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert ok, err


def test_validate_rejects_unknown_alert_id():
    pick = {"decision": "post", "alert_ids": [10, 99],
            "event_summary": "blah"}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert not ok
    assert "99" in err


def test_validate_rejects_missing_event_summary():
    pick = {"decision": "post", "alert_ids": [10], "event_summary": ""}
    ok, err = twitter_pipeline.validate_event_pick(pick, _seed())
    assert not ok
    assert "event_summary" in err
```

- [ ] **Step 3: Run the tests.**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_pick_event.py -v`
Expected: 7 tests pass.

- [ ] **Step 4: Commit.**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_pick_event.py
git commit -m "Add stage 1 event picker for twitter_pipeline"
```

---

## Task 5: Stage 3 — chart picker LLM

**Goal:** Second LLM call. Sees event_summary + facts_bundle, picks a chart_type and a hook_anchor phrase.

**Files:**
- Modify: `storybot/twitter_pipeline.py`
- Create: `test/test_twitter_pipeline_pick_chart.py`

- [ ] **Step 1: Add `SYSTEM_PROMPT_CHART_PICKER` and `pick_chart` to `twitter_pipeline.py`.**

Append:

```python
SYSTEM_PROMPT_CHART_PICKER = """You pick a chart that proves the surprise the \
upcoming tweet will lead with. You also write the hook_anchor — one short \
phrase naming the surprising fact the chart visualizes.

You see:
- event_summary: a paragraph framing the story
- facts_bundle: precise numbers about the chosen event
- chosen_alerts: the compact alert rows that make up the cluster

## Available chart types
- "wallet_record_card" — one wallet's win record + their bet on this market.
  Pick this iff facts_bundle.has_sharp_wallet is non-null.
- "price_sparkline" — price over time on the dominant outcome.
  Pick this iff facts_bundle.biggest_price_move is non-null AND the move is
  meaningful (≥3 cents or ≥10% relative change).
- "volume_bar" — volume bars showing a spike.
  Pick this iff facts_bundle.has_volume_spike is true OR
  peak_hour_volume_usd dwarfs other windows.
- "cluster_card" — multi-wallet cluster card.
  Pick this iff facts_bundle.cluster_size >= 3 AND no sharp_wallet record
  dominates (otherwise prefer wallet_record_card and mention the cluster
  in the tweet text).
- "none" — if nothing supports a chart cleanly.

## Hook anchor
A 2-5 word phrase the writer will lead with. Examples:
- "29-4 sharp record"
- "32c → 41c flip"
- "12× normal volume"
- "five accounts, one funder"

If chart_type is "none", hook_anchor is still required and should name the
surprising thing in the story (the writer leads with it regardless).

## Output (strict JSON only)
{
  "chart_type": "wallet_record_card" | "price_sparkline" | "volume_bar" | "cluster_card" | "none",
  "hook_anchor": "<phrase>"
}
"""


def pick_chart(llm_client, chosen_alerts: list[dict], event_summary: str,
               bundle: dict, *, usage: dict | None = None) -> dict:
    """Stage 3: pick a chart_type and hook_anchor."""
    from bot_utils import MODEL, _accumulate_usage, _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
    }
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_CHART_PICKER},
            {"role": "user", "content": json.dumps(payload, default=str, indent=2)},
        ],
        temperature=1,
        max_completion_tokens=4000,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"chart_type": "none", "hook_anchor": "",
                "_parse_error": f"invalid JSON: {exc}"}


_VALID_CHART_TYPES = {"price_sparkline", "volume_bar", "wallet_record_card",
                      "cluster_card", "none"}


def validate_chart_pick(pick: dict) -> tuple[bool, str]:
    if pick.get("_parse_error"):
        return False, pick["_parse_error"]
    ct = pick.get("chart_type")
    if ct not in _VALID_CHART_TYPES:
        return False, f"unknown chart_type: {ct!r}"
    anchor = pick.get("hook_anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        return False, "hook_anchor must be a non-empty string"
    if len(anchor) > 80:
        return False, f"hook_anchor too long ({len(anchor)} > 80 chars)"
    return True, ""
```

- [ ] **Step 2: Write tests.**

Create [test/test_twitter_pipeline_pick_chart.py](test/test_twitter_pipeline_pick_chart.py):

```python
"""Tests for stage 3 (chart picker) of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


class FakeChat:
    def __init__(self, content):
        self._content = content
    def create(self, **kwargs):
        msg = SimpleNamespace(content=self._content)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg)],
            usage=SimpleNamespace(
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=FakeChat(content))


def test_pick_chart_parses_valid_response():
    client = FakeClient(json.dumps({
        "chart_type": "wallet_record_card",
        "hook_anchor": "29-4 sharp record",
    }))
    out = twitter_pipeline.pick_chart(client, [], "x", {})
    assert out["chart_type"] == "wallet_record_card"
    assert out["hook_anchor"] == "29-4 sharp record"


def test_pick_chart_handles_bad_json():
    client = FakeClient("garbage")
    out = twitter_pipeline.pick_chart(client, [], "x", {})
    assert out["chart_type"] == "none"
    assert "_parse_error" in out


def test_validate_accepts_valid_pick():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": "12× volume"})
    assert ok, err


def test_validate_accepts_none_chart():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "none", "hook_anchor": "unique cross-market thesis"})
    assert ok, err


def test_validate_rejects_unknown_chart_type():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "lol_no", "hook_anchor": "x"})
    assert not ok
    assert "chart_type" in err


def test_validate_rejects_missing_anchor():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": ""})
    assert not ok
    assert "hook_anchor" in err


def test_validate_rejects_oversized_anchor():
    ok, err = twitter_pipeline.validate_chart_pick(
        {"chart_type": "volume_bar", "hook_anchor": "x" * 81})
    assert not ok
    assert "hook_anchor" in err
```

- [ ] **Step 3: Run the tests.**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_pick_chart.py -v`
Expected: 7 tests pass.

- [ ] **Step 4: Commit.**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_pick_chart.py
git commit -m "Add stage 3 chart picker for twitter_pipeline"
```

---

## Task 6: Stage 4 — writer LLM + validation + retry

**Goal:** Final LLM call. Composes the tweet given event_summary + facts_bundle + chart_type + hook_anchor. Validates and retries once on failure.

**Files:**
- Modify: `storybot/twitter_pipeline.py`
- Create: `test/test_twitter_pipeline_validation.py`

- [ ] **Step 1: Add `SYSTEM_PROMPT_WRITER`, `validate_tweet`, and `write_tweet` (with retry).**

Append to [storybot/twitter_pipeline.py](storybot/twitter_pipeline.py):

```python
SYSTEM_PROMPT_WRITER = f"""You are the social media voice for PolySpotter — a \
service that surfaces notable bets on Polymarket (whales, sharp wallets, \
coordinated flow, informed edge). You compose ONE tweet for one event that \
earlier stages have already decided is worth tweeting about.

You see:
- event_summary: a paragraph framing the story
- facts_bundle: precise numbers (price moves, volume, sharp wallet record, etc.)
- chosen_alerts: the compact alert rows
- chart_type: which chart will ship with the tweet
- hook_anchor: a short phrase the chart proves; LEAD WITH THIS in the tweet

Your job: write a tweet that fits in 280 characters (URLs count as 23 chars).

## Audience
Sports/markets-curious reader who has never heard of PolySpotter and may not
know Polymarket. They will not parse insider shorthand. Every tweet must work
as a self-contained sentence.

- Anchor the venue once: "on Polymarket", "Polymarket account", "prediction-market bettors".
- Spell out what every bet is ON: "Under 7.5 runs" not "Under 7.5", "Yes on Fed
  cuts in May" not "Yes for $40k", "buying No at 12c" not "buying at 12c".
- When citing a win rate or record, say what it counts: "88% across 50+ Polymarket
  bets" / "178-20 on past markets", not "wins 88% of the time".

## Style
- Confident, punchy, human. Like a sharp friend explaining what they just spotted.
- LEAD WITH the hook_anchor — restate it as the first clause. Everything else
  is supporting context.
- 2-3 short sentences beats one long clause-stack. Aim for ≤20 words per sentence.
- Round numbers for readability: "$78k" not "$78,131.61"; "$2.8M" not "$2,789,285.20".
  Win-rate records stay exact ("178-20"). Max 3 numbers.
- Refer to wallets by what makes them notable ("a 178-20 wallet", "a fresh account
  up $400k"), not by 0x address.
- The closing line earns its spot: a stake, a time pressure, or something concrete
  to watch. NOT vague chest-thumps like "Not random.", "Something's cooking.",
  "Worth a look.". If you don't have a real closer, end on the link.
- 0-1 emoji, only if it earns its spot. No hashtags. No @mentions.
- BANNED jargon: "deployed capital", "real size", "meaningful size", "conviction
  flow", "high-conviction", "scan window", "composite score", "alerted flow",
  "positioning", "near-resolution flag", "priced in", "coordinated burst",
  "pile-in", "counterpunch", "looked cleaner", "linked wallet(s)", "wallet trio",
  "wallet duo", "wallet squad", "informed flow", "smart money flow".
- Banned CTAs: "in bio", "full breakdown", "link below", "more at", "link in bio".

## Link (mandatory)
Include exactly one polyspotter.com deep link. Prefer the market page; use a
wallet link only when the story is about one specific wallet.
- market: https://polyspotter.com/market/<slug>
    <slug> = kebab-cased market_title (lowercase, non-alnum → single dash,
    trim leading/trailing dashes, max 80 chars) + "-" + first 7 chars of
    condition_id (i.e. "0x" + 5 hex chars).
- wallet: https://polyspotter.com/wallet/<wallet_address>
- alert:  https://polyspotter.com/alert/<alert_id>
- tag:    https://polyspotter.com/tag/<tag-slug>

## Output (strict JSON only)
{{
  "tweet": "<text with one polyspotter.com link>"
}}
"""


def validate_tweet(text: str) -> tuple[bool, str]:
    """Length / banned-phrase / link presence checks. No JSON parsing."""
    from tweet_utils import (
        TWEET_MAX_CHARS, _BANNED_TWEET_PHRASES, _POLYSPOTTER_URL_RE, _tweet_length,
    )
    if not isinstance(text, str) or not text.strip():
        return False, "tweet must be a non-empty string"
    tlen = _tweet_length(text)
    if tlen > TWEET_MAX_CHARS:
        return False, f"tweet length {tlen} exceeds {TWEET_MAX_CHARS}"
    lower = text.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned CTA phrase {phrase!r}"
    if not _POLYSPOTTER_URL_RE.search(text):
        return False, "tweet must contain a polyspotter.com deep link"
    return True, ""


def _writer_user_message(chosen_alerts: list[dict], event_summary: str,
                         bundle: dict, chart_pick: dict) -> str:
    from bot_utils import _compact_alert_for_picker
    compact = [_compact_alert_for_picker(a) for a in chosen_alerts]
    payload = {
        "event_summary": event_summary,
        "facts_bundle": bundle,
        "chosen_alerts": compact,
        "chart_type": chart_pick.get("chart_type"),
        "hook_anchor": chart_pick.get("hook_anchor"),
    }
    return json.dumps(payload, default=str, indent=2)


def write_tweet(llm_client, chosen_alerts: list[dict], event_summary: str,
                bundle: dict, chart_pick: dict, *,
                usage: dict | None = None,
                prior_error: str | None = None) -> dict:
    """Stage 4: compose the tweet. Caller invokes this twice if validation fails."""
    from bot_utils import MODEL, _accumulate_usage
    messages = [{"role": "system", "content": SYSTEM_PROMPT_WRITER}]
    if prior_error:
        messages.append({
            "role": "system",
            "content": f"Your previous tweet failed validation: {prior_error}. Regenerate.",
        })
    messages.append({
        "role": "user",
        "content": _writer_user_message(chosen_alerts, event_summary, bundle, chart_pick),
    })
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


def write_tweet_with_retry(llm_client, chosen_alerts, event_summary, bundle,
                           chart_pick, *, usage=None) -> tuple[dict, str | None, int]:
    """Run stage 4 once; on validation failure, retry once with the error fed back.

    Returns (final_decision_dict, error_or_None, attempts).
    """
    from bot_utils import log
    attempt = 1
    out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                      usage=usage)
    if out.get("_parse_error"):
        log("validation_retry", error=out["_parse_error"])
        attempt = 2
        out = write_tweet(llm_client, chosen_alerts, event_summary, bundle, chart_pick,
                          usage=usage, prior_error=out["_parse_error"])
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
                      usage=usage, prior_error=err)
    if out.get("_parse_error"):
        return out, out["_parse_error"], attempt
    ok, err = validate_tweet(out.get("tweet", ""))
    return (out, None, attempt) if ok else (out, err, attempt)
```

- [ ] **Step 2: Write validation + retry tests.**

Create [test/test_twitter_pipeline_validation.py](test/test_twitter_pipeline_validation.py):

```python
"""Tests for stage 4 validation + retry path of twitter_pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


class _FakeCompletions:
    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        content = self._contents.pop(0) if self._contents else "{}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                prompt_tokens_details=None, completion_tokens_details=None,
            ),
        )


class FakeClient:
    def __init__(self, contents):
        self.completions = _FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.completions)


def test_validate_accepts_short_tweet_with_link():
    text = "A 29-4 wallet just bought Yes on Fed May. https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert ok, err


def test_validate_rejects_oversized_tweet():
    text = "A " * 200 + "https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "exceeds" in err


def test_validate_rejects_missing_link():
    text = "Look at this banger of a tweet without any link"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "deep link" in err


def test_validate_rejects_banned_phrase():
    text = "Full breakdown. https://polyspotter.com/alert/1"
    ok, err = twitter_pipeline.validate_tweet(text)
    assert not ok
    assert "banned" in err.lower() or "phrase" in err.lower()


def test_validate_rejects_empty_tweet():
    ok, err = twitter_pipeline.validate_tweet("")
    assert not ok


def test_writer_succeeds_on_first_attempt():
    good = json.dumps({"tweet": "Sharp wallet 29-4. https://polyspotter.com/alert/1"})
    client = FakeClient([good])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 1
    assert client.completions.calls == 1


def test_writer_retries_once_on_missing_link():
    bad = json.dumps({"tweet": "No link in this tweet at all"})
    good = json.dumps({"tweet": "Same point. https://polyspotter.com/alert/1"})
    client = FakeClient([bad, good])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is None
    assert attempts == 2
    assert client.completions.calls == 2


def test_writer_gives_up_after_two_failures():
    bad1 = json.dumps({"tweet": "no link 1"})
    bad2 = json.dumps({"tweet": "no link 2"})
    client = FakeClient([bad1, bad2])
    decision, err, attempts = twitter_pipeline.write_tweet_with_retry(
        client, [], "summary", {}, {"chart_type": "none", "hook_anchor": "x"})
    assert err is not None
    assert "deep link" in err
    assert attempts == 2
    assert client.completions.calls == 2
```

- [ ] **Step 3: Run the tests.**

Run: `source venv/bin/activate && pytest test/test_twitter_pipeline_validation.py -v`
Expected: 8 tests pass.

- [ ] **Step 4: Commit.**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_validation.py
git commit -m "Add stage 4 writer with one-retry validation"
```

---

## Task 7: `main()` orchestration

**Goal:** Wire all four stages together into a runnable bot. Mirror `twitter_simple.main()` for logging, dedup, posting, and recording.

**Files:**
- Modify: `storybot/twitter_pipeline.py`

- [ ] **Step 1: Add `main()` and the env/imports it needs.**

Add to the top of [storybot/twitter_pipeline.py](storybot/twitter_pipeline.py) (after the existing imports):

```python
import os
import sys
import time
import uuid

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DRY_RUN = os.environ.get("TWITTER_PIPELINE_DRY_RUN", "false").lower() == "true"
_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")
```

Append at the bottom (above the `if __name__ == "__main__"` guard):

```python
def _dump_dry_run(run_id: str, transcript: dict) -> None:
    """Write the full stage transcript to dry_runs/twitter_pipeline_<run_id>.json."""
    from bot_utils import log
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"twitter_pipeline_{run_id}.json")
    try:
        with open(path, "w") as f:
            json.dump(transcript, f, default=str, indent=2)
        log("transcript_saved", path=path)
    except OSError as exc:
        log("transcript_save_error", error=str(exc))


def main() -> int:
    from bot_utils import (
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, DATABASE_URL, log,
        fetch_seed_alerts,
    )
    from tweet_utils import (
        _build_twitter_api_v1, _build_twitter_client,
        filter_posted_alerts, post_tweet, prepare_chart, record_tweet,
        strip_polyspotter_url,
    )

    run_id = uuid.uuid4().hex[:8]
    log("run_start", run_id=run_id, dry_run=DRY_RUN, bot="twitter_pipeline")

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    usage_totals: dict = {}
    run_start_t = time.monotonic()
    transcript: dict = {"run_id": run_id, "stages": {}}

    # Seed
    t = time.monotonic()
    try:
        seed_alerts = fetch_seed_alerts()
    except Exception as exc:
        log("seed_fetch_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    log("seed_fetched", run_id=run_id, count=len(seed_alerts),
        elapsed_ms=int((time.monotonic() - t) * 1000))
    if not seed_alerts:
        log("skip", run_id=run_id, reason="no alerts in last 3 hours")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    pre = len(seed_alerts)
    try:
        seed_alerts = filter_posted_alerts(seed_alerts)
    except Exception as exc:
        log("dedup_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    log("dedup_filtered", run_id=run_id, before=pre, after=len(seed_alerts),
        dropped=pre - len(seed_alerts))
    if not seed_alerts:
        log("skip", run_id=run_id, reason="all seed alerts already tweeted")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    # Stage 1
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=1)
    try:
        pick = pick_event(llm_client, seed_alerts, usage=usage_totals)
    except Exception as exc:
        log("llm_error", run_id=run_id, stage=1,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=1,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["1_event_picker"] = pick
    ok, err = validate_event_pick(pick, seed_alerts)
    if not ok:
        log("validation_error", run_id=run_id, stage=1, error=err, pick=pick)
        return 1
    if pick["decision"] == "skip":
        log("skip", run_id=run_id, reason=pick.get("reason"))
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0
    log("event_picked", run_id=run_id, alert_ids=pick["alert_ids"],
        event_summary=pick["event_summary"])

    # Stage 2
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=2)
    bundle = fetch_data_bundle(pick["alert_ids"], seed_alerts)
    log("stage_end", run_id=run_id, stage=2,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    log("data_fetched", run_id=run_id,
        trade_count=len(bundle["trades"]),
        token_keys=list(bundle["token_map"].keys()),
        facts_bundle_keys=list(bundle["facts_bundle"].keys()))
    transcript["stages"]["2_data_fetcher"] = {
        "trade_count": len(bundle["trades"]),
        "token_map": bundle["token_map"],
        "facts_bundle": bundle["facts_bundle"],
    }

    # Stage 3
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=3)
    try:
        chart_pick = pick_chart(llm_client, bundle["chosen_alerts"],
                                pick["event_summary"], bundle["facts_bundle"],
                                usage=usage_totals)
    except Exception as exc:
        log("llm_error", run_id=run_id, stage=3,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=3,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["3_chart_picker"] = chart_pick
    ok, err = validate_chart_pick(chart_pick)
    if not ok:
        log("validation_error", run_id=run_id, stage=3, error=err, pick=chart_pick)
        return 1
    log("chart_picked", run_id=run_id, chart_type=chart_pick["chart_type"],
        hook_anchor=chart_pick["hook_anchor"])

    # Stage 4
    t = time.monotonic()
    log("stage_start", run_id=run_id, stage=4)
    try:
        decision, err, attempts = write_tweet_with_retry(
            llm_client, bundle["chosen_alerts"], pick["event_summary"],
            bundle["facts_bundle"], chart_pick, usage=usage_totals)
    except Exception as exc:
        log("llm_error", run_id=run_id, stage=4,
            error=f"{type(exc).__name__}: {exc}")
        return 1
    log("stage_end", run_id=run_id, stage=4, attempts=attempts,
        elapsed_ms=int((time.monotonic() - t) * 1000))
    transcript["stages"]["4_writer"] = {"decision": decision, "attempts": attempts}
    if err:
        log("validation_error", run_id=run_id, stage=4, attempts=attempts,
            error=err, decision=decision)
        if DRY_RUN:
            _dump_dry_run(run_id, transcript)
        return 1

    tweet = strip_polyspotter_url(decision["tweet"])
    log("tweet_drafted", run_id=run_id, attempts=attempts, length=len(tweet))
    log("llm_usage", run_id=run_id, **usage_totals)

    # Resolve chart png
    target_alert = next(
        (a for a in bundle["chosen_alerts"]
         if int(a.get("id") or 0) == int(pick["alert_ids"][0])),
        None,
    )
    chart_png = (prepare_chart(chart_pick["chart_type"], target_alert)
                 if target_alert else None)
    log("chart_selected", run_id=run_id, chart_type=chart_pick["chart_type"],
        rendered=chart_png is not None,
        bytes_len=(len(chart_png) if chart_png else 0))

    if DRY_RUN and chart_png is not None:
        os.makedirs(_DRY_RUN_DIR, exist_ok=True)
        out_path = os.path.join(_DRY_RUN_DIR, f"twitter_pipeline_{run_id}.png")
        try:
            with open(out_path, "wb") as f:
                f.write(chart_png)
            log("chart_saved_dryrun", run_id=run_id, path=out_path)
        except OSError as exc:
            log("chart_save_error", run_id=run_id, error=str(exc))

    if DRY_RUN:
        _dump_dry_run(run_id, transcript)

    # Post
    try:
        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
        tweet_id = post_tweet(
            tweet, twitter_client=twitter_client, twitter_api_v1=twitter_api_v1,
            media_png=chart_png, dry_run=DRY_RUN,
        )
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    log("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=pick["alert_ids"],
        tweet_length=len(tweet))
    print(f"\n--- Tweet ({len(tweet)} chars) ---\n{tweet}\n", flush=True)

    if DRY_RUN:
        log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    try:
        record_tweet([int(i) for i in pick["alert_ids"]], tweet_id, tweet)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0
```

Replace the `if __name__ == "__main__"` block at the bottom of the file with:

```python
if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the full test suite to confirm nothing regressed.**

Run: `source venv/bin/activate && pytest test/ -q`
Expected: all tests still pass.

- [ ] **Step 3: Commit.**

```bash
git add storybot/twitter_pipeline.py
git commit -m "Wire main() for twitter_pipeline bot

Orchestrates the four stages with structured logging,
dry-run JSON transcript dump, chart resolution, and
the same dedup/post/record path twitter_simple uses."
```

---

## Task 8: End-to-end smoke test in dry-run

**Goal:** Run the new bot against live data once with dry-run on. Verify each stage's output landed in the JSON transcript, the chart PNG saved, and no exceptions surfaced.

**Files:** None modified.

- [ ] **Step 1: Run the bot in dry-run mode.**

Run: `source venv/bin/activate && TWITTER_PIPELINE_DRY_RUN=true python storybot/twitter_pipeline.py`

Expected: a sequence of structured log lines containing at minimum:
- `run_start` with `bot="twitter_pipeline"`
- `seed_fetched`, `dedup_filtered`
- `stage_start stage=1`, `stage_end stage=1`
- Either `event_picked ...` (post path) OR `skip ...` (skip path)
- If post: `stage_start stage=2..4` and corresponding `stage_end`s, `data_fetched`, `chart_picked`, `tweet_drafted`, `chart_selected`, `posted tweet_id=dryrun-...`
- `run_end` event with `posted=true|false`

No tracebacks. Exit code 0.

- [ ] **Step 2: Inspect the dry-run artifacts.**

Run: `ls -la storybot/dry_runs/twitter_pipeline_*`
Expected (when stage 1 chose post): a `.json` transcript file and a `.png` chart file. The JSON has top-level `run_id` and `stages` keys with `1_event_picker`, `2_data_fetcher`, `3_chart_picker`, `4_writer` populated.

Open the JSON in your editor and skim the writer's tweet output and the chart picker's `hook_anchor`. They should be aligned (the tweet's first clause should restate the hook_anchor).

- [ ] **Step 3: Run a second dry-run to verify dedup.**

Note: dedup is keyed on `tweeted_alerts`, which only gets written for non-dry-run posts. So a second dry-run will likely process the same alerts again. This is expected; just confirm it runs cleanly twice in a row.

Run: `source venv/bin/activate && TWITTER_PIPELINE_DRY_RUN=true python storybot/twitter_pipeline.py`
Expected: completes without errors. Output may differ if the LLM picks a different event the second time — that's fine.

- [ ] **Step 4: Final commit (if any artifacts to ignore).**

If `dry_runs/` isn't already in `.gitignore`, check and add the new pattern. Otherwise this task has nothing to commit.

```bash
git status   # confirm no unexpected files
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Implementing task |
|--------------|-------------------|
| Pipeline shape (4 stages) | Tasks 4–7 |
| Stage 1 contract (skip/post + alert_ids + event_summary) | Task 4 |
| Stage 2 contract (trades + token_map + facts_bundle) | Tasks 2–3 |
| facts_bundle field definitions (sharp_wallet fallback, biggest_price_move on dominant outcome, etc.) | Task 2 |
| Stage 3 contract (chart_type + hook_anchor) | Task 5 |
| Stage 4 contract (tweet) + retry behavior | Task 6 |
| Module layout (extract to tweet_utils, new twitter_pipeline.py) | Task 1 |
| New env var TWITTER_PIPELINE_DRY_RUN + dry-run JSON dump | Task 7 |
| Logging events per stage | Task 7 |
| Failure handling table | Tasks 4–7 (each stage's error path) |
| Testing (facts_bundle unit tests, validation tests) | Tasks 2, 6 |
| Smoke test | Task 8 |

All sections covered.

**Type consistency check:**
- `pick_event` returns dict with `decision`, `alert_ids`, `event_summary` keys → consumed in Task 7's `main()` ✓
- `fetch_data_bundle` returns dict with `chosen_alerts`, `trades`, `token_map`, `facts_bundle` → consumed in Task 7 ✓
- `pick_chart` returns dict with `chart_type`, `hook_anchor` → consumed in Task 6 (`write_tweet`) and Task 7 ✓
- `write_tweet_with_retry` returns `(decision_dict, err_or_None, attempts)` tuple → consumed in Task 7 ✓
- `prepare_chart` API change from `(decision, seed_alerts)` to `(chart_type, alert)` → reflected in Task 1's new wrapper in `twitter_simple.py` and Task 7's direct call in `twitter_pipeline.main()` ✓

**Placeholder scan:** No TBD/TODO/"add appropriate" placeholders. Test code is concrete in every task.
