# Twitter Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an hourly Twitter bot for the Polybot/PolySpotter project that posts one engaging tweet per hour (or skips) based on recent alerts, with "link in bio" CTAs since the X API tier doesn't allow URLs.

**Architecture:** Single standalone Python script (`backend/twitter_bot.py`) run by Railway cron. Per invocation: fetches the last hour's alerts from the hosted API, applies two-layer dedup (per-alert and per-wallet/market), sends top 5 candidates to GPT-5.4 via the existing Azure OpenAI setup, posts the returned tweet via Tweepy, and records the result in a new `tweeted_alerts` Postgres table.

**Tech Stack:** Python 3.13, `tweepy` 4.14+ (X API v2 OAuth 1.0a), Azure OpenAI (`gpt-5.4`), Postgres via psycopg2 (same DB as backend), pytest.

---

## Spec reference

Source spec: [docs/superpowers/specs/2026-04-19-twitter-bot-design.md](../specs/2026-04-19-twitter-bot-design.md)

## File structure

| Path | Purpose | State |
|---|---|---|
| `backend/twitter_bot.py` | Single-file bot: entry, config, fetch, dedup, LLM, post, record | Create |
| `backend/test_twitter_bot.py` | Pytest tests using injectable fakes for API/LLM/Twitter/DB | Create |
| `backend/schema.sql` | Append `tweeted_alerts` table definition | Modify |
| `backend/database.py` | Add `_migrate_add_tweeted_alerts` migration, call it from `init_db` | Modify |
| `backend/requirements.txt` | Add `tweepy>=4.14` | Modify |

## Module layout inside `backend/twitter_bot.py`

The file is structured as pure-ish functions that accept dependencies, plus one `main()` that wires real dependencies in. Each function fits in one screen. No classes.

```python
# Config (loaded from env at module level)
POLYSPOTTER_API_URL: str
TWITTER_BOT_MIN_SCORE: float
TWITTER_BOT_DRY_RUN: bool
X_CONSUMER_KEY, X_CONSUMER_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET: str
AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, MODEL: str

# Core functions (all take injectable deps)
def fetch_recent_alerts(api_url, min_score, *, http=requests) -> list[dict]
def filter_dedup(candidates, db_conn) -> list[dict]
def call_llm(top5, *, llm_client) -> dict   # returns decision dict, handles length retry
def validate_decision(decision, top5_ids) -> tuple[bool, str]
def post_tweet(text, *, twitter_client, dry_run) -> str   # returns tweet_id
def record_tweet(alert_ids, wallet_map, tweet_id, tweet_text, db_conn) -> None
def log_event(event: str, **fields) -> None   # prints single-line JSON to stdout

# Entrypoint
def main() -> int   # returns exit code
```

---

## Task 1: Add `tweepy` dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add `tweepy` to requirements**

Append to `backend/requirements.txt`:

```
tweepy>=4.14
```

- [ ] **Step 2: Install it locally in the project venv**

Run:
```bash
source venv/bin/activate
pip install "tweepy>=4.14"
```

Expected: tweepy and its deps install cleanly.

- [ ] **Step 3: Verify import works**

Run:
```bash
source venv/bin/activate
python -c "import tweepy; print(tweepy.__version__)"
```

Expected: prints `4.14.x` or newer.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "Add tweepy dependency for the Twitter bot"
```

---

## Task 2: Add `tweeted_alerts` table to schema and migrations

**Files:**
- Modify: `backend/schema.sql` (append at the end)
- Modify: `backend/database.py` (add a new `_migrate_add_tweeted_alerts` function, call it from `init_db`)

- [ ] **Step 1: Append the table to `schema.sql`**

Append to the end of `backend/schema.sql`:

```sql

-- tweeted_alerts: one row per alert surfaced in a posted tweet. Used by the
-- Twitter bot (backend/twitter_bot.py) for dedup. Composite tweets produce
-- multiple rows sharing the same tweet_id and tweet_text.
CREATE TABLE IF NOT EXISTS tweeted_alerts (
    alert_id       BIGINT PRIMARY KEY,
    wallet         TEXT NOT NULL,
    condition_id   TEXT NOT NULL,
    tweet_id       TEXT NOT NULL,
    tweet_text     TEXT NOT NULL,
    tweeted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweeted_alerts_wallet_market
    ON tweeted_alerts (wallet, condition_id, tweeted_at DESC);
```

- [ ] **Step 2: Add a migration helper to `database.py`**

Open `backend/database.py` and add this function near the other `_migrate_*` helpers (e.g., right after `_migrate_add_seo_fields`):

```python
def _migrate_add_tweeted_alerts(cur):
    """Create the tweeted_alerts table if it doesn't exist (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tweeted_alerts (
            alert_id       BIGINT PRIMARY KEY,
            wallet         TEXT NOT NULL,
            condition_id   TEXT NOT NULL,
            tweet_id       TEXT NOT NULL,
            tweet_text     TEXT NOT NULL,
            tweeted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_tweeted_alerts_wallet_market
            ON tweeted_alerts (wallet, condition_id, tweeted_at DESC)
    """)
```

- [ ] **Step 3: Call the migration from `init_db`**

In `backend/database.py`, update the `init_db` function to call the new migration. Change:

```python
        with conn.cursor() as cur:
            cur.execute(sql)
            _migrate_category_to_tags(cur)
            _migrate_add_llm_fields(cur)
            _migrate_add_market_media(cur)
            _migrate_add_seo_fields(cur)
            _migrate_add_event_timing(cur)
        conn.commit()
```

to:

```python
        with conn.cursor() as cur:
            cur.execute(sql)
            _migrate_category_to_tags(cur)
            _migrate_add_llm_fields(cur)
            _migrate_add_market_media(cur)
            _migrate_add_seo_fields(cur)
            _migrate_add_event_timing(cur)
            _migrate_add_tweeted_alerts(cur)
        conn.commit()
```

- [ ] **Step 4: Smoke-test the migration against a dev DB**

Requires `DATABASE_URL` pointing at a reachable Postgres (local or Railway dev):

```bash
source venv/bin/activate
cd backend
python -c "from database import init_db; init_db(); print('ok')"
```

Expected: prints `ok` and the `tweeted_alerts` table exists.

Verify:
```bash
psql "$DATABASE_URL" -c "\d tweeted_alerts"
```

Expected: shows the table definition with `alert_id BIGINT PK`, `wallet`, `condition_id`, `tweet_id`, `tweet_text`, `tweeted_at` columns.

If you don't have a reachable Postgres, skip this step — the migration will run on the next FastAPI boot via `init_db()`.

- [ ] **Step 5: Commit**

```bash
git add backend/schema.sql backend/database.py
git commit -m "Add tweeted_alerts table and migration"
```

---

## Task 3: Scaffold `backend/twitter_bot.py` with config loading

**Files:**
- Create: `backend/twitter_bot.py`

- [ ] **Step 1: Create the file with module docstring, imports, and config**

Write to `backend/twitter_bot.py`:

```python
"""
Hourly Twitter bot for PolySpotter.

Runs as a standalone script (Railway cron, once per hour at :00):
    python backend/twitter_bot.py

Flow: fetch last-hour alerts → dedup → send top 5 to GPT-5.4 → either post
a tweet via the X API or skip → record to tweeted_alerts.

Design spec: docs/superpowers/specs/2026-04-19-twitter-bot-design.md
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import psycopg2
import requests
import tweepy
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor


load_dotenv()

# --- Config (from env) --------------------------------------------------------

POLYSPOTTER_API_URL = os.environ.get("POLYSPOTTER_API_URL", "https://api.polyspotter.com")
TWITTER_BOT_MIN_SCORE = float(os.environ.get("TWITTER_BOT_MIN_SCORE", "5.0"))
TWITTER_BOT_DRY_RUN = os.environ.get("TWITTER_BOT_DRY_RUN", "false").lower() == "true"

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_KEY_SECRET = os.environ.get("X_CONSUMER_KEY_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://gpt-5-mati-labs.cognitiveservices.azure.com/openai/v1/"
MODEL = "gpt-5.4"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Time window for candidate alerts (slack beyond exactly 60 minutes to tolerate
# cron drift).
LOOKBACK_MINUTES = 65

# Soft-dedup window: don't tweet same (wallet, condition_id) within this many hours.
SOFT_DEDUP_HOURS = 24

# Hard length cap for tweets (under X's 280 limit, leaves safety margin).
TWEET_MAX_CHARS = 260


# --- Logging ------------------------------------------------------------------

def log_event(event: str, **fields: Any) -> None:
    """Emit a single-line JSON log event to stdout."""
    payload = {"event": event, **fields}
    # Ensure values are JSON-safe.
    print(json.dumps(payload, default=str), flush=True)


if __name__ == "__main__":
    sys.exit(0)  # placeholder; real main() added in Task 10
```

- [ ] **Step 2: Verify the file imports cleanly**

Run:
```bash
source venv/bin/activate
python -c "import importlib.util, sys; spec = importlib.util.spec_from_file_location('tb', 'backend/twitter_bot.py'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('ok')"
```

Expected: prints `ok`.

(If `AZURE_OPENAI_API_KEY` or `DATABASE_URL` are unset, the module still imports — they're read into module-level strings but nothing fails at import time.)

- [ ] **Step 3: Commit**

```bash
git add backend/twitter_bot.py
git commit -m "Scaffold twitter_bot.py with config and structured logging"
```

---

## Task 4: `fetch_recent_alerts` — HTTP fetch + time-window filter

**Files:**
- Modify: `backend/twitter_bot.py` (add `fetch_recent_alerts`)
- Create: `backend/test_twitter_bot.py` (first test file; includes the pattern for following tests)

- [ ] **Step 1: Write the failing tests**

Create `backend/test_twitter_bot.py`:

```python
"""
Tests for backend/twitter_bot.py.

Uses injected fakes for the HTTP client, LLM client, Twitter client, and DB
connection. No real network or DB calls.

Run: cd backend && pytest test_twitter_bot.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# The bot reads env vars at import time for config — set harmless defaults.
import os
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nope")
os.environ.setdefault("POLYSPOTTER_API_URL", "https://api.example.test")

import twitter_bot as tb


# ------------------------------------------------------------------ fixtures --

def _alert(**overrides):
    """Build an AlertOut-shaped dict with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": 1,
        "composite_score": 8.0,
        "market_title": "Will X happen?",
        "condition_id": "0xcond1",
        "wallet": "0xwallet1",
        "total_usd": 25_000.0,
        "trade_count": 1,
        "llm_headline": "Whale loads up on X",
        "llm_summary": "Wallet with 82% win rate dropped $25k.",
        "win_rate": 0.82,
        "total_pnl": 340_000.0,
        "tags": ["Politics"],
        "created_at": now,
    }
    defaults.update(overrides)
    return defaults


class FakeHTTP:
    """Stand-in for the `requests` module. Records calls, returns a canned body."""

    def __init__(self, body):
        self._body = body
        self.last_url = None
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        resp = SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: self._body
        resp.raise_for_status = lambda: None
        return resp


# ------------------------------------------------------- fetch_recent_alerts --

def test_fetch_recent_alerts_filters_to_lookback_window():
    recent = _alert(id=1, created_at=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
    old = _alert(id=2, created_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat())
    fake = FakeHTTP({"alerts": [recent, old], "total": 2, "page": 1, "per_page": 100})

    result = tb.fetch_recent_alerts(
        api_url="https://api.example.test",
        min_score=5.0,
        http=fake,
    )

    ids = [a["id"] for a in result]
    assert ids == [1]
    assert fake.last_url == "https://api.example.test/api/alerts"
    assert fake.last_params == {"per_page": 100, "min_score": 5.0}


def test_fetch_recent_alerts_returns_empty_on_no_alerts():
    fake = FakeHTTP({"alerts": [], "total": 0, "page": 1, "per_page": 100})

    result = tb.fetch_recent_alerts(
        api_url="https://api.example.test",
        min_score=5.0,
        http=fake,
    )

    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: fails with `AttributeError: module 'twitter_bot' has no attribute 'fetch_recent_alerts'`.

- [ ] **Step 3: Implement `fetch_recent_alerts`**

In `backend/twitter_bot.py`, replace the placeholder `if __name__ == "__main__":` block at the bottom (we'll re-add an entrypoint in Task 10) with the function below, then re-add `if __name__ == "__main__": sys.exit(0)` at the very end.

Insert after the `log_event` function:

```python
# --- Fetch alerts from PolySpotter API ---------------------------------------

def fetch_recent_alerts(api_url: str, min_score: float, *, http=requests) -> list[dict]:
    """Fetch alerts from the hosted API and filter to the last LOOKBACK_MINUTES.

    The API returns alerts sorted by created_at DESC, so we fetch up to 100 and
    client-side filter by `created_at`. Returns a list of AlertOut-shaped dicts.
    """
    resp = http.get(
        f"{api_url}/api/alerts",
        params={"per_page": 100, "min_score": min_score},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    alerts = body.get("alerts", [])

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    recent = []
    for a in alerts:
        ts = a.get("created_at")
        if not ts:
            continue
        # Accept datetime or ISO string; FastAPI returns ISO.
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            parsed = ts
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed >= cutoff:
            recent.append(a)
    return recent
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: both `test_fetch_recent_alerts_*` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add fetch_recent_alerts with 65-minute lookback filter"
```

---

## Task 5: `filter_dedup` — hard + soft dedup against `tweeted_alerts`

**Files:**
- Modify: `backend/twitter_bot.py` (add `filter_dedup`)
- Modify: `backend/test_twitter_bot.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_twitter_bot.py`:

```python
# ------------------------------------------------------------- filter_dedup --

class FakeCursor:
    """Stand-in for a psycopg2 cursor. Returns canned results for queries."""

    def __init__(self, hard_dedup_ids=None, soft_dedup_pairs=None):
        # Set of alert ids already tweeted.
        self._hard = set(hard_dedup_ids or [])
        # Set of (wallet, condition_id) pairs tweeted within the soft window.
        self._soft = set(soft_dedup_pairs or [])
        self._last_query = None
        self._last_params = None

    def execute(self, query, params=None):
        self._last_query = query
        self._last_params = params

    def fetchall(self):
        if "SELECT alert_id FROM tweeted_alerts WHERE alert_id" in self._last_query:
            requested = self._last_params[0]
            return [{"alert_id": i} for i in requested if i in self._hard]
        if "SELECT wallet, condition_id FROM tweeted_alerts" in self._last_query:
            return [
                {"wallet": w, "condition_id": c}
                for (w, c) in self._soft
            ]
        return []

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, cursor_factory=None):
        return self._cur

    def commit(self):
        pass

    def close(self):
        pass


def test_filter_dedup_drops_alerts_already_tweeted_by_id():
    cur = FakeCursor(hard_dedup_ids={2})
    conn = FakeConn(cur)
    candidates = [_alert(id=1), _alert(id=2), _alert(id=3)]

    result = tb.filter_dedup(candidates, conn)

    assert [a["id"] for a in result] == [1, 3]


def test_filter_dedup_drops_alerts_with_recent_same_wallet_market():
    cur = FakeCursor(soft_dedup_pairs={("0xw1", "0xc1")})
    conn = FakeConn(cur)
    candidates = [
        _alert(id=10, wallet="0xw1", condition_id="0xc1"),   # dropped
        _alert(id=11, wallet="0xw1", condition_id="0xc2"),   # kept (different market)
        _alert(id=12, wallet="0xw2", condition_id="0xc1"),   # kept (different wallet)
    ]

    result = tb.filter_dedup(candidates, conn)

    assert [a["id"] for a in result] == [11, 12]


def test_filter_dedup_keeps_everything_when_no_prior_tweets():
    cur = FakeCursor()
    conn = FakeConn(cur)
    candidates = [_alert(id=1), _alert(id=2)]

    result = tb.filter_dedup(candidates, conn)

    assert [a["id"] for a in result] == [1, 2]


def test_filter_dedup_with_empty_candidate_list_returns_empty():
    cur = FakeCursor()
    conn = FakeConn(cur)
    assert tb.filter_dedup([], conn) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the four new `test_filter_dedup_*` tests fail with `AttributeError: module 'twitter_bot' has no attribute 'filter_dedup'`.

- [ ] **Step 3: Implement `filter_dedup`**

In `backend/twitter_bot.py`, add after `fetch_recent_alerts`:

```python
# --- Deduplication -----------------------------------------------------------

def filter_dedup(candidates: list[dict], db_conn) -> list[dict]:
    """Drop candidates that have already been tweeted, or whose
    (wallet, condition_id) pair was tweeted within SOFT_DEDUP_HOURS.

    Runs two queries:
      1. Hard dedup: exact alert_id match.
      2. Soft dedup: (wallet, condition_id) match within the window.
    """
    if not candidates:
        return []

    cur = db_conn.cursor(cursor_factory=RealDictCursor)
    try:
        # 1. Hard dedup: alert_id already tweeted?
        ids = [int(a["id"]) for a in candidates]
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            (ids,),
        )
        hard = {row["alert_id"] for row in cur.fetchall()}

        # 2. Soft dedup: (wallet, condition_id) tweeted recently?
        cutoff = datetime.now(timezone.utc) - timedelta(hours=SOFT_DEDUP_HOURS)
        cur.execute(
            """
            SELECT wallet, condition_id
            FROM tweeted_alerts
            WHERE tweeted_at >= %s
              AND wallet = ANY(%s)
              AND condition_id = ANY(%s)
            """,
            (cutoff, [a.get("wallet") for a in candidates if a.get("wallet")],
             [a.get("condition_id") for a in candidates if a.get("condition_id")]),
        )
        soft = {(row["wallet"], row["condition_id"]) for row in cur.fetchall()}
    finally:
        cur.close()

    kept = []
    for a in candidates:
        if int(a["id"]) in hard:
            continue
        pair = (a.get("wallet"), a.get("condition_id"))
        if pair in soft:
            continue
        kept.append(a)
    return kept
```

- [ ] **Step 4: Adjust `FakeCursor.fetchall` to match the real query shape**

Look back at the test `FakeCursor.fetchall`. The real query for soft dedup is:

```sql
SELECT wallet, condition_id FROM tweeted_alerts WHERE tweeted_at >= %s AND wallet = ANY(%s) AND condition_id = ANY(%s)
```

The `FakeCursor` in the test detects `"SELECT wallet, condition_id FROM tweeted_alerts"` as a substring — this matches. The hard dedup query is `"SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)"` which the test matches as `"SELECT alert_id FROM tweeted_alerts WHERE alert_id"` substring. Both work. No adjustment needed.

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: all tests pass (fetch tests + 4 new dedup tests).

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add filter_dedup with hard and 24h soft dedup rules"
```

---

## Task 6: `call_llm` — LLM decision + tweet composition with length retry

**Files:**
- Modify: `backend/twitter_bot.py` (add `SYSTEM_PROMPT`, `_build_user_message`, `call_llm`)
- Modify: `backend/test_twitter_bot.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_twitter_bot.py`:

```python
# ------------------------------------------------------------------ call_llm --

class FakeLLMClient:
    """Stand-in for openai.OpenAI. chat.completions.create returns canned output."""

    def __init__(self, responses):
        # `responses` is a list of dicts — each becomes one response body.
        self._responses = list(responses)
        self.calls = []
        # Mirror the nested structure the real client exposes.
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        body = self._responses.pop(0)
        content = body if isinstance(body, str) else json.dumps(body)
        choice = SimpleNamespace(message=SimpleNamespace(content=content))
        return SimpleNamespace(choices=[choice])


def test_call_llm_returns_skip_decision_cleanly():
    response = {
        "decision": "skip",
        "reason": "all candidates routine",
        "alert_ids": None,
        "tweet": None,
        "is_composite": False,
    }
    client = FakeLLMClient([response])
    top5 = [_alert(id=1)]

    result = tb.call_llm(top5, llm_client=client)

    assert result["decision"] == "skip"
    assert len(client.calls) == 1


def test_call_llm_returns_valid_post_decision_first_try():
    response = {
        "decision": "post",
        "reason": "whale on hot market",
        "alert_ids": [1],
        "tweet": "Short tweet. link in bio.",
        "is_composite": False,
    }
    client = FakeLLMClient([response])
    top5 = [_alert(id=1)]

    result = tb.call_llm(top5, llm_client=client)

    assert result["tweet"] == "Short tweet. link in bio."
    assert len(client.calls) == 1


def test_call_llm_retries_once_on_length_overshoot_and_succeeds():
    long_tweet = "x" * 300
    retry_tweet = "x" * 200
    first = {"decision": "post", "reason": "ok", "alert_ids": [1], "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "shorter", "alert_ids": [1], "tweet": retry_tweet, "is_composite": False}
    client = FakeLLMClient([first, second])
    top5 = [_alert(id=1)]

    result = tb.call_llm(top5, llm_client=client)

    assert result["tweet"] == retry_tweet
    assert len(client.calls) == 2
    # Retry should reference the length.
    retry_messages = client.calls[1]["messages"]
    assert any("260" in m["content"] for m in retry_messages if m["role"] == "user")


def test_call_llm_returns_overlong_result_when_retry_also_fails():
    long_tweet = "x" * 300
    first = {"decision": "post", "reason": "ok", "alert_ids": [1], "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "still long", "alert_ids": [1], "tweet": "x" * 280, "is_composite": False}
    client = FakeLLMClient([first, second])

    result = tb.call_llm([_alert(id=1)], llm_client=client)

    # call_llm does NOT itself judge validity — it returns what the LLM said.
    # Caller (validate_decision) decides. This test just asserts it tried twice.
    assert len(client.calls) == 2
    assert len(result["tweet"]) == 280
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the four `test_call_llm_*` tests fail with `AttributeError: module 'twitter_bot' has no attribute 'call_llm'`.

- [ ] **Step 3: Implement `SYSTEM_PROMPT`, `_build_user_message`, `call_llm`**

In `backend/twitter_bot.py`, add after `filter_dedup`:

```python
# --- LLM composition ---------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the social media voice for PolySpotter, a service that surfaces "
    "notable Polymarket bets from sharp wallets, whales, and coordinated flow.\n\n"

    "You'll be given up to 5 alerts from the last hour. Your job: write ONE "
    "tweet that's as engaging as possible — drawing on one OR multiple alerts "
    "— or skip the hour if nothing is compelling.\n\n"

    "## Single vs composite\n"
    "- If one alert clearly stands out, write a tight hook-driven tweet focused on it.\n"
    "- If 2+ alerts tell a bigger story together (same market, same wallet across "
    "markets, a theme like '3 whales all loaded up on Iran markets today'), "
    "compose a synthesis tweet.\n"
    "- Never force synthesis. If alerts are unrelated, just pick the best one.\n\n"

    "## Tweet rules\n"
    "- Max 260 characters (safety margin under X's 280 limit).\n"
    "- Hook-driven opening: lead with the most striking fact (dollar amount, "
    "win rate, timing).\n"
    "- Use specific numbers, not vague descriptors.\n"
    "- End with a CTA that drives clicks to bio, e.g., "
    "'→ link in bio', 'full details in bio 👀', 'who is this wallet? bio link'.\n"
    "- 1–2 relevant hashtags max. Prefer topic-specific over generic #Polymarket.\n"
    "- 0–2 emojis, only if they add something. No emoji spam.\n"
    "- No URLs. No @mentions of real users.\n"
    "- Never fabricate numbers or facts not in the alert data.\n"
    "- Write like a sharp trading desk analyst, not a corporate account.\n\n"

    "## Skip criteria\n"
    "If all 5 alerts are routine/low-signal, return decision=skip with a short reason.\n\n"

    "## Output format (strict JSON)\n"
    '{\n'
    '  "decision": "post" | "skip",\n'
    '  "reason": "short string",\n'
    '  "alert_ids": [<int>, ...] | null,\n'
    '  "tweet": "<string ≤260 chars | null>",\n'
    '  "is_composite": true | false\n'
    '}\n'
    "alert_ids must be integers taken from the alerts you were shown. "
    "If is_composite=false, alert_ids must contain exactly one id."
)


def _build_user_message(top5: list[dict]) -> str:
    """Build the JSON payload describing the 5 candidate alerts."""
    payload = []
    for a in top5:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "market_title": a.get("market_title"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "wallet_total_pnl": a.get("total_pnl"),
            "total_usd": a.get("total_usd"),
            "tags": a.get("tags") or [],
        })
    return json.dumps({"alerts": payload}, default=str)


def call_llm(top5: list[dict], *, llm_client) -> dict:
    """Send the top 5 alerts to GPT and parse its decision.

    Retries once if the returned tweet exceeds TWEET_MAX_CHARS, asking the model
    to shorten. Returns the raw decision dict (caller is responsible for any
    validation beyond length — e.g. alert_id membership).
    """
    user_msg = _build_user_message(top5)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    decision = _llm_decide(messages, llm_client=llm_client)

    # Length retry (only if decision is 'post' and tweet is over limit).
    tweet = decision.get("tweet") or ""
    if decision.get("decision") == "post" and len(tweet) > TWEET_MAX_CHARS:
        retry_messages = messages + [
            {"role": "assistant", "content": json.dumps(decision)},
            {"role": "user", "content": (
                f"Your tweet was {len(tweet)} characters, must be ≤{TWEET_MAX_CHARS}. "
                f"Shorten it, keep the hook and CTA. Return the same JSON format."
            )},
        ]
        decision = _llm_decide(retry_messages, llm_client=llm_client)

    return decision


def _llm_decide(messages: list[dict], *, llm_client) -> dict:
    """Call the model once and parse JSON out of the response."""
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=500,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: all 10 tests pass (2 fetch + 4 dedup + 4 llm).

- [ ] **Step 5: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add call_llm with system prompt and length-retry logic"
```

---

## Task 7: `validate_decision` — schema + alert_id membership checks

**Files:**
- Modify: `backend/twitter_bot.py` (add `validate_decision`)
- Modify: `backend/test_twitter_bot.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_twitter_bot.py`:

```python
# ---------------------------------------------------------- validate_decision --

def test_validate_decision_accepts_valid_single_post():
    d = {"decision": "post", "alert_ids": [1], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, top5_ids={1, 2, 3})
    assert ok
    assert err == ""


def test_validate_decision_accepts_skip():
    d = {"decision": "skip", "alert_ids": None, "tweet": None, "is_composite": False}
    ok, _ = tb.validate_decision(d, top5_ids={1, 2, 3})
    assert ok


def test_validate_decision_rejects_alert_id_not_in_input():
    d = {"decision": "post", "alert_ids": [99], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, top5_ids={1, 2, 3})
    assert not ok
    assert "99" in err


def test_validate_decision_rejects_tweet_over_max_length():
    d = {"decision": "post", "alert_ids": [1], "tweet": "x" * 300, "is_composite": False}
    ok, err = tb.validate_decision(d, top5_ids={1})
    assert not ok
    assert "length" in err.lower()


def test_validate_decision_rejects_empty_alert_ids_on_post():
    d = {"decision": "post", "alert_ids": [], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, top5_ids={1})
    assert not ok


def test_validate_decision_rejects_non_composite_with_multiple_ids():
    d = {"decision": "post", "alert_ids": [1, 2], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, top5_ids={1, 2})
    assert not ok
    assert "composite" in err.lower()


def test_validate_decision_accepts_composite_with_multiple_ids():
    d = {"decision": "post", "alert_ids": [1, 2], "tweet": "ok", "is_composite": True}
    ok, err = tb.validate_decision(d, top5_ids={1, 2, 3})
    assert ok


def test_validate_decision_rejects_unknown_decision_value():
    d = {"decision": "maybe", "alert_ids": [1], "tweet": "ok", "is_composite": False}
    ok, _ = tb.validate_decision(d, top5_ids={1})
    assert not ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the 8 new `test_validate_decision_*` tests fail with AttributeError.

- [ ] **Step 3: Implement `validate_decision`**

In `backend/twitter_bot.py`, add after `_llm_decide`:

```python
# --- Validation --------------------------------------------------------------

def validate_decision(decision: dict, top5_ids: set[int]) -> tuple[bool, str]:
    """Validate the LLM's decision dict. Returns (ok, error_message).

    Rules:
      - decision must be 'post' or 'skip'.
      - if 'skip', nothing else is checked.
      - if 'post':
          - alert_ids must be a non-empty list of ints all present in top5_ids.
          - tweet must be a non-empty string with length <= TWEET_MAX_CHARS.
          - if is_composite is False, alert_ids must have length 1.
    """
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision value: {d!r}"

    alert_ids = decision.get("alert_ids") or []
    if not isinstance(alert_ids, list) or not alert_ids:
        return False, "alert_ids must be a non-empty list when decision=post"

    try:
        int_ids = [int(i) for i in alert_ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {alert_ids!r}"

    unknown = [i for i in int_ids if i not in top5_ids]
    if unknown:
        return False, f"alert_ids contains ids not in input: {unknown}"

    is_composite = bool(decision.get("is_composite"))
    if not is_composite and len(int_ids) != 1:
        return False, "non-composite tweet must reference exactly one alert_id"

    tweet = decision.get("tweet") or ""
    if not isinstance(tweet, str) or not tweet.strip():
        return False, "tweet must be a non-empty string"
    if len(tweet) > TWEET_MAX_CHARS:
        return False, f"tweet length {len(tweet)} exceeds max {TWEET_MAX_CHARS}"

    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: 18 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add validate_decision for LLM output schema checks"
```

---

## Task 8: `post_tweet` — Tweepy call with dry-run support

**Files:**
- Modify: `backend/twitter_bot.py` (add `post_tweet`, `_build_twitter_client`)
- Modify: `backend/test_twitter_bot.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_twitter_bot.py`:

```python
# -------------------------------------------------------------- post_tweet --

class FakeTwitterClient:
    def __init__(self, tweet_id="1234567890", raise_exc=None):
        self._tweet_id = tweet_id
        self._raise = raise_exc
        self.calls = []

    def create_tweet(self, text):
        self.calls.append(text)
        if self._raise:
            raise self._raise
        return SimpleNamespace(data={"id": self._tweet_id, "text": text})


def test_post_tweet_posts_and_returns_tweet_id():
    client = FakeTwitterClient(tweet_id="42")
    result = tb.post_tweet("hello world", twitter_client=client, dry_run=False)
    assert result == "42"
    assert client.calls == ["hello world"]


def test_post_tweet_dry_run_does_not_call_client():
    client = FakeTwitterClient()
    result = tb.post_tweet("hello world", twitter_client=client, dry_run=True)
    # Dry run returns a synthetic id starting with 'dryrun-'
    assert result.startswith("dryrun-")
    assert client.calls == []


def test_post_tweet_propagates_client_exception():
    client = FakeTwitterClient(raise_exc=RuntimeError("429 rate limit"))
    with pytest.raises(RuntimeError, match="rate limit"):
        tb.post_tweet("hello", twitter_client=client, dry_run=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the three `test_post_tweet_*` tests fail with AttributeError.

- [ ] **Step 3: Implement `post_tweet` and `_build_twitter_client`**

In `backend/twitter_bot.py`, add after `validate_decision`:

```python
# --- Twitter client ----------------------------------------------------------

def _build_twitter_client() -> tweepy.Client:
    """Build a real Tweepy v2 client from env credentials (OAuth 1.0a user auth)."""
    return tweepy.Client(
        consumer_key=X_CONSUMER_KEY,
        consumer_secret=X_CONSUMER_KEY_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )


def post_tweet(text: str, *, twitter_client, dry_run: bool) -> str:
    """Post a tweet (or log it in dry-run mode) and return the tweet id.

    In dry-run mode, does not call the client and returns a synthetic id
    starting with 'dryrun-'. The caller uses the dry_run flag to decide
    whether to record the tweet in the DB (dry runs must not poison dedup).
    """
    if dry_run:
        log_event("dry_run_tweet", tweet=text)
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    response = twitter_client.create_tweet(text=text)
    data = getattr(response, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {response!r}")
    return tweet_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: 21 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add post_tweet helper with dry-run mode"
```

---

## Task 9: `record_tweet` — insert `tweeted_alerts` rows

**Files:**
- Modify: `backend/twitter_bot.py` (add `record_tweet`)
- Modify: `backend/test_twitter_bot.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_twitter_bot.py`:

```python
# ------------------------------------------------------------ record_tweet --

class RecordingCursor:
    """Captures executemany/execute calls in order."""

    def __init__(self):
        self.executions = []

    def execute(self, query, params=None):
        self.executions.append(("execute", query, params))

    def executemany(self, query, rows):
        self.executions.append(("executemany", query, list(rows)))

    def close(self):
        pass


class RecordingConn:
    def __init__(self):
        self.cur = RecordingCursor()
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_record_tweet_inserts_one_row_for_single_alert():
    conn = RecordingConn()
    alerts = [_alert(id=7, wallet="0xw", condition_id="0xc")]
    tb.record_tweet(
        alerts=alerts,
        tweet_id="100",
        tweet_text="hello",
        db_conn=conn,
    )
    # One execute call with the correct values.
    kind, query, params = conn.cur.executions[0]
    assert "INSERT INTO tweeted_alerts" in query
    assert params == (7, "0xw", "0xc", "100", "hello") or params == [7, "0xw", "0xc", "100", "hello"]
    assert conn.commits == 1


def test_record_tweet_inserts_multiple_rows_for_composite():
    conn = RecordingConn()
    alerts = [
        _alert(id=1, wallet="0xA", condition_id="0xm1"),
        _alert(id=2, wallet="0xB", condition_id="0xm2"),
        _alert(id=3, wallet="0xC", condition_id="0xm3"),
    ]
    tb.record_tweet(
        alerts=alerts,
        tweet_id="500",
        tweet_text="composite tweet",
        db_conn=conn,
    )
    # Should be executemany with 3 rows all sharing tweet_id and tweet_text.
    kind, query, rows = conn.cur.executions[0]
    assert kind == "executemany"
    assert "INSERT INTO tweeted_alerts" in query
    assert len(rows) == 3
    assert {r[3] for r in rows} == {"500"}
    assert {r[4] for r in rows} == {"composite tweet"}
    assert {r[0] for r in rows} == {1, 2, 3}
    assert conn.commits == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the two `test_record_tweet_*` tests fail with AttributeError.

- [ ] **Step 3: Implement `record_tweet`**

In `backend/twitter_bot.py`, add after `post_tweet`:

```python
# --- Record ------------------------------------------------------------------

def record_tweet(
    *,
    alerts: list[dict],
    tweet_id: str,
    tweet_text: str,
    db_conn,
) -> None:
    """Insert one tweeted_alerts row per alert, all sharing tweet_id/tweet_text.

    Uses ON CONFLICT DO NOTHING so re-runs (after a DB failure mid-write, for
    example) don't crash. That said, the caller swallows errors from this
    function anyway per the 'record_error' policy.
    """
    rows = [
        (int(a["id"]), a.get("wallet") or "", a.get("condition_id") or "", tweet_id, tweet_text)
        for a in alerts
    ]
    cur = db_conn.cursor()
    try:
        if len(rows) == 1:
            cur.execute(
                """
                INSERT INTO tweeted_alerts (alert_id, wallet, condition_id, tweet_id, tweet_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                rows[0],
            )
        else:
            cur.executemany(
                """
                INSERT INTO tweeted_alerts (alert_id, wallet, condition_id, tweet_id, tweet_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                rows,
            )
    finally:
        cur.close()
    db_conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: 23 tests pass total.

- [ ] **Step 5: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Add record_tweet to insert tweeted_alerts rows"
```

---

## Task 10: `main()` — wire everything together + end-to-end test

**Files:**
- Modify: `backend/twitter_bot.py` (add `main`, replace placeholder entrypoint)
- Modify: `backend/test_twitter_bot.py` (add end-to-end test)

- [ ] **Step 1: Write the failing end-to-end test**

Append to `backend/test_twitter_bot.py`:

```python
# ------------------------------------------------------------ end-to-end -----

def test_main_runs_full_flow_successfully(monkeypatch):
    """Integration-style test: exercise main() end-to-end with all fakes."""
    # Two recent candidates, one has score just above the min, one below.
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [
            _alert(id=1, composite_score=9.0,
                   created_at=(now - timedelta(minutes=10)).isoformat()),
            _alert(id=2, composite_score=6.0,
                   created_at=(now - timedelta(minutes=15)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)

    llm = FakeLLMClient([{
        "decision": "post",
        "reason": "hot",
        "alert_ids": [1],
        "tweet": "Whale dropped $25k. link in bio",
        "is_composite": False,
    }])

    twitter = FakeTwitterClient(tweet_id="99")
    conn = RecordingConn()

    # Also need dedup queries to return empty (no prior tweets). RecordingConn
    # returns no rows because RecordingCursor has no fetchall — so we swap to
    # a combined cursor:

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn.cur = CombinedCursor()

    exit_code = tb.main(
        http=http,
        llm_client=llm,
        twitter_client=twitter,
        db_conn=conn,
    )

    assert exit_code == 0
    assert twitter.calls == ["Whale dropped $25k. link in bio"]
    # Should have written to tweeted_alerts (one execute for the insert + some
    # for dedup SELECTs). Look for the INSERT specifically.
    insert_calls = [e for e in conn.cur.executions if "INSERT INTO tweeted_alerts" in e[1]]
    assert len(insert_calls) == 1


def test_main_skips_cleanly_when_llm_says_skip(monkeypatch):
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([{
        "decision": "skip",
        "reason": "nothing compelling",
        "alert_ids": None,
        "tweet": None,
        "is_composite": False,
    }])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 0
    assert twitter.calls == []
    insert_calls = [e for e in conn.cur.executions if "INSERT INTO tweeted_alerts" in e[1]]
    assert insert_calls == []


def test_main_exits_zero_with_no_candidates(monkeypatch):
    http = FakeHTTP({"alerts": [], "total": 0, "page": 1, "per_page": 100})
    llm = FakeLLMClient([])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 0
    assert twitter.calls == []
    assert len(llm.calls) == 0  # LLM should not be called


def test_main_exits_one_on_validation_error(monkeypatch):
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    # LLM claims alert_id=999 which wasn't in our input. No retry triggers
    # because this isn't a length problem.
    llm = FakeLLMClient([{
        "decision": "post", "reason": "x", "alert_ids": [999],
        "tweet": "ok", "is_composite": False,
    }])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 1
    assert twitter.calls == []


def test_main_post_error_does_not_write_to_db(monkeypatch):
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([{
        "decision": "post", "reason": "x", "alert_ids": [1],
        "tweet": "ok", "is_composite": False,
    }])
    twitter = FakeTwitterClient(raise_exc=RuntimeError("429 rate limit"))

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 1
    insert_calls = [e for e in conn.cur.executions if "INSERT INTO tweeted_alerts" in e[1]]
    assert insert_calls == []


def test_main_dry_run_does_not_post_or_record(monkeypatch):
    monkeypatch.setattr(tb, "TWITTER_BOT_DRY_RUN", True)
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([{
        "decision": "post", "reason": "x", "alert_ids": [1],
        "tweet": "hello link in bio", "is_composite": False,
    }])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 0
    assert twitter.calls == []          # dry run: no real post
    insert_calls = [e for e in conn.cur.executions if "INSERT INTO tweeted_alerts" in e[1]]
    assert insert_calls == []           # dry run: no recording
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: all 6 new `test_main_*` tests fail with `TypeError: main() got an unexpected keyword argument 'http'` (or AttributeError if `main` doesn't exist yet).

- [ ] **Step 3: Implement `main` and the real entrypoint**

In `backend/twitter_bot.py`, **remove the placeholder `if __name__ == "__main__": sys.exit(0)` at the bottom** and replace it with the following. Add `main` before the `__main__` block:

```python
# --- Entrypoint --------------------------------------------------------------

def main(
    *,
    http=None,
    llm_client=None,
    twitter_client=None,
    db_conn=None,
) -> int:
    """Run one pass of the Twitter bot. Returns an exit code (0 = success, 1 = error).

    All dependencies can be injected for testing. When any are None, the real
    versions are constructed from environment config.
    """
    run_id = uuid.uuid4().hex[:8]
    log_event("run_start", run_id=run_id,
              api_url=POLYSPOTTER_API_URL,
              min_score=TWITTER_BOT_MIN_SCORE,
              dry_run=TWITTER_BOT_DRY_RUN)

    # Lazy-construct real deps if not injected.
    if http is None:
        http = requests
    owns_conn = False
    if db_conn is None:
        db_conn = psycopg2.connect(DATABASE_URL)
        owns_conn = True
    if llm_client is None:
        llm_client = OpenAI(
            base_url=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
        )
    if twitter_client is None:
        twitter_client = _build_twitter_client()

    try:
        # 1. Fetch.
        try:
            candidates = fetch_recent_alerts(POLYSPOTTER_API_URL, TWITTER_BOT_MIN_SCORE, http=http)
        except Exception as e:
            log_event("fetch_error", run_id=run_id, error=str(e))
            return 1

        log_event("candidates_fetched", run_id=run_id, count=len(candidates))

        # 2. Dedup.
        after_dedup = filter_dedup(candidates, db_conn)
        log_event("after_dedup", run_id=run_id, count=len(after_dedup))

        # 3. Top 5 by composite_score.
        top5 = sorted(after_dedup, key=lambda a: a.get("composite_score", 0), reverse=True)[:5]
        if not top5:
            log_event("no_candidates", run_id=run_id)
            log_event("run_end", run_id=run_id, posted=False, reason="no_candidates")
            return 0

        # 4. LLM.
        try:
            decision = call_llm(top5, llm_client=llm_client)
        except Exception as e:
            log_event("llm_error", run_id=run_id, error=str(e))
            return 1

        if decision.get("decision") == "skip":
            log_event("llm_skip", run_id=run_id, reason=decision.get("reason"))
            log_event("run_end", run_id=run_id, posted=False, reason="llm_skip")
            return 0

        # 5. Validate.
        top5_ids = {int(a["id"]) for a in top5}
        ok, err = validate_decision(decision, top5_ids)
        if not ok:
            log_event("validation_error", run_id=run_id, error=err, decision=decision)
            return 1

        # 6. Post.
        picked_ids = [int(i) for i in decision["alert_ids"]]
        picked_alerts = [a for a in top5 if int(a["id"]) in picked_ids]
        tweet_text = decision["tweet"]
        try:
            tweet_id = post_tweet(tweet_text, twitter_client=twitter_client, dry_run=TWITTER_BOT_DRY_RUN)
        except Exception as e:
            log_event("post_error", run_id=run_id, error=str(e))
            return 1

        log_event("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=picked_ids,
                  is_composite=bool(decision.get("is_composite")))

        # 7. Record (skip in dry run).
        if TWITTER_BOT_DRY_RUN:
            log_event("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id)
            return 0

        try:
            record_tweet(alerts=picked_alerts, tweet_id=tweet_id, tweet_text=tweet_text, db_conn=db_conn)
        except Exception as e:
            log_event("record_error", run_id=run_id, error=str(e))
            # Intentionally still success: the tweet is already live.
            log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False)
            return 0

        log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True)
        return 0
    finally:
        if owns_conn:
            try:
                db_conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: all 29 tests pass (23 unit + 6 e2e).

- [ ] **Step 5: Smoke-test dry-run mode locally**

This requires `DATABASE_URL`, `AZURE_OPENAI_API_KEY` set. Set `TWITTER_BOT_DRY_RUN=true` so nothing is posted and no rows are written.

```bash
source venv/bin/activate
cd backend
TWITTER_BOT_DRY_RUN=true python twitter_bot.py
```

Expected: single-line JSON log events — `run_start`, `candidates_fetched`, `after_dedup`, then either `no_candidates` / `llm_skip` / `dry_run_tweet` + `posted` + `run_end`. Exit code 0.

If you see `fetch_error`, check that `https://api.polyspotter.com/api/alerts?per_page=100&min_score=5.0` returns a 200 from your shell.

If you see `llm_error`, check `AZURE_OPENAI_API_KEY`.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "Wire twitter_bot main() end-to-end with error routing"
```

---

## Task 11: Deploy as a Railway cron service

**Files:** no code changes — this is a Railway configuration task. Document commands/actions so the engineer doesn't need to guess.

- [ ] **Step 1: Confirm environment variables on Railway**

In the Railway dashboard, for the new Twitter bot service (created in Step 2 below), set the following environment variables. Copy values from your local `.env` where applicable.

Required:
- `DATABASE_URL` — same value as the backend API service (shared DB)
- `AZURE_OPENAI_API_KEY` — same value as the backend API service
- `X_CONSUMER_KEY`, `X_CONSUMER_KEY_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`

Optional (with defaults if unset):
- `POLYSPOTTER_API_URL` (default `https://api.polyspotter.com`)
- `TWITTER_BOT_MIN_SCORE` (default `5.0`)
- `TWITTER_BOT_DRY_RUN` — set to `true` for the first run or two, then unset/set to `false`

- [ ] **Step 2: Create a new Railway service for the bot**

In Railway:
1. Open the `polybot` Railway project.
2. Add Service → Deploy from GitHub → select the same repo (`polybot`).
3. In the new service's settings:
    - Root directory: `/` (repo root)
    - Build command: `pip install -r backend/requirements.txt`
    - Start command: `python backend/twitter_bot.py`
4. Under Settings → Service → "Cron Schedule", set: `0 * * * *` (top of every hour, UTC).

Railway cron services run the start command once per trigger, then exit. This matches our single-shot design exactly.

- [ ] **Step 3: First run in dry-run mode**

With `TWITTER_BOT_DRY_RUN=true` set on the service, trigger the service manually from the Railway UI ("Run"). Check the logs: you should see `run_start` through `run_end` with no errors.

If the log shows `fetch_error`, verify `POLYSPOTTER_API_URL` and that the API service is up.
If it shows `llm_error`, check `AZURE_OPENAI_API_KEY`.
If it shows `dry_run_tweet`, inspect the tweet text and make sure it looks sane.

- [ ] **Step 4: Go live**

Remove or set `TWITTER_BOT_DRY_RUN=false` on the Railway service. Manually trigger once more and confirm a real tweet is posted and a `tweeted_alerts` row is created:

```bash
psql "$DATABASE_URL" -c "SELECT alert_id, tweet_id, tweeted_at FROM tweeted_alerts ORDER BY tweeted_at DESC LIMIT 5;"
```

Expected: the newly-inserted row(s) visible.

- [ ] **Step 5: Verify cron is scheduled**

Check the Railway service's cron schedule is `0 * * * *` and the next scheduled run is at the top of the next hour.

- [ ] **Step 6: Commit any final doc updates**

No code changes here, but if you created a deployment README snippet or updated CLAUDE.md to mention the bot service, commit it now.

```bash
git status
# If there's anything to commit:
git add <files>
git commit -m "Note Twitter bot Railway service in docs"
```

---

## Self-review notes

- Spec coverage: every requirement in the spec (fetch → dedup → top 5 → LLM → validate → length retry → post → record → dry run → logging → testing) maps to a task above.
- Types are consistent: `alert_id` is `int` throughout (matches `AlertOut.id` and the new `tweeted_alerts.alert_id BIGINT`).
- No placeholders — every step contains exact code or exact commands.
- The test file in Task 4 introduces fakes that later tasks reuse (`FakeHTTP`, `FakeLLMClient`, `FakeTwitterClient`, `FakeCursor`, `RecordingCursor`, `RecordingConn`). The CombinedCursor pattern in Task 10 overrides `fetchall` to avoid needing to modify the existing fakes.

## Open follow-ups (not in scope for this plan)

- Add a "backfill" mode that lets the bot retroactively tweet about historic alerts (e.g., when the bot is first turned on) — would need explicit user trigger, not on by default.
- Observability: push key events to a separate logging service if Railway's stdout log retention isn't sufficient.
- Rate limit-aware retry queue if we decide to post more than once per hour.
