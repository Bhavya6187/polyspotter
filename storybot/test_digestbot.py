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


_TODAY_PICK = {
    "event_slug": "nba-finals",
    "title": "Will the Lakers win?",
    "market_url": "https://polyspotter.com/event/nba-finals",
    "leaning": "Lakers @ 0.55",
    "composite_score": 80.0,
}
_WEEK_PICK = {
    "event_slug": "election-x",
    "title": "Will X win?",
    "market_url": "https://polyspotter.com/event/election-x",
    "leaning": "Yes @ 0.40",
    "composite_score": 70.0,
}
_WRITE_OUT = {
    "subject": "PolySpotter Daily — test",
    "intro": "Big day.",
    "writeups": [
        {"event_slug": "nba-finals", "headline": "Sharps on the Lakers", "blurb": "Late informed flow."},
        {"event_slug": "election-x", "headline": "Quiet money on Yes", "blurb": "Coordinated buying."},
    ],
}


def test_assemble_content_merges_facts_from_picks():
    content = digestbot.assemble_content(
        _WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[_WEEK_PICK]
    )
    assert content["subject"] == "PolySpotter Daily — test"
    assert content["intro"] == "Big day."
    sections = {s["key"]: s for s in content["sections"]}
    today_item = sections["resolving_today"]["items"][0]
    # headline/blurb come from the LLM; leaning/url/title come from the DB pick
    assert today_item["headline"] == "Sharps on the Lakers"
    assert today_item["blurb"] == "Late informed flow."
    assert today_item["leaning"] == "Lakers @ 0.55"
    assert today_item["url"] == "https://polyspotter.com/event/nba-finals"
    assert today_item["title"] == "Will the Lakers win?"
    assert sections["top_this_week"]["items"][0]["leaning"] == "Yes @ 0.40"


def test_assemble_content_omits_empty_sections():
    content = digestbot.assemble_content(
        {"subject": "s", "intro": "", "writeups": [
            {"event_slug": "election-x", "headline": "h", "blurb": "b"}]},
        today_picks=[], week_picks=[_WEEK_PICK],
    )
    keys = {s["key"] for s in content["sections"]}
    assert keys == {"top_this_week"}


def test_render_email_html_contains_facts_and_is_inline():
    content = digestbot.assemble_content(
        _WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[_WEEK_PICK]
    )
    html = digestbot.render_email_html(content)
    assert "Sharps on the Lakers" in html
    assert "Lakers @ 0.55" in html
    assert "https://polyspotter.com/event/nba-finals" in html
    assert "Resolving Today" in html
    assert "Top This Week" in html
    # email-safe: no external/embedded stylesheet, inline styles only
    assert "<link" not in html.lower()
    assert "<style" not in html.lower()
