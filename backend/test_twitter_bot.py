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


class FakeHTTP:
    """Stand-in for the `requests` module. Records calls, returns a canned body.

    `body_or_map` is either:
      - a dict mapping URL -> response body (used when the same fake serves
        multiple endpoints — e.g., agent tool calls), or
      - any other value, served as the response body for every request.

    The URL-mapping mode is detected by checking that every value is itself a
    dict/list (i.e. looks like a response body). A raw alert-list response
    body is served as-is.
    """

    def __init__(self, body_or_map):
        self._body = body_or_map
        self.last_url = None
        self.last_params = None
        self.calls = []

    def _is_url_map(self):
        # URL-map mode: dict whose keys are URLs (start with http).
        return (
            isinstance(self._body, dict)
            and bool(self._body)
            and all(isinstance(k, str) and k.startswith("http") for k in self._body.keys())
        )

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        body = self._body.get(url, {}) if self._is_url_map() else self._body
        resp = SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: body
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
        if "SELECT wallet, condition_id" in self._last_query:
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


# ------------------------------------------------------------------ call_llm --

class FakeLLMClient:
    """Stand-in that scripts the agentic loop.

    `responses` is a list of steps. Each step is either:
      - a final decision dict (emitted as message.content)
      - a raw string (for malformed-JSON tests)
      - a list of (tool_name, arguments_dict) tuples (emitted as tool_calls)

    Each `create()` consumes one step from the list.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # Preserved for legacy tests that inspect call counts.
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


def test_call_llm_exercises_tool_calls_through_agent_loop():
    """Verify the agent can make a tool call via call_llm and still return a decision."""
    # Step 1: agent requests get_wallet_profile.
    # Step 2: agent emits final JSON decision.
    final = {
        "decision": "post", "reason": "whale has 17 wins",
        "alert_ids": [1], "tweet": "Whale with 17 wins just loaded up. link in bio",
        "is_composite": False,
    }
    client = FakeLLMClient([
        [("get_wallet_profile", {"wallet": "0xwallet1"})],
        final,
    ])

    # FakeHTTP with a canned wallet profile response.
    fake_http = FakeHTTP({"https://api.example.test/api/wallets/0xwallet1": {"wins": 17, "wallet": "0xwallet1"}})

    result = tb.call_llm(
        [_alert(id=1)],
        llm_client=client,
        db_conn_pg=None,
        db_conn_sqlite=None,
        http=fake_http,
    )
    assert result["decision"] == "post"
    assert "17 wins" in result["tweet"]
    # Two LLM calls: one that returned tool_calls, one that returned the final JSON.
    assert len(client.calls) == 2
    # And the HTTP fake was hit exactly once.
    assert len(fake_http.calls) == 1


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
