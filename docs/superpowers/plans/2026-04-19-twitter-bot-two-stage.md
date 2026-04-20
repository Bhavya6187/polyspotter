# Twitter Bot Two-Stage Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Twitter bot's composer into a stage-1 LLM call that picks 2-4 shortlisted alerts (with single/composite mode + per-alert angles) and a stage-2 call that researches only the shortlist and writes the tweet. On stage-1 failure, fall back to top-3 by score.

**Architecture:** Two new helpers (`select_shortlist`, `validate_shortlist_decision`) and a `ShortlistDecision` dataclass live in [backend/twitter_bot_agent.py](../../../backend/twitter_bot_agent.py). [backend/twitter_bot.py](../../../backend/twitter_bot.py)'s `call_llm` becomes the orchestration seam: stage 1 → fallback-or-skip → stage 2. `compose_tweet` is locked to the shortlist; `validate_decision` is locked to the shortlisted IDs + mode. No new endpoints, no schema changes, no env flag.

**Tech Stack:** Python 3.13, OpenAI SDK (Azure deployment, model `gpt-5.4`), pytest, psycopg2 (Postgres), sqlite3 (`polybot.db`), tweepy.

**Spec:** [docs/superpowers/specs/2026-04-19-twitter-bot-two-stage-design.md](../specs/2026-04-19-twitter-bot-two-stage-design.md)

**Setup before starting:**
- Activate venv: `source venv/bin/activate`
- All test commands run from repo root: `cd backend && pytest <args>`
- `.env` and DB connection are not required for unit tests — fakes inject everything.

---

## Task 1: Stage-1 types and validator

**Files:**
- Modify: `backend/twitter_bot_agent.py` (add new dataclasses + validator near top, after the existing `class AgentOutputError` block around line 32)
- Modify: `backend/test_twitter_bot_agent.py` (append new test section at end)

**What this task does:** Adds the `ShortlistDecision` and `ShortlistItem` dataclasses, the `ShortlistValidationError` exception, and the pure-function `validate_shortlist_decision(raw, *, valid_alert_ids)` that converts a parsed JSON dict from stage 1 into a typed `ShortlistDecision` (or raises). No LLM, no I/O.

- [ ] **Step 1: Write failing tests for the validator**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ============================================================================
# Stage 1 — validate_shortlist_decision
# ============================================================================

def test_validate_shortlist_skip_decision_succeeds_with_minimal_fields():
    raw = {"decision": "skip", "reason": "all routine"}
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3})
    assert result.decision == "skip"
    assert result.reason == "all routine"
    assert result.mode is None
    assert result.shortlist is None


def test_validate_shortlist_single_mode_with_two_items_succeeds():
    raw = {
        "decision": "shortlist", "reason": "two strong picks",
        "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "20-0 wallet sized up"},
            {"alert_id": 2, "angle": "new wallet near close"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3})
    assert result.decision == "shortlist"
    assert result.mode == "single"
    assert len(result.shortlist) == 2
    assert result.shortlist[0].alert_id == 1
    assert result.shortlist[0].angle == "20-0 wallet sized up"


def test_validate_shortlist_composite_mode_with_three_items_succeeds():
    raw = {
        "decision": "shortlist", "reason": "shared funder cluster",
        "mode": "composite",
        "shortlist": [
            {"alert_id": 1, "angle": "wallet A"},
            {"alert_id": 2, "angle": "wallet B (same funder)"},
            {"alert_id": 3, "angle": "wallet C (same funder)"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3, 4})
    assert result.mode == "composite"
    assert len(result.shortlist) == 3


def test_validate_shortlist_rejects_unknown_decision_value():
    raw = {"decision": "maybe", "reason": "x"}
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1})


def test_validate_shortlist_rejects_missing_mode_on_shortlist():
    raw = {
        "decision": "shortlist", "reason": "x",
        "shortlist": [{"alert_id": 1, "angle": "a"}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_invalid_mode_value():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "ensemble",
        "shortlist": [{"alert_id": 1, "angle": "a"}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_size_one():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": 1, "angle": "only one"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1})


def test_validate_shortlist_rejects_size_five():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": i, "angle": f"a{i}"} for i in (1, 2, 3, 4, 5)],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2, 3, 4, 5})


def test_validate_shortlist_rejects_alert_id_not_in_input():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 99, "angle": "b"},  # 99 not in input
        ],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_empty_angle():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": ""},
            {"alert_id": 2, "angle": "b"},
        ],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_missing_angle():
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [{"alert_id": 1}, {"alert_id": 2, "angle": "b"}],
    }
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})


def test_validate_shortlist_rejects_non_dict_input():
    with pytest.raises(agent.ShortlistValidationError):
        agent.validate_shortlist_decision("not a dict", valid_alert_ids={1})


def test_validate_shortlist_composite_with_two_items_succeeds():
    """Composite needs >= 2; size 2 is the minimum and should pass."""
    raw = {
        "decision": "shortlist", "reason": "x", "mode": "composite",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 2, "angle": "b"},
        ],
    }
    result = agent.validate_shortlist_decision(raw, valid_alert_ids={1, 2})
    assert result.mode == "composite"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "validate_shortlist"
```

Expected: 12 failures, all with `AttributeError: module 'twitter_bot_agent' has no attribute 'ShortlistValidationError'` or `validate_shortlist_decision`.

- [ ] **Step 3: Add the dataclasses, exception, and validator**

In `backend/twitter_bot_agent.py`, locate the existing exception block:

```python
class ProjectionError(Exception):
    """Raised when a JMESPath expression fails to compile or evaluate."""


class AgentOutputError(Exception):
    """Raised when the agent fails to produce valid final JSON."""
```

Immediately after `AgentOutputError`, insert:

```python
class ShortlistValidationError(Exception):
    """Raised when stage-1 LLM output fails validation."""


@dataclass
class ShortlistItem:
    """One alert chosen by stage 1, with the angle stage 1 wants stage 2 to verify."""
    alert_id: int
    angle: str


@dataclass
class ShortlistDecision:
    """Result of stage 1.

    decision = "shortlist": shortlist + mode are populated.
    decision = "skip":      shortlist + mode are None; reason explains why.
    """
    decision: str
    reason: str
    mode: str | None
    shortlist: list[ShortlistItem] | None


_VALID_MODES = {"single", "composite"}


def validate_shortlist_decision(raw, *, valid_alert_ids: set[int]) -> ShortlistDecision:
    """Parse and validate the stage-1 LLM JSON output.

    Returns a ShortlistDecision on success. Raises ShortlistValidationError on
    any rule violation. `valid_alert_ids` is the set of alert IDs the LLM was
    allowed to choose from (i.e. the top-N input set).

    Rules:
      - raw must be a dict.
      - decision must be 'shortlist' or 'skip'.
      - skip → only `reason` matters; mode and shortlist are returned as None.
      - shortlist requires mode in {single, composite} and a list of 2-4 items,
        each with an int alert_id (∈ valid_alert_ids) and a non-empty angle.
    """
    if not isinstance(raw, dict):
        raise ShortlistValidationError(f"raw must be dict, got {type(raw).__name__}")

    decision = raw.get("decision")
    reason = raw.get("reason") or ""

    if decision == "skip":
        return ShortlistDecision(decision="skip", reason=reason, mode=None, shortlist=None)

    if decision != "shortlist":
        raise ShortlistValidationError(f"unknown decision value: {decision!r}")

    mode = raw.get("mode")
    if mode not in _VALID_MODES:
        raise ShortlistValidationError(f"mode must be one of {_VALID_MODES}, got {mode!r}")

    shortlist_raw = raw.get("shortlist")
    if not isinstance(shortlist_raw, list) or not (2 <= len(shortlist_raw) <= 4):
        raise ShortlistValidationError(
            f"shortlist must be a list of 2-4 items, got {shortlist_raw!r}"
        )

    items: list[ShortlistItem] = []
    for i, item in enumerate(shortlist_raw):
        if not isinstance(item, dict):
            raise ShortlistValidationError(f"shortlist[{i}] must be dict, got {item!r}")
        try:
            alert_id = int(item["alert_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ShortlistValidationError(f"shortlist[{i}].alert_id invalid: {exc}") from exc
        if alert_id not in valid_alert_ids:
            raise ShortlistValidationError(
                f"shortlist[{i}].alert_id {alert_id} not in valid set {sorted(valid_alert_ids)}"
            )
        angle = item.get("angle")
        if not isinstance(angle, str) or not angle.strip():
            raise ShortlistValidationError(f"shortlist[{i}].angle must be a non-empty string")
        items.append(ShortlistItem(alert_id=alert_id, angle=angle.strip()))

    return ShortlistDecision(decision="shortlist", reason=reason, mode=mode, shortlist=items)
```

Note: `from dataclasses import dataclass` is currently imported further down in the file (line 426, above the `ToolDeps` dataclass). Hoist this import to the top-level imports block. In `backend/twitter_bot_agent.py`, at the top of the file, locate:

```python
from __future__ import annotations

import json
from typing import Any

import jmespath
```

Replace with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jmespath
```

Then **delete** the now-redundant `from dataclasses import dataclass` line (currently at line 426, just above `@dataclass\nclass ToolDeps:`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "validate_shortlist"
```

Expected: 12 passes.

- [ ] **Step 5: Run full test file to verify no regressions**

```bash
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all existing tests still pass + 12 new ones.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git commit -m "feat(twitter-bot): add stage-1 ShortlistDecision types and validator"
```

---

## Task 2: `select_shortlist` LLM call

**Files:**
- Modify: `backend/twitter_bot_agent.py` (add `STAGE1_SYSTEM_PROMPT`, `build_stage1_user_message`, `select_shortlist`)
- Modify: `backend/test_twitter_bot_agent.py` (append new tests)

**What this task does:** Adds the stage-1 system prompt, the user-message builder for stage 1, and `select_shortlist(top_alerts, *, llm_client) → ShortlistDecision`. One LLM call, JSON mode, no tools. Wraps the validator from Task 1.

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ============================================================================
# Stage 1 — select_shortlist
# ============================================================================

class FakeStage1LLM:
    """One-shot LLM fake. Returns the scripted content on first .create() call."""

    def __init__(self, response):
        # response: dict (returned as JSON content) or str (returned raw)
        self._response = response
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, dict):
            content = json.dumps(self._response)
        else:
            content = self._response
        msg = SimpleNamespace(content=content, tool_calls=None, role="assistant")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _stage1_alert(**overrides):
    """Slim alert dict shaped like what the bot passes into select_shortlist."""
    base = {
        "id": 1,
        "composite_score": 8.0,
        "llm_headline": "Whale loads X",
        "llm_summary": "Wallet dropped $25k.",
        "wallet": "0xa",
        "win_rate": 0.82,
        "total_usd": 25000.0,
        "market_title": "Will X happen?",
        "tags": ["Politics"],
        "condition_id": "0xcond",
        "event_slug": "ev-1",
    }
    base.update(overrides)
    return base


def test_select_shortlist_returns_skip_decision():
    llm = FakeStage1LLM({"decision": "skip", "reason": "nothing compelling"})
    result = agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)
    assert result.decision == "skip"
    assert result.reason == "nothing compelling"


def test_select_shortlist_returns_single_mode_with_angles():
    llm = FakeStage1LLM({
        "decision": "shortlist", "reason": "two clear picks", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "20-0 wallet"},
            {"alert_id": 2, "angle": "new wallet near close"},
        ],
    })
    result = agent.select_shortlist(
        [_stage1_alert(id=1), _stage1_alert(id=2), _stage1_alert(id=3)],
        llm_client=llm,
    )
    assert result.mode == "single"
    assert [s.alert_id for s in result.shortlist] == [1, 2]
    assert result.shortlist[0].angle == "20-0 wallet"


def test_select_shortlist_raises_on_invalid_json():
    llm = FakeStage1LLM("{not valid json")
    with pytest.raises(agent.ShortlistValidationError):
        agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)


def test_select_shortlist_raises_on_alert_id_not_in_input():
    llm = FakeStage1LLM({
        "decision": "shortlist", "reason": "x", "mode": "single",
        "shortlist": [
            {"alert_id": 1, "angle": "a"},
            {"alert_id": 999, "angle": "b"},
        ],
    })
    with pytest.raises(agent.ShortlistValidationError):
        agent.select_shortlist([_stage1_alert(id=1), _stage1_alert(id=2)], llm_client=llm)


def test_select_shortlist_makes_exactly_one_llm_call_with_json_mode():
    llm = FakeStage1LLM({"decision": "skip", "reason": "x"})
    agent.select_shortlist([_stage1_alert(id=1)], llm_client=llm)
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["model"] == agent.MODEL
    assert call["response_format"] == {"type": "json_object"}
    assert "tools" not in call  # stage 1 has no tools


def test_select_shortlist_user_message_includes_slim_alert_fields():
    """Stage-1 payload should include enough for editorial judgment, not trade detail."""
    llm = FakeStage1LLM({"decision": "skip", "reason": "x"})
    agent.select_shortlist(
        [_stage1_alert(id=42, market_title="Tigers vs Red Sox", win_rate=0.91)],
        llm_client=llm,
    )
    user_msg = next(m for m in llm.calls[0]["messages"] if m["role"] == "user")
    # Required fields appear:
    assert "42" in user_msg["content"]
    assert "Tigers vs Red Sox" in user_msg["content"]
    # Bullets / copy_action / market_description NOT included (slim payload):
    assert "llm_bullets" not in user_msg["content"]
    assert "llm_copy_action" not in user_msg["content"]
    assert "market_description" not in user_msg["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "select_shortlist"
```

Expected: 6 failures (function doesn't exist).

- [ ] **Step 3: Add the system prompt, user-message builder, and `select_shortlist`**

In `backend/twitter_bot_agent.py`, insert the following block immediately before the existing `MODEL = "gpt-5.4"` line (currently at line 651). The MODEL constant must already exist; if it's defined here, leave it.

```python
STAGE1_SYSTEM_PROMPT = (
    "You are the editor for the PolySpotter Twitter feed. Each hour you see "
    "up to 20 candidate alerts (notable Polymarket bets surfaced by our scanner). "
    "Your job is to pick the 2-4 alerts most likely to make a great tweet — "
    "OR skip the hour if nothing is compelling.\n\n"

    "## How to choose\n"
    "- Pick the FEWEST alerts that work: 2 if there's one clear story plus a backup, "
    "3-4 if you're genuinely torn between several.\n"
    "- 'Most tweetable' is not the same as 'highest composite_score'. Look for "
    "specific, surprising, story-rich bets — sharp wallets, big size, unusual "
    "timing, named themes.\n"
    "- Skip the hour if every alert feels routine or low-signal.\n\n"

    "## Single vs composite\n"
    "- mode='single': you want a tweet about ONE alert. Stage 2 will pick the "
    "strongest from your shortlist; the others are backups in case the first "
    "doesn't hold up to research.\n"
    "- mode='composite': the alerts share a tight thread — same wallet across "
    "markets, same event, shared funder cluster, same theme — and they belong "
    "in ONE tweet together. Only pick composite if you'd genuinely combine them. "
    "Never force synthesis.\n\n"

    "## The angle field\n"
    "For each shortlisted alert, write one short sentence describing the STORY "
    "you'd want the tweet to tell. Not a recap of the headline — the angle "
    "(e.g., 'verify this wallet is actually 20-0 and size is 25× their average', "
    "or '3 wallets sharing a funder all loaded the under in the last 40 min'). "
    "Stage 2 will use your angle to focus its research tools.\n\n"

    "## Output format (strict JSON)\n"
    'For shortlist:\n'
    '{\n'
    '  "decision": "shortlist",\n'
    '  "reason": "one short sentence on why these",\n'
    '  "mode": "single" | "composite",\n'
    '  "shortlist": [\n'
    '    {"alert_id": <int>, "angle": "<short story>"},\n'
    '    ...\n'
    '  ]\n'
    '}\n\n'
    'For skip:\n'
    '{"decision": "skip", "reason": "one short sentence"}\n\n'
    "alert_id values must be integers drawn from the alerts you were shown."
)


def build_stage1_user_message(top_alerts: list[dict]) -> str:
    """Slim payload for stage 1 — fields needed for editorial judgment, no trade detail."""
    payload = []
    for a in top_alerts:
        payload.append({
            "alert_id": int(a["id"]),
            "composite_score": a.get("composite_score"),
            "llm_headline": a.get("llm_headline"),
            "llm_summary": a.get("llm_summary"),
            "wallet": a.get("wallet"),
            "wallet_win_rate": a.get("win_rate"),
            "total_usd": a.get("total_usd"),
            "market_title": a.get("market_title"),
            "tags": a.get("tags") or [],
            "condition_id": a.get("condition_id"),
            "event_slug": a.get("event_slug"),
        })
    return json.dumps({"alerts": payload}, default=str)


def select_shortlist(top_alerts: list[dict], *, llm_client) -> ShortlistDecision:
    """Run stage 1: LLM picks 2-4 alerts (with mode + angles) or decides to skip.

    Single LLM call, JSON mode, no tools. Raises ShortlistValidationError if the
    output is malformed; raises any LLM-client exception unchanged. Caller
    (twitter_bot.call_llm) is responsible for the fallback path.
    """
    valid_alert_ids = {int(a["id"]) for a in top_alerts}
    messages = [
        {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
        {"role": "user", "content": build_stage1_user_message(top_alerts)},
    ]
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.7,
        max_completion_tokens=400,
    )
    content = response.choices[0].message.content or ""
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ShortlistValidationError(f"non-JSON content: {exc}") from exc
    return validate_shortlist_decision(raw, valid_alert_ids=valid_alert_ids)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "select_shortlist"
```

Expected: 6 passes.

- [ ] **Step 5: Run full agent test file**

```bash
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git commit -m "feat(twitter-bot): add stage-1 select_shortlist LLM call"
```

---

## Task 3: `build_user_message` accepts `selection`

**Files:**
- Modify: `backend/twitter_bot_agent.py` (extend `build_user_message` at ~line 719)
- Modify: `backend/test_twitter_bot_agent.py` (append new tests)

**What this task does:** Adds an optional `selection` kwarg to `build_user_message`. When provided, includes a top-level `selection: {mode, angles}` field in the output JSON. Backwards-compatible — current callers continue to work.

- [ ] **Step 1: Write failing tests**

Append to `backend/test_twitter_bot_agent.py`:

```python
# ============================================================================
# build_user_message — selection arg
# ============================================================================

def test_build_user_message_without_selection_omits_selection_field():
    msg = agent.build_user_message([_alert(id=1)])
    parsed = json.loads(msg)
    assert "selection" not in parsed
    assert len(parsed["alerts"]) == 1


def test_build_user_message_with_selection_includes_mode_and_angles():
    selection = {"mode": "single", "angles": {"1": "verify 20-0 record", "2": "new wallet"}}
    msg = agent.build_user_message([_alert(id=1), _alert(id=2)], selection=selection)
    parsed = json.loads(msg)
    assert parsed["selection"]["mode"] == "single"
    assert parsed["selection"]["angles"]["1"] == "verify 20-0 record"
    assert parsed["selection"]["angles"]["2"] == "new wallet"


def test_build_user_message_with_composite_selection_passes_through():
    selection = {"mode": "composite", "angles": {"1": "wallet A"}}
    msg = agent.build_user_message([_alert(id=1)], selection=selection)
    parsed = json.loads(msg)
    assert parsed["selection"]["mode"] == "composite"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "build_user_message"
```

Expected: 3 failures (function doesn't accept `selection` kwarg).

- [ ] **Step 3: Update `build_user_message`**

Replace the existing `build_user_message` function (currently around line 719) with:

```python
def build_user_message(top_alerts: list[dict], *, selection: dict | None = None) -> str:
    """Build the JSON payload describing the shortlisted alerts.

    Includes every field an investigative composer needs to call deeper tools:
    condition_id, event_slug, end_date, market_description, llm_bullets.

    When `selection` is provided (from stage 1), it is included as a top-level
    `selection: {mode, angles}` field so stage 2 knows the chosen mode and
    each alert's suggested angle.
    """
    payload = []
    for a in top_alerts:
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
    body: dict = {"alerts": payload}
    if selection is not None:
        body["selection"] = selection
    return json.dumps(body, default=str)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "build_user_message"
```

Expected: 3 passes.

- [ ] **Step 5: Verify no other tests broke**

```bash
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all green (the existing `compose_tweet_user_message_includes_condition_id_and_event_slug` test still passes — `selection` defaults to None).

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git commit -m "feat(twitter-bot): build_user_message accepts optional selection arg"
```

---

## Task 4: `compose_tweet` accepts `shortlist_decision`

**Files:**
- Modify: `backend/twitter_bot_agent.py` (`compose_tweet` signature + body around line 749)
- Modify: `backend/test_twitter_bot_agent.py` (update existing `compose_tweet` tests + add new ones)

**What this task does:** Adds a required `shortlist_decision: ShortlistDecision` kwarg to `compose_tweet`. The function filters `top_alerts` to only the shortlisted IDs and passes a `selection` dict into `build_user_message`. Existing tests must be updated to pass a `shortlist_decision`.

- [ ] **Step 1: Add a test helper for building a default `ShortlistDecision`**

Append to `backend/test_twitter_bot_agent.py` (above the existing `# ----------------- compose_tweet ---` marker if possible, otherwise just at the end):

```python
# ============================================================================
# compose_tweet — shortlist_decision integration
# ============================================================================

def _shortlist(*alert_ids, mode="single", angles=None):
    """Build a simple ShortlistDecision for tests."""
    if angles is None:
        angles = {aid: f"angle for {aid}" for aid in alert_ids}
    return agent.ShortlistDecision(
        decision="shortlist",
        reason="test shortlist",
        mode=mode,
        shortlist=[
            agent.ShortlistItem(alert_id=int(aid), angle=angles[aid])
            for aid in alert_ids
        ],
    )


def test_compose_tweet_filters_top_alerts_to_shortlist():
    """User message should only contain alerts from the shortlist, not the full input."""
    captured = {}
    llm = FakeLLMWithTools([{
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }])
    orig_create = llm.chat.completions.create
    def wrapped(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return orig_create(**kwargs)
    llm.chat.completions.create = wrapped

    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    agent.compose_tweet(
        [_alert(id=1), _alert(id=2), _alert(id=3), _alert(id=4)],
        llm_client=llm, deps=deps,
        shortlist_decision=_shortlist(1, 3),  # only 1 and 3 are shortlisted
    )
    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    parsed = json.loads(user_msg["content"])
    ids = {int(a["alert_id"]) for a in parsed["alerts"]}
    assert ids == {1, 3}


def test_compose_tweet_user_message_includes_selection_mode_and_angles():
    captured = {}
    llm = FakeLLMWithTools([{
        "decision": "skip", "reason": "x", "alert_ids": None,
        "tweet": None, "is_composite": False,
    }])
    orig_create = llm.chat.completions.create
    def wrapped(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return orig_create(**kwargs)
    llm.chat.completions.create = wrapped

    deps = agent.ToolDeps(http=None, api_url=None, db_conn_pg=None, db_conn_sqlite=None)
    sd = _shortlist(1, 2, mode="composite", angles={1: "wallet A", 2: "wallet B same funder"})
    agent.compose_tweet(
        [_alert(id=1), _alert(id=2)],
        llm_client=llm, deps=deps, shortlist_decision=sd,
    )
    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    parsed = json.loads(user_msg["content"])
    assert parsed["selection"]["mode"] == "composite"
    assert parsed["selection"]["angles"]["1"] == "wallet A"
    assert parsed["selection"]["angles"]["2"] == "wallet B same funder"
```

- [ ] **Step 2: Update existing compose_tweet tests to pass shortlist_decision**

The existing tests pass `[_alert(id=1)]` and call `compose_tweet(alerts, llm_client=llm, deps=deps)` without a shortlist. After the signature change they must pass a shortlist. Edit each existing call to `agent.compose_tweet(...)` in `backend/test_twitter_bot_agent.py`:

In **`test_compose_tweet_zero_tool_calls_returns_decision`** — change:
```python
result = agent.compose_tweet([_alert(id=1)], llm_client=llm, deps=deps)
```
to:
```python
result = agent.compose_tweet(
    [_alert(id=1)], llm_client=llm, deps=deps,
    shortlist_decision=_shortlist(1, 2),
)
```
Also update the input list to include id=2 so the shortlist is satisfiable: `[_alert(id=1), _alert(id=2)]`.

Apply the same pattern (add 2nd alert + `shortlist_decision=_shortlist(1, 2)`) to:
- `test_compose_tweet_uses_tool_result_then_composes`
- `test_compose_tweet_exhausts_budget_forcing_final_json`
- `test_compose_tweet_single_turn_over_budget_truncates_dispatched`
- `test_compose_tweet_raises_on_max_iterations_without_final_json`
- `test_compose_tweet_raises_on_malformed_final_json`
- `test_compose_tweet_invokes_on_tool_call_callback_per_dispatch`
- `test_compose_tweet_user_message_includes_condition_id_and_event_slug`

For each, the input list becomes `[_alert(id=1), _alert(id=2)]` (or include the alert with whatever non-default `id` the test uses) and add `shortlist_decision=_shortlist(1, 2, ...)` matching those IDs.

- [ ] **Step 3: Run tests to verify the new ones fail and the old ones fail with TypeError**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "compose_tweet"
```

Expected: new tests fail (`unexpected keyword argument 'shortlist_decision'`); existing updated tests now also fail (same reason).

- [ ] **Step 4: Update `compose_tweet` signature and body**

In `backend/twitter_bot_agent.py`, replace the existing `compose_tweet` function (around line 749) with:

```python
def compose_tweet(
    top_alerts: list[dict],
    *,
    llm_client,
    deps: ToolDeps,
    shortlist_decision: ShortlistDecision,
    on_tool_call=None,
) -> dict:
    """Run the function-calling loop and return the final decision dict.

    Stage-2 entry point: receives a ShortlistDecision from stage 1 and
    operates only on the shortlisted alerts.

    If `on_tool_call` is provided, it's invoked as `on_tool_call(name, args, envelope)`
    after each tool dispatch (including budget-exhausted ones), giving callers a
    streaming view of what the agent did.

    Raises AgentOutputError if the model fails to emit a valid final JSON
    response within MAX_ITERATIONS.
    """
    if shortlist_decision.shortlist is None:
        raise ValueError("compose_tweet requires a shortlist_decision with shortlist set")

    shortlisted_ids = {item.alert_id for item in shortlist_decision.shortlist}
    filtered = [a for a in top_alerts if int(a["id"]) in shortlisted_ids]
    selection = {
        "mode": shortlist_decision.mode,
        "angles": {str(item.alert_id): item.angle for item in shortlist_decision.shortlist},
    }

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(filtered, selection=selection)},
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

        if tool_calls:
            messages.append(_assistant_tool_message(msg))
            dispatched = 0
            for call in tool_calls:
                args = json.loads(call.function.arguments or "{}")
                if not forcing_final and dispatched < remaining:
                    env = dispatch_tool(call.function.name, args, deps=deps)
                    dispatched += 1
                else:
                    env = dispatch_tool_over_budget(call.function.name, deps=deps)
                if on_tool_call is not None:
                    on_tool_call(call.function.name, args, env)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(env, default=str),
                })
            tool_calls_used += dispatched
            if tool_calls_used >= MAX_TOOL_CALLS and not forcing_final:
                forcing_final = True
                messages.append({
                    "role": "user",
                    "content": (
                        "Tool budget exhausted. Return your final JSON decision now — "
                        "no more tool calls."
                    ),
                })
            continue

        content = msg.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentOutputError(f"final content was not valid JSON: {exc}") from exc

    raise AgentOutputError("agent exceeded MAX_ITERATIONS without final JSON")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot_agent.py -v -k "compose_tweet"
```

Expected: all green.

- [ ] **Step 6: Run full agent test file**

```bash
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/twitter_bot_agent.py backend/test_twitter_bot_agent.py
git commit -m "feat(twitter-bot): compose_tweet locked to stage-1 shortlist"
```

---

## Task 5: Trim stage-2 system prompt

**Files:**
- Modify: `backend/twitter_bot_agent.py` (`SYSTEM_PROMPT` around line 654)

**What this task does:** Removes the "Single vs composite" decision section from the stage-2 prompt (that decision is now upstream) and adds a "Selection context" paragraph telling stage 2 about the shortlist+angles+mode. Pure prompt edit — no test-driven steps; just verify nothing regresses.

- [ ] **Step 1: Update the prompt**

In `backend/twitter_bot_agent.py`, replace the existing `SYSTEM_PROMPT = (...)` block (currently around line 654) with:

```python
SYSTEM_PROMPT = (
    "You are the social media voice for PolySpotter, a service that surfaces "
    "notable Polymarket bets from sharp wallets, whales, and coordinated flow.\n\n"

    "## Selection context\n"
    "Stage 1 has already shortlisted 2-4 alerts and committed to a mode (single "
    "or composite). The user message includes a `selection` block with the mode "
    "and a per-alert `angles` map — each angle is the story stage 1 wants you "
    "to verify and sharpen. You may pivot to a stronger angle you discover "
    "during research, but you must respect the mode:\n"
    "- mode='single': feature ONE alert from the shortlist. Others are backups.\n"
    "- mode='composite': your tweet must reference all shortlisted alerts as a "
    "single weave (same wallet, same event, shared funders, same theme).\n\n"

    "## You have research tools\n"
    "You can call up to 10 tools before writing the tweet. Use them when "
    "digging deeper would sharpen the story. A good tweet cites a SPECIFIC "
    "fact the alert payload doesn't already contain (e.g., 'bought the Under "
    "at 0.35 — market now at 0.62', 'this wallet has late-timed 17 markets "
    "in 3 weeks', 'volume 12x'd in the last 4 hours'). Zero calls is fine if "
    "the alerts already tell a tight story.\n\n"

    "## JMESPath projection\n"
    "Every tool accepts an optional `projection` string (a JMESPath expression). "
    "Use it to pull narrow values without loading large blobs into context. "
    "Examples:\n"
    "  - `length(bet_history)` — just a count\n"
    "  - `{win_rate: win_rate, total_pnl: total_pnl}` — pick fields\n"
    "  - `bet_history[?won==`true`].pnl_usd` — filtered list\n"
    "  - `avg(bet_history[?won==`true`].entry_price)` — computed aggregate\n"
    "If the projection fails (bad JMESPath, null values, etc.), the envelope "
    "includes a `projection_error` field AND the raw (8KB-capped) data — you "
    "don't need a second call to recover. Use the raw data or retry with a "
    "safer expression (e.g., filter out nulls).\n\n"

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
    "If after research the shortlisted alerts don't actually support a strong "
    "tweet, return decision=skip with a short reason.\n\n"

    "## Output format (strict JSON, returned as your final assistant content)\n"
    '{\n'
    '  "decision": "post" | "skip",\n'
    '  "reason": "short string",\n'
    '  "alert_ids": [<int>, ...] | null,\n'
    '  "tweet": "<string ≤260 chars | null>",\n'
    '  "is_composite": true | false\n'
    '}\n'
    "alert_ids must be integers from the shortlist. is_composite must match "
    "the selection mode (true if mode=composite, false if mode=single)."
)
```

- [ ] **Step 2: Run all agent tests to confirm no regression**

```bash
cd backend && pytest test_twitter_bot_agent.py -v
```

Expected: all green. The prompt edit doesn't change any function signature or test assertion.

- [ ] **Step 3: Commit**

```bash
git add backend/twitter_bot_agent.py
git commit -m "refactor(twitter-bot): trim stage-2 prompt for shortlist contract"
```

---

## Task 6: `validate_decision` new signature

**Files:**
- Modify: `backend/twitter_bot.py` (`validate_decision` function around line 222)
- Modify: `backend/test_twitter_bot.py` (update existing `validate_decision` tests + add new ones)

**What this task does:** Replaces `top_alert_ids` with `shortlisted_ids` and adds a required `mode` arg. Composite-mode posts must reference the entire shortlisted set; single-mode posts must reference exactly one shortlisted ID.

- [ ] **Step 1: Update existing tests + add new tests**

In `backend/test_twitter_bot.py`, replace the entire `# ---------- validate_decision ---` test section (around line 339) with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest test_twitter_bot.py -v -k "validate_decision"
```

Expected: failures with `unexpected keyword argument 'shortlisted_ids'` or `'mode'`.

- [ ] **Step 3: Update `validate_decision`**

In `backend/twitter_bot.py`, replace the existing `validate_decision` function (around line 222) with:

```python
def validate_decision(
    decision: dict,
    shortlisted_ids: set[int],
    mode: str,
) -> tuple[bool, str]:
    """Validate the LLM's stage-2 decision dict. Returns (ok, error_message).

    Args:
        decision: the dict returned by compose_tweet.
        shortlisted_ids: the set of alert IDs stage 1 shortlisted (the only
            valid alert IDs the tweet may reference).
        mode: "single" or "composite", from the ShortlistDecision.

    Rules:
      - decision must be 'post' or 'skip'.
      - if 'skip', nothing else is checked (mode-agnostic).
      - if 'post':
          - alert_ids must be a non-empty list of ints, all ∈ shortlisted_ids.
          - tweet must be a non-empty string with length <= TWEET_MAX_CHARS.
          - mode='single':    len(alert_ids) == 1 AND is_composite is False.
          - mode='composite': set(alert_ids) == shortlisted_ids AND is_composite is True.
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

    unknown = [i for i in int_ids if i not in shortlisted_ids]
    if unknown:
        return False, f"alert_ids contains ids not in shortlist: {unknown}"

    is_composite = bool(decision.get("is_composite"))

    if mode == "single":
        if len(int_ids) != 1:
            return False, f"single-mode tweet must reference exactly one alert_id, got {len(int_ids)}"
        if is_composite:
            return False, "single-mode tweet must have is_composite=false"
    elif mode == "composite":
        if set(int_ids) != shortlisted_ids:
            return False, (
                f"composite-mode tweet must reference all shortlisted ids "
                f"{sorted(shortlisted_ids)}, got {sorted(int_ids)}"
            )
        if not is_composite:
            return False, "composite-mode tweet must have is_composite=true"
    else:
        return False, f"unknown mode: {mode!r}"

    tweet = decision.get("tweet") or ""
    if not isinstance(tweet, str) or not tweet.strip():
        return False, "tweet must be a non-empty string"
    if len(tweet) > TWEET_MAX_CHARS:
        return False, f"tweet length {len(tweet)} exceeds max {TWEET_MAX_CHARS}"

    return True, ""
```

- [ ] **Step 4: Run validate_decision tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot.py -v -k "validate_decision"
```

Expected: 11 passes.

- [ ] **Step 5: Run the full file (other tests will likely fail because `main()` still calls validate_decision with the old signature — that's fixed in Task 8)**

```bash
cd backend && pytest test_twitter_bot.py -v
```

Expected: `validate_decision` tests pass; some `main` tests will fail because of the signature mismatch in Task 8's territory. We'll fix those in Task 8. Note which tests fail; they should all be `test_main_*` cases that exercise the full flow.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "feat(twitter-bot): validate_decision enforces shortlist + mode"
```

---

## Task 7: `call_llm` orchestrates stage 1 → stage 2

**Files:**
- Modify: `backend/twitter_bot.py` (`call_llm` and `_shorten_tweet` around lines 144 and 195)
- Modify: `backend/test_twitter_bot.py` (update existing call_llm tests + add new ones)

**What this task does:** `call_llm` now runs stage 1, handles skip/fallback, calls stage 2, applies the length retry, and returns `(ShortlistDecision, dict)` instead of just `dict`. Adds new telemetry events (`stage1_start`, `stage1_result`, `stage1_invalid`, `stage1_fallback`).

- [ ] **Step 1: Add new tests for the orchestration paths**

Replace the entire `# ---- call_llm --` test block in `backend/test_twitter_bot.py` (around line 191) with the following. The existing four tests are kept (with their LLM scripts updated to include a stage-1 step first), and four new tests are added.

Find the section starting with `# -------------- call_llm --` and replace through (but not including) `# ---------- validate_decision --` with:

```python
# ------------------------------------------------------------------ call_llm --

class FakeLLMClient:
    """Stand-in that scripts the LLM call sequence.

    `responses` is a list of steps. Each step is either:
      - a final decision dict (emitted as message.content)
      - a raw string (for malformed-JSON tests)
      - a list of (tool_name, arguments_dict) tuples (emitted as tool_calls)

    Each `create()` consumes one step from the list. Stage 1 consumes one step
    (its JSON output); stage 2 consumes 1+ steps (tool rounds + final).
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeLLMClient script exhausted")
        step = self._responses.pop(0)

        if isinstance(step, dict):
            msg = SimpleNamespace(
                content=json.dumps(step), tool_calls=None, role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        if isinstance(step, str):
            msg = SimpleNamespace(content=step, tool_calls=None, role="assistant")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

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
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            self.calls.append(kwargs)
            if self._first:
                self._first = False
                raise RuntimeError("stage-1 LLM down")
            msg = SimpleNamespace(
                content=json.dumps(self._second), tool_calls=None, role="assistant",
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest test_twitter_bot.py -v -k "call_llm"
```

Expected: failures across the board (call_llm signature/return changed; tests reference attributes like `sd.mode` that don't exist yet).

- [ ] **Step 3: Update `call_llm` and `_shorten_tweet`**

In `backend/twitter_bot.py`, replace `call_llm` (around line 144) and `_shorten_tweet` (around line 195) with:

```python
def call_llm(
    top_alerts: list[dict],
    *,
    llm_client,
    db_conn_pg=None,
    db_conn_sqlite=None,
    http=None,
    run_id: str | None = None,
):
    """Orchestrate stage 1 → stage 2 and return (ShortlistDecision, decision_dict).

    Stage 1: select_shortlist picks 2-4 alerts (or skips). On invalid output or
    LLM exception, falls back to a deterministic top-3-by-score shortlist.

    Stage 2: compose_tweet researches the shortlist and writes the tweet.
    Length-retry is applied to the stage-2 output.

    Returns:
        (shortlist_decision, decision_dict). On stage-1 skip, the decision dict
        is {"decision": "skip", "reason": shortlist_decision.reason} and stage 2
        is not invoked.
    """
    from twitter_bot_agent import (
        compose_tweet, select_shortlist, validate_shortlist_decision,
        ShortlistDecision, ShortlistItem, ShortlistValidationError, ToolDeps,
    )

    log_event("stage1_start", run_id=run_id, input_count=len(top_alerts))

    # --- Stage 1 ---
    fallback = False
    try:
        shortlist_decision = select_shortlist(top_alerts, llm_client=llm_client)
    except ShortlistValidationError as exc:
        log_event("stage1_invalid", run_id=run_id, validation_error=str(exc)[:500])
        shortlist_decision = _build_fallback_shortlist(top_alerts)
        log_event("stage1_fallback", run_id=run_id, error=str(exc)[:500])
        fallback = True
    except Exception as exc:
        shortlist_decision = _build_fallback_shortlist(top_alerts)
        log_event("stage1_fallback", run_id=run_id, error=f"{type(exc).__name__}: {exc}"[:500])
        fallback = True

    log_event(
        "stage1_result",
        run_id=run_id,
        decision=shortlist_decision.decision,
        mode=shortlist_decision.mode,
        shortlist_ids=(
            [item.alert_id for item in shortlist_decision.shortlist]
            if shortlist_decision.shortlist else None
        ),
        reason=shortlist_decision.reason,
        fallback=fallback,
    )

    if shortlist_decision.decision == "skip":
        return shortlist_decision, {
            "decision": "skip",
            "reason": shortlist_decision.reason,
        }

    # --- Stage 2 ---
    deps = ToolDeps(
        http=http if http is not None else requests,
        api_url=POLYSPOTTER_API_URL,
        db_conn_pg=db_conn_pg,
        db_conn_sqlite=db_conn_sqlite,
    )

    def _on_tool_call(name: str, args: dict, envelope: dict) -> None:
        if TWITTER_BOT_DRY_RUN:
            proj = args.get("projection")
            other = {k: v for k, v in args.items() if k != "projection"}
            err = envelope.get("error")
            status = f"ERROR: {err}" if err else "ok"
            line = f"  tool  {name}  {other}"
            if proj:
                line += f"\n        proj: {proj}"
            line += f"\n        → {status}"
            print(line, flush=True)
            return
        log_event(
            "tool_call",
            run_id=run_id,
            name=name,
            args=args,
            error=envelope.get("error"),
            truncated=envelope.get("truncated", False),
        )

    decision = compose_tweet(
        top_alerts,
        llm_client=llm_client,
        deps=deps,
        shortlist_decision=shortlist_decision,
        on_tool_call=_on_tool_call,
    )

    tweet = decision.get("tweet") or ""
    if decision.get("decision") == "post" and len(tweet) > TWEET_MAX_CHARS:
        decision = _shorten_tweet(decision, top_alerts, shortlist_decision, llm_client=llm_client)

    return shortlist_decision, decision


def _build_fallback_shortlist(top_alerts: list[dict]):
    """Top-3 by composite_score, mode=single, no angles. Used on stage-1 failure."""
    from twitter_bot_agent import ShortlistDecision, ShortlistItem
    sorted_alerts = sorted(
        top_alerts, key=lambda a: a.get("composite_score", 0), reverse=True,
    )
    picks = sorted_alerts[:3]
    items = [ShortlistItem(alert_id=int(a["id"]), angle="") for a in picks]
    return ShortlistDecision(
        decision="shortlist",
        reason="stage-1 fallback: top by composite_score",
        mode="single",
        shortlist=items,
    )


def _shorten_tweet(decision: dict, top_alerts: list[dict], shortlist_decision, *, llm_client) -> dict:
    """One-shot non-agentic call to shorten an over-length tweet."""
    from twitter_bot_agent import SYSTEM_PROMPT, build_user_message
    original = decision.get("tweet") or ""
    shortlisted_ids = {item.alert_id for item in shortlist_decision.shortlist}
    filtered = [a for a in top_alerts if int(a["id"]) in shortlisted_ids]
    selection = {
        "mode": shortlist_decision.mode,
        "angles": {str(item.alert_id): item.angle for item in shortlist_decision.shortlist},
    }
    retry_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(filtered, selection=selection)},
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

Note: `_build_user_message` (the private wrapper at line 133) is no longer used by `call_llm` — `_shorten_tweet` now calls `build_user_message` directly with `selection`. You can delete `_build_user_message` from `twitter_bot.py` or leave it; it's not imported elsewhere. (Recommend deleting for cleanliness.)

Delete the existing `_build_user_message` function in `twitter_bot.py` (around line 133 — the one that begins `def _build_user_message(top_alerts: list[dict]) -> str:`).

- [ ] **Step 4: Run call_llm tests to verify they pass**

```bash
cd backend && pytest test_twitter_bot.py -v -k "call_llm"
```

Expected: 8 passes.

- [ ] **Step 5: Run full test_twitter_bot.py file (some `main` tests will still be broken — fixed in Task 8)**

```bash
cd backend && pytest test_twitter_bot.py -v
```

Expected: validate_decision and call_llm tests pass; some `test_main_*` tests fail because main() still passes the old signature into validate_decision and unpacks the wrong return shape. Note which.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "feat(twitter-bot): call_llm orchestrates stage 1 with fallback path"
```

---

## Task 8: Update `main()` for new return shape and telemetry

**Files:**
- Modify: `backend/twitter_bot.py` (`main` function around line 341)
- Modify: `backend/test_twitter_bot.py` (update `_alert` factory + existing main tests + add new tests)

**What this task does:** `main()` unpacks the `(ShortlistDecision, dict)` tuple from `call_llm`, passes the shortlist + mode into `validate_decision`, and logs `stage1_mode` + `stage1_fallback` in `run_end`. Existing main tests get their LLM scripts updated to include a stage-1 step.

- [ ] **Step 1: Add new tests for stage-1 telemetry in main()**

Append to `backend/test_twitter_bot.py`:

```python
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
    # Verify stage1_fallback event was logged.
    assert "stage1_fallback" in out


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
```

- [ ] **Step 2: Update existing `main` tests to script stage-1 first**

In `backend/test_twitter_bot.py`, locate each existing `test_main_*` test and prepend a `_stage1_shortlist(...)` step to its `FakeLLMClient` script. Specifically:

**`test_main_runs_full_flow_successfully`**: change
```python
llm = FakeLLMClient([{
    "decision": "post", ..., "alert_ids": [1], ...
}])
```
to
```python
llm = FakeLLMClient([
    _stage1_shortlist(1, 2),
    {"decision": "post", ..., "alert_ids": [1], ...},
])
```
Also ensure the input has at least 2 alerts in the lookback window so the shortlist has ≥2 valid IDs (already true: ids 1 and 2 are both included).

**`test_main_skips_cleanly_when_llm_says_skip`**: change to use `_stage1_skip(...)` only — the existing stage-2 skip dict becomes unreachable. New script:
```python
llm = FakeLLMClient([_stage1_skip("nothing compelling")])
```
(Drop the old stage-2 skip response. Stage-1 skip terminates before stage 2.)

**`test_main_exits_zero_with_no_candidates`**: leave LLM script empty (no candidates → no LLM calls). Already correct.

**`test_main_exits_one_on_validation_error`**: stage-1 shortlists alert 1, stage-2 references invalid id 999. Add at least 2 alerts so shortlist is satisfiable:
```python
api_body = {
    "alerts": [
        _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
        _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
    ],
    "total": 2, "page": 1, "per_page": 100,
}
...
llm = FakeLLMClient([
    _stage1_shortlist(1, 2),
    {"decision": "post", "reason": "x", "alert_ids": [999],
     "tweet": "ok", "is_composite": False},
])
```

**`test_main_post_error_does_not_write_to_db`**: similar — add 2nd alert + stage-1 step:
```python
api_body = {
    "alerts": [
        _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
        _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
    ],
    "total": 2, "page": 1, "per_page": 100,
}
...
llm = FakeLLMClient([
    _stage1_shortlist(1, 2),
    {"decision": "post", "reason": "x", "alert_ids": [1],
     "tweet": "ok", "is_composite": False},
])
```

**`test_main_dry_run_does_not_post_or_record`**: same pattern:
```python
api_body = {
    "alerts": [
        _alert(id=1, created_at=(now - timedelta(minutes=5)).isoformat()),
        _alert(id=2, created_at=(now - timedelta(minutes=5)).isoformat()),
    ],
    "total": 2, "page": 1, "per_page": 100,
}
...
llm = FakeLLMClient([
    _stage1_shortlist(1, 2),
    {"decision": "post", "reason": "x", "alert_ids": [1],
     "tweet": "hello link in bio", "is_composite": False},
])
```

- [ ] **Step 3: Run full test file to confirm everything fails appropriately**

```bash
cd backend && pytest test_twitter_bot.py -v -k "main"
```

Expected: most main tests fail (call_llm now returns a tuple; main hasn't been updated yet).

- [ ] **Step 4: Update `main()` in `backend/twitter_bot.py`**

Locate the body of `main()` (around line 341). Replace the section from "# 4. LLM (agentic composer)." through "# 5. Validate." (approximately lines 419-449) with:

```python
        # 4. LLM (two-stage agentic composer).
        from db import get_db as _get_sqlite_db
        try:
            db_conn_sqlite = _get_sqlite_db()
        except Exception as e:
            log_event("sqlite_open_error", run_id=run_id, error=str(e))
            db_conn_sqlite = None

        try:
            shortlist_decision, decision = call_llm(
                top_alerts,
                llm_client=llm_client,
                db_conn_pg=db_conn,
                db_conn_sqlite=db_conn_sqlite,
                http=http,
                run_id=run_id,
            )
        except Exception as e:
            log_event("llm_error", run_id=run_id, stage=2, error=str(e))
            return 1

        if decision.get("decision") == "skip":
            stage = 1 if shortlist_decision.decision == "skip" else 2
            log_event("llm_skip", run_id=run_id, stage=stage, reason=decision.get("reason"))
            log_event(
                "run_end", run_id=run_id, posted=False, reason="llm_skip",
                stage1_mode=shortlist_decision.mode or "skip",
                stage1_fallback=False,
            )
            return 0

        # 5. Validate.
        shortlisted_ids = {item.alert_id for item in shortlist_decision.shortlist}
        ok, err = validate_decision(decision, shortlisted_ids, shortlist_decision.mode)
        if not ok:
            log_event("validation_error", run_id=run_id, error=err, decision=decision)
            return 1
```

Then locate the `run_end` events for posted-success cases (in the "# 7. Record" section, two of them — one inside the dry-run branch, one for the regular post). Each needs `stage1_mode` and `stage1_fallback` fields appended.

The dry-run end (around current line 468):
```python
        if TWITTER_BOT_DRY_RUN:
            log_event("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
                      stage1_mode=shortlist_decision.mode,
                      stage1_fallback=("fallback" in (shortlist_decision.reason or "")))
            return 0
```

The recorded-success end (around current line 479):
```python
        log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
                  stage1_mode=shortlist_decision.mode,
                  stage1_fallback=("fallback" in (shortlist_decision.reason or "")))
        return 0
```

The record_error branch (around current line 476):
```python
            log_event("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
                      stage1_mode=shortlist_decision.mode,
                      stage1_fallback=("fallback" in (shortlist_decision.reason or "")))
            return 0
```

Note: `stage1_fallback` is detected here by checking if the shortlist_decision's reason contains the literal "fallback" string (set by `_build_fallback_shortlist` to `"stage-1 fallback: top by composite_score"`). This works because no other code path sets that exact substring.

Also update the no-candidates `run_end` at the start of `main` (around line 392) — it doesn't reach stage 1, so `stage1_mode=None`:
```python
        if not top_alerts:
            log_event("no_candidates", run_id=run_id)
            log_event("run_end", run_id=run_id, posted=False, reason="no_candidates",
                      stage1_mode=None, stage1_fallback=False)
            return 0
```

- [ ] **Step 5: Run all main tests**

```bash
cd backend && pytest test_twitter_bot.py -v -k "main"
```

Expected: all green.

- [ ] **Step 6: Run the full backend test suite**

```bash
cd backend && pytest -v
```

Expected: all green (test_twitter_bot.py + test_twitter_bot_agent.py + any unrelated existing tests).

- [ ] **Step 7: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "feat(twitter-bot): main() unpacks two-stage result and logs stage1 fields"
```

---

## Task 9: Dry-run output for stage 1

**Files:**
- Modify: `backend/twitter_bot.py` (`main` function — add new dry-run print block)
- Modify: `backend/test_twitter_bot.py` (add a capsys-based test)

**What this task does:** Adds a "Stage 1 selection" block to dry-run output, between the existing top-N candidates table and the tool-call trace.

- [ ] **Step 1: Write a failing test**

Append to `backend/test_twitter_bot.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && pytest test_twitter_bot.py -v -k "dry_run_prints_stage1"
```

Expected: 2 failures (output doesn't include the new block).

- [ ] **Step 3: Add the dry-run print block in `main()`**

In `backend/twitter_bot.py`, locate the section right before the `try: shortlist_decision, decision = call_llm(...)` block. We want to print the stage-1 selection AFTER stage 1 returns but BEFORE stage-2 tool calls happen. Since stage 1 happens inside `call_llm`, we can't print between them from `main()`.

Two options:
- (a) Pull stage-1 out of `call_llm` into `main()`. More invasive.
- (b) Print after `call_llm` returns, just BEFORE the validation/posting blocks. The tool-call lines from stage 2 will already have appeared via the `_on_tool_call` callback inside `call_llm`. The block would appear AFTER the tool trace, which is wrong order.
- (c) Add an optional `on_stage1_complete` callback to `call_llm` that fires right after stage 1 returns, before stage 2 starts.

Pick **(c)** — minimal coupling, correct ordering.

In `backend/twitter_bot_agent.py` — actually the orchestration is in `twitter_bot.py`'s `call_llm`. Adjust there.

Edit `call_llm` in `backend/twitter_bot.py` to accept an optional `on_stage1_complete` callback:

```python
def call_llm(
    top_alerts: list[dict],
    *,
    llm_client,
    db_conn_pg=None,
    db_conn_sqlite=None,
    http=None,
    run_id: str | None = None,
    on_stage1_complete=None,
):
    ...
    # After computing shortlist_decision and the stage1_result log_event:
    if on_stage1_complete is not None:
        on_stage1_complete(shortlist_decision, fallback)
    ...
```

Apply this hook: place the `if on_stage1_complete is not None:` line immediately after the `log_event("stage1_result", ...)` block (right before the `if shortlist_decision.decision == "skip":` check).

Then in `main()`, define the callback and pass it in:

```python
        def _on_stage1(sd, fallback):
            if not TWITTER_BOT_DRY_RUN:
                return
            if sd.decision == "skip":
                print(f"\n--- Stage 1 skip: {sd.reason} ---", flush=True)
                return
            if fallback:
                print(f"\n--- Stage 1 fallback: {sd.reason} — using top-{len(sd.shortlist)} by score ---", flush=True)
            else:
                print(
                    f"\n--- Stage 1 selection: {sd.mode} ({len(sd.shortlist)} alerts) ---",
                    flush=True,
                )
                print(f"  → reason: {sd.reason}", flush=True)
            for item in sd.shortlist:
                print(f"  #{item.alert_id}  {item.angle}", flush=True)
            print("", flush=True)

        try:
            shortlist_decision, decision = call_llm(
                top_alerts,
                llm_client=llm_client,
                db_conn_pg=db_conn,
                db_conn_sqlite=db_conn_sqlite,
                http=http,
                run_id=run_id,
                on_stage1_complete=_on_stage1,
            )
        except Exception as e:
            ...
```

Replace the existing `try: shortlist_decision, decision = call_llm(...)` block in `main()` with the version that defines `_on_stage1` and passes it.

- [ ] **Step 4: Run dry-run tests to confirm they pass**

```bash
cd backend && pytest test_twitter_bot.py -v -k "dry_run_prints_stage1"
```

Expected: 2 passes.

- [ ] **Step 5: Run the entire backend suite to confirm no regressions**

```bash
cd backend && pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/twitter_bot.py backend/test_twitter_bot.py
git commit -m "feat(twitter-bot): print stage-1 selection block in dry-run mode"
```

---

## Task 10: Manual end-to-end verification

**Files:** None modified.

**What this task does:** Runs the bot in dry-run mode against the real hosted API and confirms the new two-stage output looks correct end-to-end. This is the proof that nothing was missed in test coverage.

- [ ] **Step 1: Activate venv and run dry-run**

```bash
source venv/bin/activate
TWITTER_BOT_DRY_RUN=true python backend/twitter_bot.py
```

- [ ] **Step 2: Verify the dry-run output structure**

Expected sections in this order:
1. `{"event": "run_start", ...}`
2. `{"event": "candidates_fetched", "count": <N>}`
3. `{"event": "after_dedup", "count": <M>}`
4. `--- Top <M> candidate alerts ---` table (existing block, unchanged)
5. `{"event": "stage1_start", "input_count": <K>}` (K = min(M, 20))
6. `{"event": "stage1_result", ...}` with `decision`, `mode`, `shortlist_ids`, `reason`, `fallback`
7. EITHER:
   - `--- Stage 1 selection: <mode> (<N> alerts) ---` block with reason + per-alert angles, OR
   - `--- Stage 1 skip: <reason> ---` (and the run ends here), OR
   - `--- Stage 1 fallback: <error> — using top-N by score ---`
8. `tool ...` lines from stage 2 (existing format)
9. `{"event": "posted", ...}` and `--- Final tweet (N chars) ---`
10. `{"event": "run_end", ..., "stage1_mode": "...", "stage1_fallback": false}`

Confirm:
- Stage 2 only researches the 2-4 shortlisted condition_ids (not all 20).
- The final tweet's `alert_ids` are a subset of `stage1_result.shortlist_ids`.
- If `stage1_mode=composite`, the tweet's `alert_ids` set equals `shortlist_ids`.

- [ ] **Step 3: Confirm the existing scanner tests still pass (no cross-contamination)**

```bash
cd .. && source venv/bin/activate && pytest test/ -v
```

Expected: all green.

- [ ] **Step 4: No commit needed**

This task is verification only.

---

## Self-review notes

After writing, the plan was checked against the spec:

- **Spec coverage** ✓ — every section is implemented:
  - Stage 1 = Tasks 1-2 + 9 (output), Stage 2 changes = Tasks 3-5, validate_decision = Task 6, orchestration = Task 7, telemetry = Task 7-8, dry-run = Task 9, fallback = Task 7.
- **Type consistency** ✓ — `ShortlistDecision`, `ShortlistItem`, `validate_shortlist_decision`, `select_shortlist`, `compose_tweet(... shortlist_decision=...)`, `validate_decision(decision, shortlisted_ids, mode)` all used consistently across tasks.
- **Placeholder scan** ✓ — no TBD/TODO; every code step contains the actual code.
- **One callout:** The `stage1_fallback` boolean in run_end (Task 8) is detected via substring of the fallback reason. A cleaner approach would be a flag on `ShortlistDecision`, but adding that field would require touching Task 1's dataclass and validator (and tests). Substring detection works because `_build_fallback_shortlist` is the only producer of that exact reason string. This is acceptable for scope; if it ever bites, add a `fallback: bool = False` field to `ShortlistDecision` then.
