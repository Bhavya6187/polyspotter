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

    def __init__(self, hard_dedup_ids=None):
        # Set of alert ids already tweeted.
        self._hard = set(hard_dedup_ids or [])
        self._last_query = None
        self._last_params = None

    def execute(self, query, params=None):
        self._last_query = query
        self._last_params = params

    def fetchall(self):
        if "SELECT alert_id FROM tweeted_alerts WHERE alert_id" in self._last_query:
            requested = self._last_params[0]
            return [{"alert_id": i} for i in requested if i in self._hard]
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
    """Responses-API stand-in that scripts the LLM call sequence.

    `responses` is a list of steps. Each step is either:
      - a final decision dict (emitted as response.output_text JSON)
      - a raw string (for malformed-JSON tests)
      - a list of (tool_name, arguments_dict) tuples (emitted as function_call
        items in response.output)

    Each `create()` consumes one step from the list. Stage 1 consumes one step
    (its JSON output); stage 2 consumes 1+ steps (tool rounds + final).
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeLLMClient script exhausted")
        step = self._responses.pop(0)

        if isinstance(step, dict):
            return SimpleNamespace(output_text=json.dumps(step), output=[])

        if isinstance(step, str):
            return SimpleNamespace(output_text=step, output=[])

        import uuid as _uuid
        tc = [
            _FakeFunctionCallItem(
                call_id=f"call_{_uuid.uuid4().hex[:8]}",
                item_id=f"fc_{_uuid.uuid4().hex[:8]}",
                name=name,
                arguments=json.dumps(args),
            )
            for (name, args) in step
        ]
        return SimpleNamespace(output_text="", output=tc)


class _FakeFunctionCallItem(SimpleNamespace):
    """Stand-in for openai.types.responses.ResponseFunctionToolCall.

    Carries the four attributes the agent loop reads off the item plus a
    `model_dump` method so the loop can JSON-serialize it back into input.
    """

    def __init__(self, *, call_id, item_id, name, arguments):
        super().__init__(
            type="function_call", id=item_id, call_id=call_id,
            name=name, arguments=arguments,
        )

    def model_dump(self, mode=None):
        return {
            "type": "function_call",
            "id": self.id,
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
        }


# Reusable stage-1 responses for tests.
def _stage1_skip(reason="all routine"):
    return {"decision": "skip", "reason": reason}


def _stage1_shortlist(*alert_ids, mode="single"):
    return {
        "decision": "shortlist", "reason": "test pick", "mode": mode,
        "shortlist": [{"alert_id": int(i), "angle": f"angle for {i}"} for i in alert_ids],
    }


def test_call_llm_stage1_skip_returns_skip_without_calling_stage2():
    """Stage-1 skip should short-circuit; only one LLM call happens."""
    client = FakeLLMClient([_stage1_skip("nothing compelling")])
    top_alerts = [_alert(id=1), _alert(id=2)]

    sd, decision = tb.call_llm(top_alerts, llm_client=client)

    assert sd.decision == "skip"
    assert decision["decision"] == "skip"
    assert decision["reason"] == "nothing compelling"
    assert len(client.calls) == 1


def test_call_llm_full_flow_returns_post_decision():
    """Stage 1 shortlists 2 alerts, stage 2 emits a valid post decision."""
    final = {
        "decision": "post", "reason": "whale on hot market",
        "alert_ids": [1], "tweet": "Short tweet. link in bio.",
        "is_composite": False,
    }
    client = FakeLLMClient([_stage1_shortlist(1, 2), final])
    top_alerts = [_alert(id=1), _alert(id=2)]

    sd, decision = tb.call_llm(top_alerts, llm_client=client)

    assert sd.mode == "single"
    assert {item.alert_id for item in sd.shortlist} == {1, 2}
    assert decision["tweet"] == "Short tweet. link in bio."
    assert len(client.calls) == 2  # stage 1 + stage 2 final


def test_call_llm_retries_once_on_length_overshoot_and_succeeds():
    long_tweet = "x" * 300
    retry_tweet = "x" * 200
    first = {"decision": "post", "reason": "ok", "alert_ids": [1], "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "shorter", "alert_ids": [1], "tweet": retry_tweet, "is_composite": False}
    client = FakeLLMClient([_stage1_shortlist(1, 2), first, second])
    top_alerts = [_alert(id=1), _alert(id=2)]

    sd, decision = tb.call_llm(top_alerts, llm_client=client)

    assert decision["tweet"] == retry_tweet
    assert len(client.calls) == 3  # stage 1 + stage 2 first + retry


def test_call_llm_returns_overlong_result_when_retry_also_fails():
    long_tweet = "x" * 300
    first = {"decision": "post", "reason": "ok", "alert_ids": [1], "tweet": long_tweet, "is_composite": False}
    second = {"decision": "post", "reason": "still long", "alert_ids": [1], "tweet": "x" * 280, "is_composite": False}
    client = FakeLLMClient([_stage1_shortlist(1, 2), first, second])

    sd, decision = tb.call_llm([_alert(id=1), _alert(id=2)], llm_client=client)

    assert len(client.calls) == 3
    assert len(decision["tweet"]) == 280


def test_call_llm_exercises_tool_calls_through_agent_loop():
    """Stage-1 shortlists, stage-2 makes a tool call, then emits a final decision."""
    final = {
        "decision": "post", "reason": "whale has 17 wins",
        "alert_ids": [1], "tweet": "Whale with 17 wins just loaded up. link in bio",
        "is_composite": False,
    }
    client = FakeLLMClient([
        _stage1_shortlist(1, 2),
        [("get_wallet_profile", {"wallet": "0xwallet1"})],
        final,
    ])
    fake_http = FakeHTTP({"https://api.example.test/api/wallets/0xwallet1": {"wins": 17, "wallet": "0xwallet1"}})

    sd, decision = tb.call_llm(
        [_alert(id=1), _alert(id=2)],
        llm_client=client, db_conn_pg=None, db_conn_sqlite=None, http=fake_http,
    )
    assert decision["decision"] == "post"
    assert "17 wins" in decision["tweet"]
    assert len(client.calls) == 3  # stage 1 + stage 2 tool round + stage 2 final
    assert len(fake_http.calls) == 1


def test_call_llm_stage1_invalid_json_falls_back_to_top_3_by_score():
    """Malformed stage-1 output triggers fallback shortlist (top-3 by composite_score)."""
    final = {
        "decision": "post", "reason": "ok", "alert_ids": [3],
        "tweet": "fallback worked. link in bio", "is_composite": False,
    }
    # Stage 1 returns garbage, stage 2 emits final.
    client = FakeLLMClient(["{not json", final])
    top_alerts = [
        _alert(id=1, composite_score=5.0),
        _alert(id=2, composite_score=8.0),
        _alert(id=3, composite_score=12.0),
        _alert(id=4, composite_score=10.0),
    ]
    sd, decision = tb.call_llm(top_alerts, llm_client=client)
    # Fallback: top-3 by composite_score → ids {3, 4, 2}, mode single.
    assert sd.mode == "single"
    assert {item.alert_id for item in sd.shortlist} == {2, 3, 4}
    assert decision["decision"] == "post"


def test_call_llm_stage1_exception_falls_back():
    """If stage-1 LLM raises, fall back to top-3 and proceed."""
    final = {
        "decision": "post", "reason": "ok", "alert_ids": [1],
        "tweet": "fallback. link in bio", "is_composite": False,
    }

    class RaisingThenWorkingLLM:
        def __init__(self, second_response):
            self._second = second_response
            self._first = True
            self.calls = []
            self.responses = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            self.calls.append(kwargs)
            if self._first:
                self._first = False
                raise RuntimeError("stage-1 LLM down")
            return SimpleNamespace(output_text=json.dumps(self._second), output=[])

    client = RaisingThenWorkingLLM(final)
    top_alerts = [_alert(id=1, composite_score=10.0), _alert(id=2, composite_score=8.0)]
    sd, decision = tb.call_llm(top_alerts, llm_client=client)
    # Fallback shortlist: top-3 by score (only 2 available, so both included).
    assert sd.mode == "single"
    assert {item.alert_id for item in sd.shortlist} == {1, 2}
    assert decision["tweet"] == "fallback. link in bio"


def test_call_llm_stage1_fallback_with_fewer_than_three_alerts():
    """When fewer than 3 alerts are in input on fallback, shortlist whatever is there."""
    final = {
        "decision": "post", "reason": "ok", "alert_ids": [1],
        "tweet": "lone alert. link in bio", "is_composite": False,
    }
    client = FakeLLMClient(["{bad", final])
    sd, decision = tb.call_llm([_alert(id=1, composite_score=10.0)], llm_client=client)
    assert sd.mode == "single"
    assert len(sd.shortlist) == 1
    assert sd.shortlist[0].alert_id == 1


# ---------------------------------------------------------- validate_decision --

def test_validate_decision_accepts_valid_single_post():
    d = {"decision": "post", "alert_ids": [1], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2}, mode="single")
    assert ok
    assert err == ""


def test_validate_decision_accepts_skip_in_either_mode():
    d = {"decision": "skip", "alert_ids": None, "tweet": None, "is_composite": False}
    for mode in ("single", "composite"):
        ok, _ = tb.validate_decision(d, shortlisted_ids={1, 2}, mode=mode)
        assert ok


def test_validate_decision_rejects_alert_id_not_in_shortlist():
    d = {"decision": "post", "alert_ids": [99], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2, 3}, mode="single")
    assert not ok
    assert "99" in err


def test_validate_decision_rejects_tweet_over_max_length():
    d = {"decision": "post", "alert_ids": [1], "tweet": "x" * 300, "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1}, mode="single")
    assert not ok
    assert "length" in err.lower()


def test_validate_decision_rejects_empty_alert_ids_on_post():
    d = {"decision": "post", "alert_ids": [], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1}, mode="single")
    assert not ok


def test_validate_decision_single_mode_rejects_multiple_alert_ids():
    d = {"decision": "post", "alert_ids": [1, 2], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2}, mode="single")
    assert not ok
    assert "single" in err.lower()


def test_validate_decision_single_mode_rejects_is_composite_true():
    d = {"decision": "post", "alert_ids": [1], "tweet": "ok", "is_composite": True}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2}, mode="single")
    assert not ok


def test_validate_decision_composite_mode_accepts_full_shortlist():
    d = {"decision": "post", "alert_ids": [1, 2, 3], "tweet": "ok", "is_composite": True}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2, 3}, mode="composite")
    assert ok


def test_validate_decision_composite_mode_rejects_partial_shortlist():
    d = {"decision": "post", "alert_ids": [1, 2], "tweet": "ok", "is_composite": True}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2, 3}, mode="composite")
    assert not ok
    assert "composite" in err.lower()


def test_validate_decision_composite_mode_rejects_is_composite_false():
    d = {"decision": "post", "alert_ids": [1, 2], "tweet": "ok", "is_composite": False}
    ok, err = tb.validate_decision(d, shortlisted_ids={1, 2}, mode="composite")
    assert not ok


def test_validate_decision_rejects_unknown_decision_value():
    d = {"decision": "maybe", "alert_ids": [1], "tweet": "ok", "is_composite": False}
    ok, _ = tb.validate_decision(d, shortlisted_ids={1}, mode="single")
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

    llm = FakeLLMClient([
        _stage1_shortlist(1, 2),
        {
            "decision": "post",
            "reason": "hot",
            "alert_ids": [1],
            "tweet": "Whale dropped $25k. link in bio",
            "is_composite": False,
        },
    ])

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
    llm = FakeLLMClient([_stage1_skip("nothing compelling")])
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
        "alerts": [
            _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    # LLM claims alert_id=999 which wasn't in our input. No retry triggers
    # because this isn't a length problem.
    llm = FakeLLMClient([
        _stage1_shortlist(1, 2),
        {"decision": "post", "reason": "x", "alert_ids": [999],
         "tweet": "ok", "is_composite": False},
    ])
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
        "alerts": [
            _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([
        _stage1_shortlist(1, 2),
        {"decision": "post", "reason": "x", "alert_ids": [1],
         "tweet": "ok", "is_composite": False},
    ])
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
        "alerts": [
            _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([
        _stage1_shortlist(1, 2),
        {"decision": "post", "reason": "x", "alert_ids": [1],
         "tweet": "hello link in bio", "is_composite": False},
    ])
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


# ------------------------------------------------------------ stage-1 main ----

def test_main_stage1_skip_does_not_call_stage2(monkeypatch):
    """When stage 1 skips, the LLM is called once and no tweet is posted."""
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([_stage1_skip("nothing compelling")])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 0
    assert twitter.calls == []
    assert len(llm.calls) == 1  # only stage 1


def test_main_stage1_fallback_logs_and_proceeds(monkeypatch, capsys):
    """Stage-1 invalid JSON triggers fallback, stage 2 runs, tweet is posted."""
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [
            _alert(id=1, composite_score=10.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, composite_score=8.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    final = {
        "decision": "post", "reason": "ok", "alert_ids": [1],
        "tweet": "fallback worked. link in bio", "is_composite": False,
    }
    llm = FakeLLMClient(["{bad json", final])
    twitter = FakeTwitterClient(tweet_id="42")

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert twitter.calls == ["fallback worked. link in bio"]

    # Verify the terminal run_end JSON line carries stage1_fallback=True and
    # stage1_mode="single" (from _build_fallback_shortlist).
    run_end_lines = [line for line in out.splitlines() if '"event": "run_end"' in line]
    assert run_end_lines, "expected a run_end log event"
    final = json.loads(run_end_lines[-1])
    assert final.get("stage1_fallback") is True
    assert final.get("stage1_mode") == "single"


def test_main_runs_full_two_stage_flow_successfully(monkeypatch):
    """Stage 1 shortlists 2 alerts, stage 2 posts a single-mode tweet."""
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [
            _alert(id=1, composite_score=9.0,
                   created_at=(now - timedelta(minutes=10)).isoformat()),
            _alert(id=2, composite_score=8.0,
                   created_at=(now - timedelta(minutes=15)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([
        _stage1_shortlist(1, 2),
        {"decision": "post", "reason": "hot", "alert_ids": [1],
         "tweet": "Whale dropped $25k. link in bio", "is_composite": False},
    ])
    twitter = FakeTwitterClient(tweet_id="99")

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    exit_code = tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)

    assert exit_code == 0
    assert twitter.calls == ["Whale dropped $25k. link in bio"]
    insert_calls = [e for e in conn.cur.executions if "INSERT INTO tweeted_alerts" in e[1]]
    assert len(insert_calls) == 1


def test_main_stage1_skip_run_end_has_mode_none(monkeypatch, capsys):
    """When stage 1 skips, the run_end event logs stage1_mode=None (not 'skip')."""
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([_stage1_skip("nothing compelling")])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []

    conn = RecordingConn()
    conn.cur = CombinedCursor()

    tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)
    out = capsys.readouterr().out
    run_end_lines = [line for line in out.splitlines() if '"event": "run_end"' in line]
    assert run_end_lines, "expected a run_end log event"
    final = json.loads(run_end_lines[-1])
    assert final.get("stage1_mode") is None
    assert final.get("stage1_fallback") is False


# ------------------------------------------------------------ dry-run output --

def test_main_dry_run_prints_stage1_selection_block(monkeypatch, capsys):
    monkeypatch.setattr(tb, "TWITTER_BOT_DRY_RUN", True)
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [
            _alert(id=1, composite_score=9.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, composite_score=8.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([
        _stage1_shortlist(1, 2, mode="single"),
        {"decision": "post", "reason": "ok", "alert_ids": [1],
         "tweet": "hello link in bio", "is_composite": False},
    ])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []
    conn = RecordingConn()
    conn.cur = CombinedCursor()

    tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)
    out = capsys.readouterr().out

    assert "Stage 1 selection: single (2 alerts)" in out
    # Each shortlisted alert id appears in the block:
    assert "#1" in out
    assert "#2" in out
    # Angles appear:
    assert "angle for 1" in out


def test_main_dry_run_prints_stage1_skip_block(monkeypatch, capsys):
    monkeypatch.setattr(tb, "TWITTER_BOT_DRY_RUN", True)
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [_alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat())],
        "total": 1, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    llm = FakeLLMClient([_stage1_skip("nothing compelling")])
    twitter = FakeTwitterClient()

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []
    conn = RecordingConn()
    conn.cur = CombinedCursor()

    tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)
    out = capsys.readouterr().out

    assert "Stage 1 skip:" in out
    assert "nothing compelling" in out


def test_main_stage1_invalid_logs_raw_output(monkeypatch, capsys):
    """When stage-1 LLM emits malformed JSON, stage1_invalid carries raw_output."""
    now = datetime.now(timezone.utc)
    api_body = {
        "alerts": [
            _alert(id=1, composite_score=10.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
            _alert(id=2, composite_score=8.0,
                   created_at=(now - timedelta(minutes=5)).isoformat()),
        ],
        "total": 2, "page": 1, "per_page": 100,
    }
    http = FakeHTTP(api_body)
    bad = "{this is not valid json at all"
    final = {
        "decision": "post", "reason": "ok", "alert_ids": [1],
        "tweet": "ok. link in bio", "is_composite": False,
    }
    llm = FakeLLMClient([bad, final])
    twitter = FakeTwitterClient(tweet_id="42")

    class CombinedCursor(RecordingCursor):
        def fetchall(self):
            return []
    conn = RecordingConn()
    conn.cur = CombinedCursor()

    tb.main(http=http, llm_client=llm, twitter_client=twitter, db_conn=conn)
    out = capsys.readouterr().out
    invalid_lines = [line for line in out.splitlines() if '"event": "stage1_invalid"' in line]
    assert invalid_lines, "expected a stage1_invalid log event"
    event = json.loads(invalid_lines[-1])
    assert "raw_output" in event
    assert event["raw_output"] == bad  # raw_output contains the original bad content
