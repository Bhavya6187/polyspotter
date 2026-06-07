import json

import digestbot


def test_leaning_str_with_outcome_and_price():
    assert digestbot.leaning_str({"outcome": "Yes", "entry_price": 0.62}) == "Yes @ 0.62"


def test_leaning_str_outcome_only():
    assert digestbot.leaning_str({"outcome": "Lakers"}) == "Lakers"


def test_leaning_str_none():
    assert digestbot.leaning_str(None) == "No clear lean"
    assert digestbot.leaning_str({}) == "No clear lean"


def test_shape_candidate_parses_json_strings():
    row = {
        "event_slug": "nba-finals",
        "condition_id": "0xabc",
        "market_title": "Will the Lakers win?",
        "market_url": "https://polyspotter.com/event/nba-finals",
        "end_date": None,
        "event_end_estimate": None,
        "total_usd": 12000.0,
        "trade_count": 7,
        "composite_score": 80.0,
        "llm_copy_action": '{"outcome": "Lakers", "entry_price": 0.55}',
        "tags": '["Sports", "NBA"]',
    }
    c = digestbot.shape_candidate(row)
    assert c["event_slug"] == "nba-finals"
    assert c["title"] == "Will the Lakers win?"
    assert c["market_url"] == "https://polyspotter.com/event/nba-finals"
    assert c["total_usd"] == 12000.0
    assert c["trade_count"] == 7
    assert c["composite_score"] == 80.0
    assert c["leaning"] == "Lakers @ 0.55"


def test_dedupe_by_event_keeps_highest_composite():
    cands = [
        {"event_slug": "a", "composite_score": 30.0},
        {"event_slug": "a", "composite_score": 90.0},
        {"event_slug": "b", "composite_score": 50.0},
    ]
    out = digestbot.dedupe_by_event(cands)
    by_slug = {c["event_slug"]: c for c in out}
    assert len(out) == 2
    assert by_slug["a"]["composite_score"] == 90.0
    assert by_slug["b"]["composite_score"] == 50.0


def test_parse_json_response_plain():
    assert digestbot.parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_fenced():
    text = 'here you go:\n```json\n{"a": 2}\n```\nthanks'
    assert digestbot.parse_json_response(text) == {"a": 2}


def test_run_claude_builds_argv_and_passes_stdin(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        return FakeProc()

    monkeypatch.setattr(digestbot.subprocess, "run", fake_run)
    out = digestbot.run_claude("PROMPT", "PAYLOAD")
    assert out == '{"ok": true}'
    assert captured["argv"][:3] == ["claude", "-p", "PROMPT"]
    assert "--model" in captured["argv"]
    assert "opus" in captured["argv"]
    assert "--dangerously-skip-permissions" in captured["argv"]
    assert captured["input"] == "PAYLOAD"


def test_run_claude_json_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_run_claude(prompt, payload):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else '{"ok": 1}'

    monkeypatch.setattr(digestbot, "run_claude", fake_run_claude)
    assert digestbot.run_claude_json("P", "X") == {"ok": 1}
    assert calls["n"] == 2


def test_run_claude_json_raises_after_two_bad(monkeypatch):
    monkeypatch.setattr(digestbot, "run_claude", lambda p, x: "still not json")
    try:
        digestbot.run_claude_json("P", "X")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
