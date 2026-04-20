# Twitter Bot Agentic Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-pass LLM composer in `backend/twitter_bot.py` with an agentic composer that can call up to 5 curated research tools (hosted API, Railway Postgres, local `polybot.db`, Gamma API) before writing the tweet. Same input and output contract as today's bot — this is a drop-in upgrade of one step, not a rewrite.

**Architecture:** A new module `backend/twitter_bot_agent.py` houses 16 read-only tools, a dispatcher with JMESPath projection and 8KB truncation, and a function-calling loop against GPT-5.4 via Azure OpenAI. `backend/twitter_bot.py` wires the agent in place of `call_llm()` and threads a `polybot.db` SQLite connection through. No backend schema changes, no new endpoints, no langchain.

**Tech Stack:** Python 3.13, OpenAI SDK (native function calling), `psycopg2` (Postgres), `sqlite3` (stdlib), `requests` (HTTP), `jmespath` (new dep), `pytest` with injected fakes.

**Design doc:** [2026-04-19-twitter-bot-agentic-composer-design.md](../specs/2026-04-19-twitter-bot-agentic-composer-design.md)

**Smoke test (dry-run against live API):** Ran 2026-04-19, produced composite tweet "Utah just saw a coordinated shove: 14 wallets put in $46.3k across 24 buys, including one bettor with a 79% win rate (+$76k)..." (228 chars, 2 alert_ids). Agent cited specific win rates and price-movement data only reachable via tool calls. No errors.

**Repo layout while executing this plan:**
- Worktree root: `/home/bhavya/git/polybot/.worktrees/twitter-agent/`
- Branch: `feature/twitter-agentic-composer`
- All paths below are **relative to the worktree root** unless stated otherwise.

---

## Prerequisites (once before Task 1)

Activate a Python venv inside the worktree so tasks can run tests.

```bash
cd /home/bhavya/git/polybot/.worktrees/twitter-agent
python3.13 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

Verify the existing test suite passes on a fresh worktree:

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: all 29 tests pass. If any fail, stop — investigate before proceeding.

---

## Task 1: Bootstrap — add `jmespath` dep and envelope helpers

Create the new module with the three primitives every tool relies on: response envelope, JMESPath projection, and 8KB truncation.

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/twitter_bot_agent.py`
- Create: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Add `jmespath` to requirements**

Append to `backend/requirements.txt`:

```
jmespath>=1.0
```

Install it:

```bash
source venv/bin/activate
pip install 'jmespath>=1.0'
```

- [ ] **Step 2: Write failing tests for envelope helpers**

Create `backend/test_twitter_bot_agent.py`:

```python
"""
Tests for backend/twitter_bot_agent.py.

Run: cd backend && pytest test_twitter_bot_agent.py -v
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/nope")
os.environ.setdefault("POLYSPOTTER_API_URL", "https://api.example.test")

import twitter_bot_agent as agent


# -------------------------------------------------------------- envelope ----

def test_build_envelope_wraps_data():
    env = agent.build_envelope({"a": 1, "b": 2})
    assert env == {"data": {"a": 1, "b": 2}, "truncated": False}


def test_build_envelope_error_shape():
    env = agent.build_envelope(None, error="projection failed: bad syntax")
    assert env == {"error": "projection failed: bad syntax"}


def test_apply_projection_returns_projected_value():
    raw = {"bet_history": [1, 2, 3, 4]}
    result = agent.apply_projection(raw, "length(bet_history)")
    assert result == 4


def test_apply_projection_returns_raw_when_projection_is_none():
    raw = {"a": 1}
    assert agent.apply_projection(raw, None) == raw


def test_apply_projection_raises_on_bad_expression():
    with pytest.raises(agent.ProjectionError):
        agent.apply_projection({"a": 1}, "invalid(")


def test_truncate_payload_leaves_small_payloads_alone():
    small = {"x": 1}
    result, truncated = agent.truncate_payload(small, cap_bytes=8192)
    assert result == small
    assert truncated is False


def test_truncate_payload_trims_top_level_array():
    big = [{"x": "y" * 100} for _ in range(1000)]
    result, truncated = agent.truncate_payload(big, cap_bytes=512)
    assert truncated is True
    assert isinstance(result, list)
    assert len(result) < 1000
    # Serialized result must fit within the cap.
    assert len(json.dumps(result, default=str)) <= 512


def test_truncate_payload_stringifies_oversize_dict():
    big = {f"k{i}": "x" * 100 for i in range(100)}
    result, truncated = agent.truncate_payload(big, cap_bytes=512)
    assert truncated is True
    assert isinstance(result, str)
    assert len(result) <= 512
    assert result.endswith("…")
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'twitter_bot_agent'` or similar.

- [ ] **Step 4: Implement the envelope helpers**

Create `backend/twitter_bot_agent.py`:

```python
"""
Agentic composer for backend/twitter_bot.py.

The bot hands this module the top 5 recent alerts. compose_tweet() drives a
GPT-5.4 function-calling loop with up to 5 tool calls, then returns the same
decision dict the bot expects (post/skip, alert_ids, tweet, is_composite).

All tools are read-only. No schema changes. No new endpoints. No langchain.
"""

from __future__ import annotations

import json
from typing import Any

import jmespath


# --- Constants ---------------------------------------------------------------

MAX_TOOL_CALLS = 5
MAX_ITERATIONS = 7  # 5 tool rounds + 1 forcing + 1 safety
RESPONSE_CAP_BYTES = 8192


# --- Errors ------------------------------------------------------------------

class ProjectionError(Exception):
    """Raised when a JMESPath expression fails to compile or evaluate."""


class AgentOutputError(Exception):
    """Raised when the agent fails to produce valid final JSON."""


# --- Envelope helpers --------------------------------------------------------

def build_envelope(data: Any, *, error: str | None = None, truncated: bool = False) -> dict:
    """Build the response envelope the LLM sees for every tool call."""
    if error is not None:
        return {"error": error}
    return {"data": data, "truncated": truncated}


def apply_projection(raw: Any, projection: str | None) -> Any:
    """Evaluate a JMESPath projection against raw data, or return raw if projection is None."""
    if projection is None:
        return raw
    try:
        compiled = jmespath.compile(projection)
    except jmespath.exceptions.ParseError as exc:
        raise ProjectionError(f"invalid: {exc}") from exc
    try:
        return compiled.search(raw)
    except Exception as exc:
        raise ProjectionError(f"failed: {exc}") from exc


def truncate_payload(data: Any, *, cap_bytes: int = RESPONSE_CAP_BYTES) -> tuple[Any, bool]:
    """Truncate a payload to fit within cap_bytes when JSON-serialized.

    - Top-level lists get trimmed item-by-item from the end.
    - Dicts (or other values) get JSON-stringified and tail-cut with `…` suffix.
    Returns (possibly-truncated-value, was_truncated).
    """
    serialized = json.dumps(data, default=str)
    if len(serialized) <= cap_bytes:
        return data, False

    if isinstance(data, list):
        trimmed = list(data)
        while trimmed and len(json.dumps(trimmed, default=str)) > cap_bytes:
            trimmed.pop()
        return trimmed, True

    # Fall-through: dict, scalar, or anything else. Stringify and cut.
    return serialized[: cap_bytes - 1] + "…", True
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/requirements.txt backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add twitter_bot_agent module skeleton with envelope helpers

Introduces apply_projection (JMESPath), build_envelope, and truncate_payload
— the three primitives every tool dispatch will use. No tools yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: HTTP tool helper + `get_wallet_profile` as TDD template

Build the shared HTTP helper used by tools 1-4 and 7, plus the first tool end-to-end as the pattern.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests for `_http_get_json` and `get_wallet_profile`**

Append to `backend/test_twitter_bot_agent.py`:

```python
# -------------------------------------------------------------- http helper --

class FakeHTTP:
    """Canned-response requests substitute, also records calls."""

    def __init__(self, responses):
        # responses: dict mapping URL -> body (dict) OR a single body dict
        self._responses = responses
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if isinstance(self._responses, dict):
            body = self._responses.get(url, {})
        else:
            body = self._responses
        resp = SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: body
        resp.raise_for_status = lambda: None
        return resp


class FailingHTTP:
    """Raises requests.exceptions.Timeout on every call."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        import requests
        self.calls.append(url)
        raise requests.exceptions.Timeout("fake timeout")


def test_http_get_json_returns_parsed_body():
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": {"wallet": "0xabc", "wins": 7}})
    result = agent._http_get_json("https://api.example.test/api/wallets/0xabc", http=http, timeout=5)
    assert result == {"wallet": "0xabc", "wins": 7}


def test_http_get_json_surfaces_timeout_as_exception():
    http = FailingHTTP()
    with pytest.raises(agent.HTTPToolError):
        agent._http_get_json("https://api.example.test/x", http=http, timeout=5)


# -------------------------------------------------------- get_wallet_profile --

def test_get_wallet_profile_returns_full_envelope():
    body = {"wallet": "0xabc", "wins": 7, "bet_history": [{"won": True}, {"won": False}]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": body})

    env = agent.get_wallet_profile(wallet="0xabc", http=http, api_url="https://api.example.test")

    assert env["data"] == body
    assert env["truncated"] is False


def test_get_wallet_profile_applies_projection():
    body = {"wallet": "0xabc", "bet_history": [1, 2, 3, 4, 5]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": body})

    env = agent.get_wallet_profile(
        wallet="0xabc", projection="length(bet_history)",
        http=http, api_url="https://api.example.test",
    )

    assert env["data"] == 5


def test_get_wallet_profile_bad_projection_returns_error():
    http = FakeHTTP({"https://api.example.test/api/wallets/0xabc": {"a": 1}})
    env = agent.get_wallet_profile(
        wallet="0xabc", projection="invalid(",
        http=http, api_url="https://api.example.test",
    )
    assert "error" in env
    assert "projection" in env["error"]


def test_get_wallet_profile_http_error_returns_error():
    env = agent.get_wallet_profile(
        wallet="0xabc", http=FailingHTTP(), api_url="https://api.example.test",
    )
    assert "error" in env
    assert "http" in env["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: the new tests fail with `AttributeError: module 'twitter_bot_agent' has no attribute '_http_get_json'` (or `get_wallet_profile`). Previously-passing tests still pass.

- [ ] **Step 3: Implement `_http_get_json` and `get_wallet_profile`**

Append to `backend/twitter_bot_agent.py`:

```python
# --- HTTP helper -------------------------------------------------------------

HTTP_TIMEOUT_SECONDS = 5


class HTTPToolError(Exception):
    """Raised for HTTP failures (timeout, non-2xx, bad JSON)."""


def _http_get_json(url: str, *, http, params: dict | None = None, timeout: int = HTTP_TIMEOUT_SECONDS) -> Any:
    """GET a URL and return parsed JSON, or raise HTTPToolError."""
    try:
        resp = http.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPToolError(f"{type(exc).__name__}: {exc}") from exc


def _safe_tool(fn):
    """Wrap a tool so exceptions become error envelopes, and apply projection + truncation.

    The wrapped tool must return raw data (any JSON-serializable value). The
    decorator applies projection (if `projection` kwarg is set), truncates to
    8KB, and wraps the result in an envelope. Exceptions surface as error
    envelopes.
    """
    def wrapped(*args, projection: str | None = None, **kwargs):
        try:
            raw = fn(*args, **kwargs)
        except ProjectionError as exc:
            return build_envelope(None, error=f"projection {exc}")
        except HTTPToolError as exc:
            return build_envelope(None, error=f"http: {exc}")
        except Exception as exc:
            return build_envelope(None, error=f"{type(exc).__name__}: {exc}")

        try:
            projected = apply_projection(raw, projection)
        except ProjectionError as exc:
            return build_envelope(None, error=f"projection {exc}")

        truncated_value, was_truncated = truncate_payload(projected)
        return build_envelope(truncated_value, truncated=was_truncated)

    wrapped.__name__ = fn.__name__
    wrapped.__wrapped__ = fn
    return wrapped


# --- Backend API tools -------------------------------------------------------

@_safe_tool
def get_wallet_profile(*, wallet: str, http, api_url: str) -> Any:
    """Profile + recent alerts (≤10) + bet history (≤20) for a wallet."""
    url = f"{api_url.rstrip('/')}/api/wallets/{wallet}"
    return _http_get_json(url, http=http)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all tests pass (8 from Task 1 + 6 new = 14).

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add HTTP helper and get_wallet_profile tool

Introduces _http_get_json, _safe_tool decorator (applies projection +
truncation + error envelope), and the first curated tool as the TDD
template for the remaining HTTP-backed tools.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Remaining HTTP-backed backend tools

Add the other four tools that wrap backend API endpoints: `get_alert_detail`, `get_market_price_history`, `get_market_holders`, `get_live_market`. Same pattern as `get_wallet_profile`.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ---------------------------------------------------- get_alert_detail --

def test_get_alert_detail_calls_correct_endpoint():
    body = {"id": 42, "trades": [], "signals": [{"strategy": "new_wallet_large_bet", "severity": 4.0}]}
    http = FakeHTTP({"https://api.example.test/api/alerts/42": body})
    env = agent.get_alert_detail(alert_id=42, http=http, api_url="https://api.example.test")
    assert env["data"]["id"] == 42
    assert http.calls[0]["url"] == "https://api.example.test/api/alerts/42"


# ------------------------------------------ get_market_price_history --

def test_get_market_price_history_passes_hours_param():
    body = {"candles": [{"t": 1, "p": 0.5}]}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/price-history": body})
    env = agent.get_market_price_history(
        condition_id="0xcond", hours=12,
        http=http, api_url="https://api.example.test",
    )
    assert env["data"] == body
    assert http.calls[0]["params"] == {"hours": 12}


def test_get_market_price_history_defaults_to_24_hours():
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/price-history": {"candles": []}})
    agent.get_market_price_history(
        condition_id="0xcond", http=http, api_url="https://api.example.test",
    )
    assert http.calls[0]["params"] == {"hours": 24}


# ------------------------------------------------- get_market_holders --

def test_get_market_holders_returns_holder_data():
    body = {"holders": {"Yes": [{"wallet": "0x1", "shares": 100}]}}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/holders": body})
    env = agent.get_market_holders(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body


# ----------------------------------------------------- get_live_market --

def test_get_live_market_returns_live_data():
    body = {"state": "live", "score": "2-1"}
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/live": body})
    env = agent.get_live_market(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 5 new tests fail with `AttributeError`. Prior tests still pass.

- [ ] **Step 3: Implement the tools**

Append to `backend/twitter_bot_agent.py` (below `get_wallet_profile`):

```python
@_safe_tool
def get_alert_detail(*, alert_id: int, http, api_url: str) -> Any:
    """Full trades + signals for a single alert."""
    url = f"{api_url.rstrip('/')}/api/alerts/{int(alert_id)}"
    return _http_get_json(url, http=http)


@_safe_tool
def get_market_price_history(*, condition_id: str, hours: int = 24, http, api_url: str) -> Any:
    """Price candles for a market over the last N hours."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/price-history"
    return _http_get_json(url, http=http, params={"hours": int(hours)})


@_safe_tool
def get_market_holders(*, condition_id: str, http, api_url: str) -> Any:
    """Top holders per outcome for a market."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/holders"
    return _http_get_json(url, http=http)


@_safe_tool
def get_live_market(*, condition_id: str, http, api_url: str) -> Any:
    """Live sports/event state for a market, when available."""
    url = f"{api_url.rstrip('/')}/api/market/{condition_id}/live"
    return _http_get_json(url, http=http)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 19 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add alert_detail, price_history, holders, live_market tools

Covers four remaining HTTP-backed backend API tools using the _safe_tool
template. All follow the same envelope + projection + truncation contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Postgres helper + Postgres-backed tools

Add `get_market_alerts`, `get_event_alerts`, `search_alerts_by_tag`. These run SELECTs against Railway Postgres via an injected psycopg2-style connection.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# --------------------------------------------------------- Postgres fakes ---

class FakePgCursor:
    """Minimal psycopg2 cursor substitute with canned rows per query pattern."""

    def __init__(self, rows_by_marker):
        # rows_by_marker: dict mapping a substring marker -> list of RealDict-like rows
        self._rows_by_marker = rows_by_marker
        self._rows = []
        self.last_query = None
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params
        self._rows = []
        for marker, rows in self._rows_by_marker.items():
            if marker in query:
                self._rows = rows
                return
        # No marker matched — return empty.

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakePgConn:
    def __init__(self, cursor):
        self._cur = cursor

    def cursor(self, cursor_factory=None):
        return self._cur

    def commit(self):
        pass


# ------------------------------------------------------- get_market_alerts ---

def test_get_market_alerts_returns_rows():
    rows = [
        {"id": 1, "composite_score": 12.0, "wallet": "0xa", "total_usd": 10000,
         "llm_headline": "hd1", "created_at": "2026-04-19T12:00:00Z"},
        {"id": 2, "composite_score": 11.0, "wallet": "0xb", "total_usd": 8000,
         "llm_headline": "hd2", "created_at": "2026-04-19T11:00:00Z"},
    ]
    cur = FakePgCursor({"FROM alerts WHERE condition_id": rows})
    conn = FakePgConn(cur)
    env = agent.get_market_alerts(condition_id="0xcond", limit=10, db_conn_pg=conn)
    assert len(env["data"]) == 2
    assert env["data"][0]["id"] == 1
    assert cur.last_params == ("0xcond", 10)


# ------------------------------------------------------- get_event_alerts ---

def test_get_event_alerts_queries_event_slug():
    rows = [{"id": 7, "composite_score": 15.0, "wallet": "0xz", "total_usd": 20000,
             "llm_headline": "h", "market_title": "mt", "created_at": "2026-04-19T10:00:00Z"}]
    cur = FakePgCursor({"FROM alerts WHERE event_slug": rows})
    conn = FakePgConn(cur)
    env = agent.get_event_alerts(event_slug="my-event", limit=20, db_conn_pg=conn)
    assert env["data"][0]["id"] == 7
    assert cur.last_params == ("my-event", 20)


# ---------------------------------------------------- search_alerts_by_tag ---

def test_search_alerts_by_tag_filters_by_tag_and_window():
    rows = [{"id": 100, "composite_score": 9.0, "wallet": "0x1", "market_title": "x",
             "total_usd": 5000, "llm_headline": "hh", "created_at": "2026-04-19T08:00:00Z"}]
    cur = FakePgCursor({"tags::jsonb @>": rows})
    conn = FakePgConn(cur)
    env = agent.search_alerts_by_tag(tag="Iran", hours=12, limit=5, db_conn_pg=conn)
    assert env["data"][0]["id"] == 100
    # First param is the JSON-encoded tag array.
    assert cur.last_params[0] == '["Iran"]'
    assert cur.last_params[1] == 12
    assert cur.last_params[2] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 3 new tests fail with `AttributeError`. Prior pass.

- [ ] **Step 3: Implement the Postgres tools**

Append to `backend/twitter_bot_agent.py`:

```python
# --- Postgres tools ----------------------------------------------------------

from psycopg2.extras import RealDictCursor


def _pg_fetchall(db_conn_pg, query: str, params: tuple) -> list[dict]:
    """Run a SELECT and return RealDictCursor rows as plain dicts."""
    cur = db_conn_pg.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


@_safe_tool
def get_market_alerts(*, condition_id: str, limit: int = 10, db_conn_pg) -> Any:
    """Other alerts on the same market (highest composite_score first)."""
    query = """
        SELECT id, composite_score, wallet, total_usd, llm_headline, created_at
        FROM alerts
        WHERE condition_id = %s
        ORDER BY composite_score DESC
        LIMIT %s
    """
    return _pg_fetchall(db_conn_pg, query, (condition_id, int(limit)))


@_safe_tool
def get_event_alerts(*, event_slug: str, limit: int = 20, db_conn_pg) -> Any:
    """Alerts on sibling markets in the same event."""
    query = """
        SELECT id, composite_score, wallet, market_title, condition_id,
               total_usd, llm_headline, created_at
        FROM alerts
        WHERE event_slug = %s
        ORDER BY composite_score DESC
        LIMIT %s
    """
    return _pg_fetchall(db_conn_pg, query, (event_slug, int(limit)))


@_safe_tool
def search_alerts_by_tag(*, tag: str, hours: int = 24, limit: int = 20, db_conn_pg) -> Any:
    """Alerts from the last N hours whose tags array contains this tag.

    Thematic synthesis, e.g., tag="Iran" → every Iran-tagged alert in the window.
    """
    query = """
        SELECT id, composite_score, wallet, market_title, condition_id,
               total_usd, llm_headline, created_at
        FROM alerts
        WHERE tags::jsonb @> %s::jsonb
          AND created_at >= NOW() - (%s || ' hours')::interval
        ORDER BY composite_score DESC
        LIMIT %s
    """
    tag_json = json.dumps([tag])
    return _pg_fetchall(db_conn_pg, query, (tag_json, int(hours), int(limit)))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 22 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add Postgres-backed market/event/tag alert tools

get_market_alerts, get_event_alerts, search_alerts_by_tag query the Railway
Postgres \`alerts\` table directly. search_alerts_by_tag uses jsonb
containment against the TEXT-stored JSON tags column.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `get_theses` hybrid tool

Theses are pre-computed cross-market wallet positioning groupings. Tool accepts one of: wallet, condition_id, event_slug. Implemented as HTTP call to the market endpoint when condition_id is given, else `/api/theses` with client-side filter.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ----------------------------------------------------------- get_theses ---

def test_get_theses_rejects_zero_filters():
    env = agent.get_theses(http=FakeHTTP({}), api_url="https://api.example.test")
    assert "error" in env
    assert "exactly one" in env["error"]


def test_get_theses_rejects_multiple_filters():
    env = agent.get_theses(
        wallet="0xa", event_slug="ev",
        http=FakeHTTP({}), api_url="https://api.example.test",
    )
    assert "error" in env


def test_get_theses_uses_market_endpoint_for_condition_id():
    body = [{"thesis_id": 1, "headline": "thesis"}]
    http = FakeHTTP({"https://api.example.test/api/market/0xcond/theses": body})
    env = agent.get_theses(condition_id="0xcond", http=http, api_url="https://api.example.test")
    assert env["data"] == body


def test_get_theses_filters_client_side_by_wallet():
    body = {"theses": [
        {"id": 1, "wallet": "0xa", "event_slug": "e1"},
        {"id": 2, "wallet": "0xb", "event_slug": "e1"},
        {"id": 3, "wallet": "0xa", "event_slug": "e2"},
    ]}
    http = FakeHTTP({"https://api.example.test/api/theses": body})
    env = agent.get_theses(wallet="0xa", http=http, api_url="https://api.example.test")
    assert len(env["data"]) == 2
    assert {t["id"] for t in env["data"]} == {1, 3}


def test_get_theses_filters_client_side_by_event_slug():
    body = {"theses": [
        {"id": 1, "wallet": "0xa", "event_slug": "e1"},
        {"id": 2, "wallet": "0xb", "event_slug": "e1"},
        {"id": 3, "wallet": "0xa", "event_slug": "e2"},
    ]}
    http = FakeHTTP({"https://api.example.test/api/theses": body})
    env = agent.get_theses(event_slug="e1", http=http, api_url="https://api.example.test")
    assert {t["id"] for t in env["data"]} == {1, 2}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 5 new tests fail.

- [ ] **Step 3: Implement `get_theses`**

Append to `backend/twitter_bot_agent.py`:

```python
@_safe_tool
def get_theses(
    *,
    wallet: str | None = None,
    condition_id: str | None = None,
    event_slug: str | None = None,
    http,
    api_url: str,
) -> Any:
    """Cross-market thesis groupings, filtered by exactly one of the three args."""
    filters = [wallet, condition_id, event_slug]
    provided = sum(1 for f in filters if f)
    if provided != 1:
        raise ValueError("exactly one of wallet/condition_id/event_slug required")

    base = api_url.rstrip("/")
    if condition_id:
        return _http_get_json(f"{base}/api/market/{condition_id}/theses", http=http)

    # Wallet or event_slug: fetch full list and filter client-side. The list
    # endpoint may return either a bare list or {theses: [...]}.
    raw = _http_get_json(f"{base}/api/theses", http=http)
    items = raw.get("theses") if isinstance(raw, dict) else raw
    if wallet:
        return [t for t in items if t.get("wallet") == wallet]
    return [t for t in items if t.get("event_slug") == event_slug]
```

Note: this tool uses `raise ValueError(...)` for the "exactly one filter" case. The `_safe_tool` decorator catches it and returns an error envelope starting with `ValueError:`. The test above checks `"exactly one"` is in the error message — that matches.

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 27 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add get_theses hybrid tool

Uses /api/market/{id}/theses when condition_id given, otherwise
/api/theses with client-side wallet or event_slug filter. Enforces
exactly-one-of-three-filters rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: SQLite helper + polybot.db tools

Six tools over `polybot.db`: `get_wallet_pnl_positions`, `get_wallet_timing_pattern`, `get_wallet_event_history`, `get_funder_cluster`, `get_orderbook_snapshot`, `get_market_volume_history`.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ------------------------------------------------------------- SQLite tools --

def _make_sqlite_conn():
    """Build an in-memory SQLite DB seeded with the tables our tools query."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE wallet_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, condition_id TEXT, asset TEXT, outcome TEXT,
            avg_price REAL, total_bought REAL, realized_pnl REAL, cur_price REAL,
            event_slug TEXT, end_date TEXT, position_type TEXT,
            recorded_at TEXT, api_timestamp INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE timing_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, condition_id TEXT, minutes_to_resolution REAL,
            usd_value REAL, trade_timestamp REAL, recorded_at TEXT,
            market_duration_hours REAL
        )
    """)
    conn.execute("""
        CREATE TABLE wallet_event_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT, event_slug TEXT, condition_id TEXT, outcome TEXT,
            side TEXT, usd_value REAL, trade_timestamp REAL, recorded_at TEXT,
            price REAL, market_title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE wallet_funders (
            wallet TEXT PRIMARY KEY, funder TEXT, discovered_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT, token_id TEXT, outcome TEXT,
            best_bid REAL, best_ask REAL, spread REAL,
            bid_depth REAL, ask_depth REAL, mid_price REAL, snapshot_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE market_volume_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT, volume_24h REAL, snapshot_at TEXT
        )
    """)
    conn.commit()
    return conn


def test_get_wallet_pnl_positions_returns_rows():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_pnl (wallet, condition_id, outcome, avg_price, total_bought, "
        "realized_pnl, cur_price, position_type, end_date, recorded_at) VALUES "
        "('0xa', 'c1', 'Yes', 0.35, 10000, 500, 0.62, 'open', NULL, '2026-04-19')"
    )
    conn.commit()
    env = agent.get_wallet_pnl_positions(wallet="0xa", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 1
    assert env["data"][0]["outcome"] == "Yes"
    assert env["data"][0]["avg_price"] == 0.35


def test_get_wallet_pnl_positions_lowercases_wallet():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_pnl (wallet, condition_id, outcome, avg_price, total_bought, "
        "realized_pnl, cur_price, position_type, end_date, recorded_at) VALUES "
        "('0xabc', 'c1', 'Yes', 0.3, 5000, 0, 0.5, 'open', NULL, '2026-04-19')"
    )
    conn.commit()
    env = agent.get_wallet_pnl_positions(wallet="0xABC", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 1


def test_get_wallet_timing_pattern_returns_stats():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO timing_flags (wallet, condition_id, minutes_to_resolution, "
        "usd_value, trade_timestamp, recorded_at, market_duration_hours) VALUES "
        "('0xa', 'c1', 5.0, 10000, 1700000000, '2026-04-19', 72)"
    )
    conn.execute(
        "INSERT INTO timing_flags (wallet, condition_id, minutes_to_resolution, "
        "usd_value, trade_timestamp, recorded_at, market_duration_hours) VALUES "
        "('0xa', 'c2', 10.0, 5000, 1700000100, '2026-04-19', 48)"
    )
    conn.commit()
    env = agent.get_wallet_timing_pattern(wallet="0xa", db_conn_sqlite=conn)
    assert env["data"]["total_flags"] == 2
    assert env["data"]["distinct_markets"] == 2
    assert env["data"]["min_minutes"] == 5.0


def test_get_wallet_event_history_returns_trades():
    conn = _make_sqlite_conn()
    conn.execute(
        "INSERT INTO wallet_event_history (wallet, event_slug, condition_id, outcome, "
        "side, usd_value, trade_timestamp, recorded_at, price, market_title) VALUES "
        "('0xa', 'ev1', 'c1', 'Yes', 'BUY', 5000, 1700000000, '2026-04-19', 0.3, 'Mkt A')"
    )
    conn.execute(
        "INSERT INTO wallet_event_history (wallet, event_slug, condition_id, outcome, "
        "side, usd_value, trade_timestamp, recorded_at, price, market_title) VALUES "
        "('0xa', 'ev1', 'c2', 'No', 'BUY', 3000, 1700000100, '2026-04-19', 0.4, 'Mkt B')"
    )
    conn.commit()
    env = agent.get_wallet_event_history(wallet="0xa", event_slug="ev1", db_conn_sqlite=conn)
    assert len(env["data"]) == 2


def test_get_funder_cluster_returns_linked_wallets():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO wallet_funders (wallet, funder, discovered_at) VALUES (?, ?, ?)",
        [("0xa", "0xfund", "t1"), ("0xb", "0xfund", "t2"), ("0xc", "0xother", "t3")],
    )
    conn.commit()
    env = agent.get_funder_cluster(wallet="0xa", db_conn_sqlite=conn)
    assert env["data"]["funder"] == "0xfund"
    assert set(env["data"]["wallets"]) == {"0xa", "0xb"}


def test_get_funder_cluster_returns_empty_when_no_funder():
    conn = _make_sqlite_conn()
    env = agent.get_funder_cluster(wallet="0xnone", db_conn_sqlite=conn)
    assert env["data"] == {"funder": None, "wallets": []}


def test_get_orderbook_snapshot_returns_latest_per_token():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO orderbook_snapshots (condition_id, token_id, outcome, "
        "best_bid, best_ask, spread, bid_depth, ask_depth, mid_price, snapshot_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("c1", "tok-yes", "Yes", 0.60, 0.62, 0.02, 10000, 8000, 0.61, "2026-04-19T10:00:00"),
            ("c1", "tok-yes", "Yes", 0.58, 0.60, 0.02, 9000, 7500, 0.59, "2026-04-19T09:00:00"),
            ("c1", "tok-no", "No", 0.38, 0.40, 0.02, 5000, 4500, 0.39, "2026-04-19T10:00:00"),
        ],
    )
    conn.commit()
    env = agent.get_orderbook_snapshot(condition_id="c1", db_conn_sqlite=conn)
    assert len(env["data"]) == 2
    # Latest per token_id — check best_bid for tok-yes is 0.60 (from the 10:00 row).
    yes_row = next(r for r in env["data"] if r["token_id"] == "tok-yes")
    assert yes_row["best_bid"] == 0.60


def test_get_market_volume_history_returns_rows():
    conn = _make_sqlite_conn()
    conn.executemany(
        "INSERT INTO market_volume_snapshots (condition_id, volume_24h, snapshot_at) VALUES (?, ?, ?)",
        [("c1", 5000, "2026-04-19T08:00:00"),
         ("c1", 12000, "2026-04-19T10:00:00"),
         ("c2", 9999, "2026-04-19T10:00:00")],
    )
    conn.commit()
    env = agent.get_market_volume_history(condition_id="c1", limit=10, db_conn_sqlite=conn)
    assert len(env["data"]) == 2
    # Sorted most recent first.
    assert env["data"][0]["volume_24h"] == 12000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 8 new tests fail. Prior pass.

- [ ] **Step 3: Implement the SQLite tools**

Append to `backend/twitter_bot_agent.py`:

```python
# --- SQLite tools ------------------------------------------------------------

def _sqlite_rows(db_conn_sqlite, query: str, params: tuple, *, keys: list[str]) -> list[dict]:
    """Run a SELECT and zip column-order keys into per-row dicts."""
    cur = db_conn_sqlite.execute(query, params)
    return [dict(zip(keys, row)) for row in cur.fetchall()]


@_safe_tool
def get_wallet_pnl_positions(*, wallet: str, limit: int = 20, db_conn_sqlite) -> Any:
    """Per-position detail (outcome, avg_price, cur_price, realized_pnl) for a wallet."""
    query = """
        SELECT condition_id, outcome, avg_price, total_bought, realized_pnl,
               cur_price, position_type, end_date
        FROM wallet_pnl
        WHERE wallet = ?
        ORDER BY total_bought DESC
        LIMIT ?
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (wallet.lower(), int(limit)),
        keys=["condition_id", "outcome", "avg_price", "total_bought",
              "realized_pnl", "cur_price", "position_type", "end_date"],
    )


@_safe_tool
def get_wallet_timing_pattern(*, wallet: str, db_conn_sqlite) -> Any:
    """How often this wallet bets near resolution (excluding short-duration markets)."""
    row = db_conn_sqlite.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT condition_id),
               AVG(minutes_to_resolution), MIN(minutes_to_resolution),
               SUM(usd_value)
        FROM timing_flags
        WHERE wallet = ?
          AND (market_duration_hours IS NULL OR market_duration_hours >= 1.0)
        """,
        (wallet.lower(),),
    ).fetchone()
    return {
        "total_flags": row[0] or 0,
        "distinct_markets": row[1] or 0,
        "avg_minutes": row[2] or 0.0,
        "min_minutes": row[3] or 0.0,
        "total_usd": row[4] or 0.0,
    }


@_safe_tool
def get_wallet_event_history(*, wallet: str, event_slug: str, db_conn_sqlite) -> Any:
    """Every trade (not just flagged) this wallet made on a given event."""
    query = """
        SELECT condition_id, outcome, side, usd_value, trade_timestamp, price, market_title
        FROM wallet_event_history
        WHERE wallet = ? AND event_slug = ?
        ORDER BY trade_timestamp ASC
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (wallet.lower(), event_slug),
        keys=["condition_id", "outcome", "side", "usd_value",
              "trade_timestamp", "price", "market_title"],
    )


@_safe_tool
def get_funder_cluster(*, wallet: str, db_conn_sqlite) -> Any:
    """Wallets sharing a funder with this one (wallet inclusive if present)."""
    w = wallet.lower()
    row = db_conn_sqlite.execute(
        "SELECT funder FROM wallet_funders WHERE wallet = ?", (w,)
    ).fetchone()
    if not row or not row[0]:
        return {"funder": None, "wallets": []}
    funder = row[0]
    peers = db_conn_sqlite.execute(
        "SELECT wallet FROM wallet_funders WHERE funder = ?", (funder,)
    ).fetchall()
    return {"funder": funder, "wallets": [r[0] for r in peers]}


@_safe_tool
def get_orderbook_snapshot(*, condition_id: str, db_conn_sqlite) -> Any:
    """Most recent orderbook snapshot per outcome token on a market."""
    query = """
        SELECT token_id, outcome, best_bid, best_ask, spread,
               bid_depth, ask_depth, mid_price, snapshot_at
        FROM orderbook_snapshots
        WHERE id IN (
            SELECT MAX(id) FROM orderbook_snapshots
            WHERE condition_id = ?
            GROUP BY token_id
        )
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (condition_id,),
        keys=["token_id", "outcome", "best_bid", "best_ask", "spread",
              "bid_depth", "ask_depth", "mid_price", "snapshot_at"],
    )


@_safe_tool
def get_market_volume_history(*, condition_id: str, limit: int = 50, db_conn_sqlite) -> Any:
    """Recent 24h-volume snapshots for a market (most recent first)."""
    query = """
        SELECT volume_24h, snapshot_at
        FROM market_volume_snapshots
        WHERE condition_id = ?
        ORDER BY snapshot_at DESC
        LIMIT ?
    """
    return _sqlite_rows(
        db_conn_sqlite, query, (condition_id, int(limit)),
        keys=["volume_24h", "snapshot_at"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 35 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add six polybot.db SQLite-backed tools

wallet_pnl_positions, wallet_timing_pattern, wallet_event_history,
funder_cluster, orderbook_snapshot, market_volume_history — exposes the
scanner's private detail tables to the tweet composer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `call_gamma_api` generic caller

HTTP tool against Gamma, restricted to an allowlisted set of path prefixes.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ---------------------------------------------------------- call_gamma_api ---

def test_call_gamma_api_allowed_path_makes_request():
    body = {"id": 1, "slug": "will-x", "volume": 5000}
    http = FakeHTTP({"https://gamma-api.polymarket.com/markets": body})
    env = agent.call_gamma_api(path="/markets", http=http)
    assert env["data"] == body
    assert http.calls[0]["url"] == "https://gamma-api.polymarket.com/markets"


def test_call_gamma_api_passes_query_params():
    http = FakeHTTP({"https://gamma-api.polymarket.com/events/my-event": {"id": 9}})
    env = agent.call_gamma_api(path="/events/my-event", params={"limit": 5}, http=http)
    assert env["data"]["id"] == 9
    assert http.calls[0]["params"] == {"limit": 5}


def test_call_gamma_api_rejects_disallowed_path():
    env = agent.call_gamma_api(path="/admin/secret", http=FakeHTTP({}))
    assert "error" in env
    assert "not allowed" in env["error"]


def test_call_gamma_api_rejects_missing_leading_slash():
    env = agent.call_gamma_api(path="markets", http=FakeHTTP({}))
    assert "error" in env


def test_call_gamma_api_rejects_external_path_injection():
    env = agent.call_gamma_api(path="/markets/../admin", http=FakeHTTP({}))
    assert "error" in env
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 5 new tests fail.

- [ ] **Step 3: Implement `call_gamma_api`**

Append to `backend/twitter_bot_agent.py`:

```python
# --- Gamma API generic caller ------------------------------------------------

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
GAMMA_PATH_ALLOWLIST = ("/markets", "/events", "/trades")


def _gamma_path_allowed(path: str) -> bool:
    """Allow paths that start with an allowlisted prefix and contain no parent traversals."""
    if not path.startswith("/"):
        return False
    if ".." in path or "//" in path:
        return False
    return any(path == prefix or path.startswith(prefix + "/") for prefix in GAMMA_PATH_ALLOWLIST)


@_safe_tool
def call_gamma_api(*, path: str, params: dict | None = None, http) -> Any:
    """Generic GET against https://gamma-api.polymarket.com with path allowlist.

    Allowed prefixes: /markets, /events, /trades (with arbitrary subpaths).
    """
    if not _gamma_path_allowed(path):
        raise ValueError("path not allowed")
    url = f"{GAMMA_BASE_URL}{path}"
    return _http_get_json(url, http=http, params=params or None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 40 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add call_gamma_api generic tool with path allowlist

Allows /markets, /events, /trades prefixes. Rejects missing leading slash,
parent-traversal, and any path outside the allowlist.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Tool registry, OpenAI schemas, and dispatcher

The dispatcher receives a tool name + JSON args from the LLM, looks up the tool function, coerces types, injects deps, and returns the envelope. Also builds the `tools=` list passed to the OpenAI API.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests for the dispatcher**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ------------------------------------------------------------- dispatcher ---

def test_tool_schemas_include_all_16_tools():
    schemas = agent.TOOL_SCHEMAS
    names = {s["function"]["name"] for s in schemas}
    expected = {
        "get_wallet_profile", "get_alert_detail", "get_market_price_history",
        "get_market_holders", "get_market_alerts", "get_event_alerts",
        "get_live_market", "get_theses", "search_alerts_by_tag",
        "get_wallet_pnl_positions", "get_wallet_timing_pattern",
        "get_wallet_event_history", "get_funder_cluster",
        "get_orderbook_snapshot", "get_market_volume_history",
        "call_gamma_api",
    }
    assert names == expected


def test_tool_schemas_every_tool_has_projection_param():
    for s in agent.TOOL_SCHEMAS:
        params = s["function"]["parameters"]["properties"]
        assert "projection" in params, f"{s['function']['name']} missing projection"


def test_dispatch_calls_tool_with_projection():
    body = {"wallet": "0xa", "bet_history": [1, 2, 3]}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    deps = agent.ToolDeps(
        http=http, api_url="https://api.example.test",
        db_conn_pg=None, db_conn_sqlite=None,
    )
    env = agent.dispatch_tool(
        "get_wallet_profile",
        {"wallet": "0xa", "projection": "length(bet_history)"},
        deps=deps,
    )
    assert env["data"] == 3


def test_dispatch_unknown_tool_returns_error():
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    env = agent.dispatch_tool("made_up_tool", {}, deps=deps)
    assert "error" in env
    assert "unknown tool" in env["error"].lower()


def test_dispatch_bad_arg_types_returns_error():
    http = FakeHTTP({"https://api.example.test/api/alerts/7": {"id": 7}})
    deps = agent.ToolDeps(
        http=http, api_url="https://api.example.test",
        db_conn_pg=None, db_conn_sqlite=None,
    )
    # alert_id must be int — pass dict, triggers a coercion failure downstream.
    env = agent.dispatch_tool("get_alert_detail", {"alert_id": {"bad": "value"}}, deps=deps)
    assert "error" in env


def test_dispatch_respects_budget_marker():
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    env = agent.dispatch_tool_over_budget("get_wallet_profile", deps=deps)
    assert "error" in env
    assert "budget" in env["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 6 new tests fail.

- [ ] **Step 3: Implement the registry, schemas, and dispatcher**

Append to `backend/twitter_bot_agent.py`:

```python
# --- Tool registry & dispatcher ----------------------------------------------

from dataclasses import dataclass


@dataclass
class ToolDeps:
    """Bundle of injected dependencies. Pass into the loop and the dispatcher."""
    http: Any
    api_url: str | None
    db_conn_pg: Any
    db_conn_sqlite: Any


# Registry: tool name → (callable, set of dep names it needs)
_TOOL_REGISTRY: dict[str, tuple[Any, set[str]]] = {
    "get_wallet_profile": (get_wallet_profile, {"http", "api_url"}),
    "get_alert_detail": (get_alert_detail, {"http", "api_url"}),
    "get_market_price_history": (get_market_price_history, {"http", "api_url"}),
    "get_market_holders": (get_market_holders, {"http", "api_url"}),
    "get_market_alerts": (get_market_alerts, {"db_conn_pg"}),
    "get_event_alerts": (get_event_alerts, {"db_conn_pg"}),
    "get_live_market": (get_live_market, {"http", "api_url"}),
    "get_theses": (get_theses, {"http", "api_url"}),
    "search_alerts_by_tag": (search_alerts_by_tag, {"db_conn_pg"}),
    "get_wallet_pnl_positions": (get_wallet_pnl_positions, {"db_conn_sqlite"}),
    "get_wallet_timing_pattern": (get_wallet_timing_pattern, {"db_conn_sqlite"}),
    "get_wallet_event_history": (get_wallet_event_history, {"db_conn_sqlite"}),
    "get_funder_cluster": (get_funder_cluster, {"db_conn_sqlite"}),
    "get_orderbook_snapshot": (get_orderbook_snapshot, {"db_conn_sqlite"}),
    "get_market_volume_history": (get_market_volume_history, {"db_conn_sqlite"}),
    "call_gamma_api": (call_gamma_api, {"http"}),
}


def _projection_param() -> dict:
    return {
        "type": "string",
        "description": (
            "Optional JMESPath expression applied to the result before it "
            "reaches you. Example: 'length(bet_history)'."
        ),
    }


TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "get_wallet_profile",
        "description": (
            "Profile + up to 10 recent alerts + up to 20 bet history items for a wallet. "
            "Example projection: 'length(bet_history)' to count bets only."
        ),
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_alert_detail",
        "description": "Full trades + signals for a single alert id.",
        "parameters": {"type": "object", "required": ["alert_id"], "properties": {
            "alert_id": {"type": "integer"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_price_history",
        "description": "Price candles for a market over the last N hours (default 24).",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "hours": {"type": "integer", "default": 24},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_holders",
        "description": "Top holders per outcome for a market.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_alerts",
        "description": "Other PolySpotter alerts on the same market, highest score first.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_event_alerts",
        "description": "Alerts on sibling markets in the same event (e.g., different props on the same game).",
        "parameters": {"type": "object", "required": ["event_slug"], "properties": {
            "event_slug": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_live_market",
        "description": "Live sports/event state (score, clock, phase) when available.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_theses",
        "description": (
            "Cross-market thesis groupings. Provide exactly one of wallet, condition_id, or event_slug."
        ),
        "parameters": {"type": "object", "properties": {
            "wallet": {"type": "string"},
            "condition_id": {"type": "string"},
            "event_slug": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "search_alerts_by_tag",
        "description": (
            "Alerts in the last N hours whose tags array contains the given tag. "
            "Use for thematic synthesis (e.g., tag='Iran')."
        ),
        "parameters": {"type": "object", "required": ["tag"], "properties": {
            "tag": {"type": "string"},
            "hours": {"type": "integer", "default": 24},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_pnl_positions",
        "description": "Per-position detail from polybot.db: outcome, avg_price, cur_price, realized_pnl, position_type.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_timing_pattern",
        "description": "How often this wallet bets near resolution: total_flags, distinct_markets, avg/min minutes.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_wallet_event_history",
        "description": "Every trade (flagged or not) this wallet made on a given event.",
        "parameters": {"type": "object", "required": ["wallet", "event_slug"], "properties": {
            "wallet": {"type": "string"},
            "event_slug": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_funder_cluster",
        "description": "Wallets sharing a funder (Etherscan-derived) with this one.",
        "parameters": {"type": "object", "required": ["wallet"], "properties": {
            "wallet": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_orderbook_snapshot",
        "description": "Most recent orderbook snapshot per outcome token (spread, depth, mid price).",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "get_market_volume_history",
        "description": "Recent 24h-volume snapshots for a market, most recent first.",
        "parameters": {"type": "object", "required": ["condition_id"], "properties": {
            "condition_id": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "projection": _projection_param(),
        }},
    }},
    {"type": "function", "function": {
        "name": "call_gamma_api",
        "description": (
            "Generic GET to https://gamma-api.polymarket.com. Allowed path prefixes: "
            "/markets, /events, /trades. Example: path='/events/my-event'."
        ),
        "parameters": {"type": "object", "required": ["path"], "properties": {
            "path": {"type": "string"},
            "params": {"type": "object"},
            "projection": _projection_param(),
        }},
    }},
]


def dispatch_tool(name: str, arguments: dict, *, deps: ToolDeps) -> dict:
    """Look up a tool by name, inject deps, run it, return the envelope."""
    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return build_envelope(None, error=f"unknown tool: {name}")

    fn, needed = entry
    kwargs = dict(arguments) if isinstance(arguments, dict) else {}
    for dep_name in needed:
        kwargs[dep_name] = getattr(deps, dep_name)
    try:
        return fn(**kwargs)
    except TypeError as exc:
        # Wrong argument types / missing required args.
        return build_envelope(None, error=f"TypeError: {exc}")


def dispatch_tool_over_budget(name: str, *, deps: ToolDeps) -> dict:
    """Return a budget-exhausted error envelope without running the tool.

    Used when a single assistant turn requests more tool calls than the
    remaining budget: the first N are dispatched normally, the rest get this.
    """
    return build_envelope(None, error="tool budget exhausted")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 46 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add tool registry, OpenAI schemas, and dispatcher

TOOL_SCHEMAS describes all 16 tools for the function-calling API; ToolDeps
bundles injected dependencies; dispatch_tool routes name+args to the right
tool with the right deps and wraps errors.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: System prompt + agent loop (`compose_tweet`)

The heart of the agent. One function that runs the multi-turn function-calling loop, enforces the 5-tool budget, and returns the decision dict.

**Files:**
- Modify: `backend/twitter_bot_agent.py`
- Modify: `backend/test_twitter_bot_agent.py`

- [ ] **Step 1: Write failing tests for the loop**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ----------------------------------------------------------- compose_tweet ---

class FakeLLMWithTools:
    """LLM fake that emits either tool_calls or a final content per scripted step.

    `script` is a list of either:
      - list of (tool_name, arguments_dict) — the model requests those tool calls
      - dict — final JSON decision (returned as message.content)
    """

    def __init__(self, script):
        self._script = list(script)
        self.call_log = []  # List of dicts mirroring create() kwargs (minus messages)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.call_log.append({k: v for k, v in kwargs.items() if k != "messages"})
        if not self._script:
            raise RuntimeError("FakeLLMWithTools script exhausted")
        step = self._script.pop(0)

        if isinstance(step, dict):
            # Final JSON content response, no tool calls.
            msg = SimpleNamespace(
                content=json.dumps(step),
                tool_calls=None,
                role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        # Tool-call step.
        tc = []
        for i, (name, args) in enumerate(step):
            tc.append(SimpleNamespace(
                id=f"call_{len(self.call_log)}_{i}",
                type="function",
                function=SimpleNamespace(name=name, arguments=json.dumps(args)),
            ))
        msg = SimpleNamespace(content=None, tool_calls=tc, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _alert(**overrides):
    base = {
        "id": 1,
        "composite_score": 8.0,
        "market_title": "Will X?",
        "condition_id": "0xcond",
        "event_slug": "ev",
        "wallet": "0xa",
        "total_usd": 25000,
        "trade_count": 2,
        "llm_headline": "Whale X",
        "llm_summary": "Wallet dropped $25k.",
        "win_rate": 0.82,
        "total_pnl": 340000,
        "tags": ["Politics"],
        "end_date": "2026-04-20T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_compose_tweet_zero_tool_calls_returns_decision():
    final = {
        "decision": "post", "reason": "strong alert",
        "alert_ids": [1], "tweet": "Short tweet. link in bio",
        "is_composite": False,
    }
    llm = FakeLLMWithTools([final])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "post"
    assert result["tweet"] == "Short tweet. link in bio"


def test_compose_tweet_uses_tool_result_then_composes():
    body = {"wallet": "0xa", "wins": 12}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    final = {
        "decision": "post", "reason": "ok",
        "alert_ids": [1], "tweet": "12 wins.",
        "is_composite": False,
    }
    llm = FakeLLMWithTools([
        [("get_wallet_profile", {"wallet": "0xa"})],
        final,
    ])
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "post"
    assert http.calls[0]["url"] == "https://api.example.test/api/wallets/0xa"


def test_compose_tweet_exhausts_budget_forcing_final_json():
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    # Script: 5 single-tool rounds, then a 6th attempt that we'll force into JSON.
    rounds = [[("get_wallet_profile", {"wallet": "0xa"})] for _ in range(5)]
    rounds.append([("get_wallet_profile", {"wallet": "0xa"})])  # 6th attempt
    final = {
        "decision": "skip", "reason": "exhausted",
        "alert_ids": None, "tweet": None, "is_composite": False,
    }
    rounds.append(final)
    llm = FakeLLMWithTools(rounds)
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "skip"
    # 6th call should have tool_choice='none' (forcing final JSON).
    last_call = llm.call_log[-1]
    assert last_call.get("tool_choice") == "none"


def test_compose_tweet_single_turn_over_budget_truncates_dispatched():
    """If model asks for 6 tools in one turn at budget 0, we dispatch 5 and error the 6th."""
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    calls_in_one_turn = [("get_wallet_profile", {"wallet": "0xa"}) for _ in range(6)]
    final = {
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }
    llm = FakeLLMWithTools([calls_in_one_turn, final])
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)

    assert result["decision"] == "skip"
    # HTTP called exactly 5 times (first 5 dispatched, 6th got budget error).
    assert len(http.calls) == 5


def test_compose_tweet_raises_on_max_iterations_without_final_json():
    """A misbehaving model that never emits content triggers AgentOutputError."""
    body = {"wallet": "0xa"}
    http = FakeHTTP({"https://api.example.test/api/wallets/0xa": body})
    # Feed endless tool-call rounds.
    script = [[("get_wallet_profile", {"wallet": "0xa"})] for _ in range(20)]
    llm = FakeLLMWithTools(script)
    deps = agent.ToolDeps(http=http, api_url="https://api.example.test",
                          db_conn_pg=None, db_conn_sqlite=None)

    with pytest.raises(agent.AgentOutputError):
        agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)


def test_compose_tweet_raises_on_malformed_final_json():
    bad = "{not valid json"
    llm = FakeLLMWithTools([bad])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    with pytest.raises(agent.AgentOutputError):
        agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)


def test_compose_tweet_user_message_includes_condition_id_and_event_slug():
    """Without these fields, tools can't be called. Verify they're in the prompt."""
    llm = FakeLLMWithTools([{
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }])
    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)

    # We don't directly inspect messages in the fake — instead, capture via a
    # subclass that records the messages list.
    captured = {}
    orig_create = llm.chat.completions.create
    def wrapped(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return orig_create(**kwargs)
    llm.chat.completions.create = wrapped

    agent.compose_tweet(
        [_alert(id=1, condition_id="0xcond", event_slug="my-ev")],
        llm_client=llm, deps=deps,
    )

    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    assert "0xcond" in user_msg["content"]
    assert "my-ev" in user_msg["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 7 new tests fail with `AttributeError`.

- [ ] **Step 3: Implement system prompt, user message builder, and the loop**

Append to `backend/twitter_bot_agent.py`:

```python
# --- Prompt + loop -----------------------------------------------------------

MODEL = "gpt-5.4"


SYSTEM_PROMPT = (
    "You are the social media voice for PolySpotter, a service that surfaces "
    "notable Polymarket bets from sharp wallets, whales, and coordinated flow.\n\n"

    "You'll be given up to 5 alerts from the last hour. Your job: write ONE "
    "tweet that's as engaging as possible — drawing on one OR multiple alerts "
    "— or skip the hour if nothing is compelling.\n\n"

    "## You have research tools\n"
    "You can call up to 5 tools before writing the tweet. Use them when "
    "digging deeper would sharpen the story. A good tweet cites a SPECIFIC "
    "fact the alert payload doesn't already contain (e.g., 'bought the Under "
    "at 0.35 — market now at 0.62', 'this wallet has late-timed 17 markets "
    "in 3 weeks', 'volume 12x'd in the last 4 hours'). You don't have to use "
    "all 5. Zero calls is fine if the alerts already tell a tight story.\n\n"

    "## JMESPath projection\n"
    "Every tool accepts an optional `projection` string (a JMESPath expression). "
    "Use it to pull narrow values without loading large blobs into context. "
    "Examples:\n"
    "  - `length(bet_history)` — just a count\n"
    "  - `{win_rate: win_rate, total_pnl: total_pnl}` — pick fields\n"
    "  - `bet_history[?won==`true`].pnl_usd` — filtered list\n"
    "  - `avg(bet_history[?won==`true`].entry_price)` — computed aggregate\n"
    "Bad projections return `{\"error\": \"projection failed: ...\"}` and still "
    "cost a tool call. If you want to explore a tool's shape, call it once "
    "without projection to see the raw (8KB-capped) response.\n\n"

    "## Single vs composite\n"
    "- If one alert clearly stands out, write a tight hook-driven tweet focused on it.\n"
    "- If 2+ alerts tell a bigger story together (same market, same wallet across "
    "markets, a theme like '3 whales all loaded up on Iran markets today'), "
    "compose a synthesis tweet.\n"
    "- Never force synthesis. If alerts are unrelated, just pick the best one.\n\n"

    "## Tweet rules\n"
    "- Max 260 characters (safety margin under X's 280 limit).\n"
    "- Hook-driven opening: lead with the most striking fact.\n"
    "- Use specific numbers, not vague descriptors.\n"
    "- End with a CTA driving clicks to bio: '→ link in bio', "
    "'full details in bio 👀', 'who is this wallet? bio link'.\n"
    "- 1–2 relevant hashtags max. Prefer topic-specific over generic #Polymarket.\n"
    "- 0–2 emojis, only if they add something.\n"
    "- No URLs. No @mentions.\n"
    "- Never fabricate numbers or facts. Only cite values from the alert payload "
    "or from tool responses in this conversation.\n"
    "- Write like a sharp trading desk analyst, not a corporate account.\n\n"

    "## Skip criteria\n"
    "If all alerts are routine/low-signal, return decision=skip with a short reason.\n\n"

    "## Output format (strict JSON, returned as your final assistant content)\n"
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


def build_user_message(top5: list[dict]) -> str:
    """Build the JSON payload describing the 5 candidate alerts.

    Includes every field an investigative composer needs to call deeper tools:
    condition_id, event_slug, end_date, market_description, llm_bullets.
    """
    payload = []
    for a in top5:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "llm_bullets": a.get("llm_bullets") or [],
            "llm_copy_action": a.get("llm_copy_action") or {},
            "market_title": a.get("market_title"),
            "market_description": a.get("market_description"),
            "condition_id": a.get("condition_id"),
            "event_slug": a.get("event_slug"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "wallet_total_pnl": a.get("total_pnl"),
            "total_usd": a.get("total_usd"),
            "trade_count": a.get("trade_count"),
            "tags": a.get("tags") or [],
            "end_date": a.get("end_date"),
        })
    return json.dumps({"alerts": payload}, default=str)


def compose_tweet(top5: list[dict], *, llm_client, deps: ToolDeps) -> dict:
    """Run the function-calling loop and return the final decision dict.

    Raises AgentOutputError if the model fails to emit a valid final JSON
    response within MAX_ITERATIONS.
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(top5)},
    ]
    tool_calls_used = 0
    forcing_final = False

    for _ in range(MAX_ITERATIONS):
        remaining = MAX_TOOL_CALLS - tool_calls_used
        call_kwargs = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "temperature": 0.7,
            "max_completion_tokens": 800,
        }
        if remaining > 0 and not forcing_final:
            call_kwargs["tool_choice"] = "auto"
        else:
            call_kwargs["tool_choice"] = "none"
            call_kwargs["response_format"] = {"type": "json_object"}

        response = llm_client.chat.completions.create(**call_kwargs)
        msg = response.choices[0].message

        tool_calls = getattr(msg, "tool_calls", None)

        if tool_calls and remaining > 0 and not forcing_final:
            # Record the assistant turn exactly as the API expects to echo back.
            messages.append(_assistant_tool_message(msg))
            dispatched = 0
            for call in tool_calls:
                if dispatched < remaining:
                    args = json.loads(call.function.arguments or "{}")
                    env = dispatch_tool(call.function.name, args, deps=deps)
                    dispatched += 1
                else:
                    env = dispatch_tool_over_budget(call.function.name, deps=deps)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(env, default=str),
                })
            tool_calls_used += dispatched
            if tool_calls_used >= MAX_TOOL_CALLS:
                forcing_final = True
                messages.append({
                    "role": "user",
                    "content": (
                        "Tool budget exhausted. Return your final JSON decision now — "
                        "no more tool calls."
                    ),
                })
            continue

        # No tool calls (or forced) — expect final JSON content.
        content = msg.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentOutputError(f"final content was not valid JSON: {exc}") from exc

    raise AgentOutputError("agent exceeded MAX_ITERATIONS without final JSON")


def _assistant_tool_message(msg) -> dict:
    """Shape an assistant message with tool_calls for echoing back to the API."""
    return {
        "role": "assistant",
        "content": msg.content,  # usually None
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            }
            for c in msg.tool_calls
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: 53 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Add compose_tweet agent loop and system prompt

Implements the function-calling loop with 5-call budget, forcing message
on exhaustion, budget-truncated single-turn dispatch, and AgentOutputError
for iteration overflow or malformed JSON. build_user_message includes
condition_id/event_slug/end_date so tools are callable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Wire `compose_tweet` into `backend/twitter_bot.py`

Replace the single-pass `call_llm` with a thin wrapper that calls `compose_tweet`, preserving the 260-char length retry behavior and all existing validation.

**Files:**
- Modify: `backend/twitter_bot.py`

- [ ] **Step 1: Update `_build_user_message` to include the extra fields**

In `backend/twitter_bot.py`, replace the body of `_build_user_message` (currently lines 204-220) with a delegation to the agent module's equivalent:

```python
def _build_user_message(top5: list[dict]) -> str:
    """Build the JSON payload describing the 5 candidate alerts.

    Delegates to twitter_bot_agent.build_user_message so the field list stays
    in sync with the agent's expectations (condition_id, event_slug, end_date,
    etc. — required for tool calls).
    """
    from twitter_bot_agent import build_user_message
    return build_user_message(top5)
```

- [ ] **Step 2: Replace `call_llm` with an agent-backed version**

In `backend/twitter_bot.py`, delete `_llm_decide` entirely (currently lines 254-264 — it has no callers after this change) and replace `call_llm` (currently lines 223-251) with:

```python
def call_llm(top5: list[dict], *, llm_client, db_conn_pg=None, db_conn_sqlite=None, http=None) -> dict:
    """Run the agentic composer and handle the 260-char length retry.

    Delegates composition to twitter_bot_agent.compose_tweet (which runs the
    tool-calling loop). If the returned tweet exceeds TWEET_MAX_CHARS, makes
    one non-agentic follow-up LLM call asking to shorten, matching the
    behavior of the pre-agent bot.
    """
    from twitter_bot_agent import compose_tweet, ToolDeps

    deps = ToolDeps(
        http=http if http is not None else requests,
        api_url=POLYSPOTTER_API_URL,
        db_conn_pg=db_conn_pg,
        db_conn_sqlite=db_conn_sqlite,
    )

    decision = compose_tweet(top5, llm_client=llm_client, deps=deps)

    tweet = decision.get("tweet") or ""
    if decision.get("decision") == "post" and len(tweet) > TWEET_MAX_CHARS:
        decision = _shorten_tweet(decision, top5, llm_client=llm_client)

    return decision


def _shorten_tweet(decision: dict, top5: list[dict], *, llm_client) -> dict:
    """One-shot non-agentic call to shorten an over-length tweet."""
    from twitter_bot_agent import SYSTEM_PROMPT, build_user_message
    original = decision.get("tweet") or ""
    retry_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(top5)},
        {"role": "assistant", "content": json.dumps(decision)},
        {"role": "user", "content": (
            f"Your tweet was {len(original)} characters, must be ≤{TWEET_MAX_CHARS}. "
            f"Shorten it, keep the hook and CTA. Return the same JSON format — "
            f"no tool calls, just the final JSON."
        )},
    ]
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=retry_messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=500,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)
```

- [ ] **Step 3: Thread `db_conn_sqlite` and `http` through `main()`**

In `backend/twitter_bot.py` `main()` (starting around line 389), update the call to `call_llm` to pass the new deps. Replace the `try: decision = call_llm(top5, llm_client=llm_client)` block (currently around line 462-466) with:

```python
        # 4. LLM (agentic composer).
        from db import get_db as _get_sqlite_db
        try:
            db_conn_sqlite = _get_sqlite_db()
        except Exception as e:
            log_event("sqlite_open_error", run_id=run_id, error=str(e))
            db_conn_sqlite = None

        try:
            decision = call_llm(
                top5,
                llm_client=llm_client,
                db_conn_pg=db_conn,
                db_conn_sqlite=db_conn_sqlite,
                http=http,
            )
        except Exception as e:
            log_event("llm_error", run_id=run_id, error=str(e))
            return 1
```

Note: `db.get_db()` lives at the repo root (`/home/bhavya/git/polybot/db.py`). For this import to work from inside `backend/`, the `sys.path` must include the repo root. Add near the top of `backend/twitter_bot.py` (after the other imports, before `load_dotenv()`):

```python
# The scanner's db module lives at the repo root; add it to sys.path so we can
# import polybot.db for SQLite-backed agent tools.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
```

- [ ] **Step 4: Run the existing test suite and confirm it still passes**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py -v
```

Expected: the `call_llm`-level tests (`test_call_llm_returns_skip_decision_cleanly`, `test_call_llm_returns_valid_post_decision_first_try`, `test_call_llm_retries_once_on_length_overshoot_and_succeeds`, `test_call_llm_returns_overlong_result_when_retry_also_fails`) will **FAIL** because the old fake LLM doesn't speak the tool-calls protocol. Fixing them is Task 11.

Other tests (`fetch_recent_alerts`, `filter_dedup`, `validate_decision`, `post_tweet`, `record_tweet`) should **still PASS**.

Expected failure count: 4 (the four `test_call_llm_*` cases + any integration test that uses the old fake for the LLM step).

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/twitter_bot.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Wire compose_tweet into twitter_bot.main

call_llm now delegates composition to the agentic loop and keeps a
non-agentic single-shot 'shorten' follow-up for the rare case the
agent's tweet exceeds 260 chars. main() opens a polybot.db SQLite
connection and threads it through. The scanner's db module is added
to sys.path so backend code can import it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Adapt the existing `test_twitter_bot.py` cases to the agentic world

The old `FakeLLMClient` and the four `test_call_llm_*` cases test a contract (`call_llm` as a simple chat call) that no longer exists. Replace them with agent-aware fakes.

**Files:**
- Modify: `backend/test_twitter_bot.py`

- [ ] **Step 1: Replace `FakeLLMClient` with an agent-aware fake**

In `backend/test_twitter_bot.py`, replace the existing `FakeLLMClient` class (lines 188-203) with a version that emits tool-call sequences:

```python
class FakeLLMClient:
    """Stand-in that scripts the agentic loop.

    `responses` is a list of steps. Each step is either:
      - a final decision dict (emitted as message.content)
      - a list of (tool_name, arguments_dict) tuples (emitted as tool_calls)

    Starts empty on a `responses=[...]` list; each `create()` consumes one.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # Preserved for legacy tests that inspect call_count.
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeLLMClient script exhausted")
        step = self._responses.pop(0)

        if isinstance(step, dict):
            msg = SimpleNamespace(
                content=json.dumps(step),
                tool_calls=None,
                role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        if isinstance(step, str):
            # Raw string content (for malformed-JSON test).
            msg = SimpleNamespace(content=step, tool_calls=None, role="assistant")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        # Tool-call step.
        import uuid as _uuid
        tc = [
            SimpleNamespace(
                id=f"call_{_uuid.uuid4().hex[:8]}",
                type="function",
                function=SimpleNamespace(name=name, arguments=json.dumps(args)),
            )
            for (name, args) in step
        ]
        msg = SimpleNamespace(content=None, tool_calls=tc, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
```

- [ ] **Step 2: Replace the four `test_call_llm_*` cases**

In `backend/test_twitter_bot.py`, delete the four tests currently at lines 206-268 (`test_call_llm_returns_skip_decision_cleanly`, `test_call_llm_returns_valid_post_decision_first_try`, `test_call_llm_retries_once_on_length_overshoot_and_succeeds`, `test_call_llm_returns_overlong_result_when_retry_also_fails`) and replace them with:

```python
def test_call_llm_returns_skip_decision_cleanly():
    client = FakeLLMClient([{
        "decision": "skip", "reason": "all routine",
        "alert_ids": None, "tweet": None, "is_composite": False,
    }])
    result = tb.call_llm([_alert(id=1, condition_id="c", event_slug="e")],
                         llm_client=client)
    assert result["decision"] == "skip"


def test_call_llm_returns_valid_post_decision_first_try():
    client = FakeLLMClient([{
        "decision": "post", "reason": "hot",
        "alert_ids": [1], "tweet": "Short tweet. link in bio.",
        "is_composite": False,
    }])
    result = tb.call_llm([_alert(id=1, condition_id="c", event_slug="e")],
                         llm_client=client)
    assert result["tweet"] == "Short tweet. link in bio."


def test_call_llm_retries_once_on_length_overshoot_and_succeeds():
    long_tweet = "x" * 300
    retry_tweet = "x" * 200
    first = {"decision": "post", "reason": "ok", "alert_ids": [1],
             "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "shorter", "alert_ids": [1],
              "tweet": retry_tweet, "is_composite": False}
    client = FakeLLMClient([first, second])

    result = tb.call_llm([_alert(id=1, condition_id="c", event_slug="e")],
                         llm_client=client)

    assert result["tweet"] == retry_tweet
    # Two LLM calls: one for the agent's final, one for the shorten retry.
    assert len(client.calls) == 2


def test_call_llm_returns_overlong_result_when_retry_also_fails():
    long_tweet = "x" * 300
    first = {"decision": "post", "reason": "ok", "alert_ids": [1],
             "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "still long", "alert_ids": [1],
              "tweet": "x" * 280, "is_composite": False}
    client = FakeLLMClient([first, second])

    result = tb.call_llm([_alert(id=1, condition_id="c", event_slug="e")],
                         llm_client=client)

    # call_llm doesn't judge validity itself — returns what the retry said.
    assert len(result["tweet"]) == 280
```

- [ ] **Step 3: Update the `_alert` helper to include the fields the agent needs**

In `backend/test_twitter_bot.py`, update `_alert` (line 29) to include the extra fields added in Task 10's prompt enrichment:

```python
def _alert(**overrides):
    """Build an AlertOut-shaped dict with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": 1,
        "composite_score": 8.0,
        "market_title": "Will X happen?",
        "market_description": "Resolves Yes if X.",
        "condition_id": "0xcond1",
        "event_slug": "ev-1",
        "end_date": "2026-04-20T00:00:00Z",
        "wallet": "0xwallet1",
        "total_usd": 25_000.0,
        "trade_count": 1,
        "llm_headline": "Whale loads up on X",
        "llm_summary": "Wallet with 82% win rate dropped $25k.",
        "llm_bullets": [],
        "llm_copy_action": {},
        "win_rate": 0.82,
        "total_pnl": 340_000.0,
        "tags": ["Politics"],
        "created_at": now,
    }
    defaults.update(overrides)
    return defaults
```

- [ ] **Step 4: Run the full test suite**

```bash
source venv/bin/activate
cd backend && pytest test_twitter_bot.py test_twitter_bot_agent.py -v
```

Expected: every test passes. Count should be `29 (original bot) - 4 (dropped call_llm tests) + 4 (new call_llm tests) + 53 (agent) = 82` — confirm via the final summary line.

- [ ] **Step 5: Commit**

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add backend/test_twitter_bot.py
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Adapt test_twitter_bot.py to the agentic FakeLLMClient

FakeLLMClient now scripts multi-turn tool-calling sequences. The four
call_llm tests exercise zero-tool composition, a length-retry succeeds,
and a length-retry fallback. _alert gains condition_id/event_slug/
end_date so build_user_message shapes correctly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Dry-run smoke test against the live hosted API

Run the bot against the real `https://api.polyspotter.com` and the live `polybot.db` in dry-run mode, with a fake Twitter client. This verifies wiring end-to-end without posting anything.

**Files:** None — this is an operational test.

- [ ] **Step 1: Confirm `.env` has all required vars**

```bash
cd /home/bhavya/git/polybot/.worktrees/twitter-agent
grep -E '^(DATABASE_URL|AZURE_OPENAI_API_KEY|POLYSPOTTER_API_URL|X_CONSUMER_KEY)=' ../../.env | cut -d= -f1
```

Expected output (order may vary): `DATABASE_URL`, `AZURE_OPENAI_API_KEY`, `POLYSPOTTER_API_URL` (optional), `X_CONSUMER_KEY`.

If any are missing, stop and ask the user to populate `.env` before continuing.

- [ ] **Step 2: Copy .env into the worktree so the bot can find it**

The bot calls `load_dotenv()` from the worktree root. Symlink or copy:

```bash
cd /home/bhavya/git/polybot/.worktrees/twitter-agent
ln -sf ../../.env .env
ls -la .env
```

Expected: a symlink pointing to `../../.env`.

- [ ] **Step 3: Run the bot in dry-run mode**

```bash
source venv/bin/activate
cd /home/bhavya/git/polybot/.worktrees/twitter-agent
TWITTER_BOT_DRY_RUN=true python backend/twitter_bot.py
```

Expected: structured JSON log events in order:
1. `run_start` with `dry_run: true`
2. `candidates_fetched` with a non-zero count (unless no alerts in the last hour)
3. `after_dedup` with a count ≤ candidates_fetched
4. Either `no_candidates` (exit early) OR `dry_run_top5` showing up to 5 alerts
5. If alerts exist: LLM agent should emit at least one final decision — either `llm_skip` OR `dry_run_tweet` followed by `posted` with a `dryrun-*` id
6. `run_end`

No `fetch_error`, `llm_error`, `post_error`, or uncaught tracebacks.

- [ ] **Step 4: Inspect the resulting tweet**

If the bot posted (dry-run), the `dry_run_tweet` event contains the composed tweet text. Read it — confirm:
- Length ≤ 260 characters
- Cites specific numbers (not vague)
- Ends with a link-in-bio CTA
- Doesn't fabricate claims not in the alert payload or tool responses

If it skipped, the `llm_skip` event reason should be coherent.

If something looks off, check logs for `tool_call` events to see which tools the agent reached for.

- [ ] **Step 5: Commit a brief validation note**

Add a short line to the top of the plan noting the smoke test ran cleanly. Open `docs/superpowers/plans/2026-04-19-twitter-bot-agentic-composer.md` and add below the header, right above the `---` separator:

```markdown
**Smoke test (dry-run against live API):** Ran 2026-04-19, produced tweet "<paste first 80 chars of the tweet>..." — no errors.
```

```bash
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent add docs/superpowers/plans/2026-04-19-twitter-bot-agentic-composer.md
git -C /home/bhavya/git/polybot/.worktrees/twitter-agent commit -m "Verify agentic composer end-to-end in dry-run"
```

- [ ] **Step 6: Hand off to the user**

Report the smoke-test output + final test suite status. Ask whether to open a PR into `main`.

---

## Summary of artifacts

After all tasks complete, the feature branch `feature/twitter-agentic-composer` will have:

| File | Status | Purpose |
|---|---|---|
| `backend/twitter_bot_agent.py` | NEW | 16 curated tools, dispatcher, agent loop |
| `backend/twitter_bot.py` | MODIFIED | `call_llm` delegates to agent; polybot.db threaded through; user-msg enriched |
| `backend/test_twitter_bot_agent.py` | NEW | Full agent test coverage (53 tests) |
| `backend/test_twitter_bot.py` | MODIFIED | Agent-aware `FakeLLMClient`; call_llm tests rewritten |
| `backend/requirements.txt` | MODIFIED | Added `jmespath>=1.0` |
| `docs/superpowers/specs/2026-04-19-twitter-bot-agentic-composer-design.md` | NEW | Design spec (already committed) |
| `docs/superpowers/plans/2026-04-19-twitter-bot-agentic-composer.md` | NEW | This plan |

No scanner changes, no Postgres schema changes, no new backend endpoints. The existing bot's fetch, dedup, post, and record paths are unchanged — the agent is a drop-in replacement for the single LLM call.
