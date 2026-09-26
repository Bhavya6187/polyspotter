import json

import digestbot


def test_leaning_str_with_outcome_and_price():
    assert digestbot.leaning_str({"outcome": "Yes", "entry_price": 0.62}) == "Yes (62% implied)"


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
    assert c["leaning"] == "Lakers (55% implied)"


def test_category_label_broad_and_specific():
    assert digestbot.category_label(["Esports", "Dota 2", "Games", "Sports"]) == "Esports · Dota 2"
    assert digestbot.category_label(["Sports", "Games", "MLB", "baseball"]) == "Sports · MLB"


def test_category_label_broad_half_is_priority_ordered_not_tag_ordered():
    # 'Sports' precedes 'Esports' in the raw tags, but Esports wins by priority
    assert digestbot.category_label(["Sports", "Esports", "Dota 2"]) == "Esports · Dota 2"
    assert digestbot.category_label(["Esports", "Sports", "Dota 2"]) == "Esports · Dota 2"


def test_category_label_titlecases_only_lowercase_tags():
    # all-lowercase tag gets smart title-case; connectors stay lowercase
    assert digestbot.category_label(["Esports", "league of legends", "Games"]) == "Esports · League of Legends"
    # already-cased acronyms are left alone
    assert digestbot.category_label(["Politics", "Iran Ceasefire"]) == "Politics · Iran Ceasefire"


def test_category_label_drops_operational_junk():
    label = digestbot.category_label(
        ["Crypto", "Bitcoin", "Recurring", "Hide From New", "5M", "Rewards Automation 1000, 4.5, 100"]
    )
    assert label == "Crypto · Bitcoin"


def test_category_label_none_when_empty_or_all_junk():
    assert digestbot.category_label(None) is None
    assert digestbot.category_label([]) is None
    assert digestbot.category_label(["Recurring", "Hide From New", "Games"]) is None


def test_appeal_rank_tiers():
    assert digestbot.appeal_rank(["Politics", "Geopolitics", "Iran"]) == 0
    assert digestbot.appeal_rank(["Sports", "NBA"]) == 1
    assert digestbot.appeal_rank(["Crypto", "Bitcoin"]) == 2
    assert digestbot.appeal_rank(["Culture", "Movies"]) == 2  # unknown-ish → middle tier
    assert digestbot.appeal_rank(["Esports", "Dota 2", "Games"]) == 3


def test_appeal_rank_esports_beats_sports_tag():
    # esports markets are also tagged "Sports"; esports must win → tier 3, not 1
    assert digestbot.appeal_rank(["Esports", "league of legends", "Games", "Sports"]) == 3


def test_appeal_rank_handles_missing_or_bad_tags():
    assert digestbot.appeal_rank(None) == 2
    assert digestbot.appeal_rank([]) == 2


def test_order_by_appeal_tier_then_size():
    picks = [
        {"event_slug": "dota", "tags": ["Esports", "Dota 2"], "total_usd": 332000},
        {"event_slug": "iran", "tags": ["Politics", "Geopolitics"], "total_usd": 14000},
        {"event_slug": "nba", "tags": ["Sports", "NBA"], "total_usd": 294000},
    ]
    order = [p["event_slug"] for p in digestbot.order_by_appeal(picks)]
    # politics(0) < major sports(1) < esports(3), despite dota having the most money
    assert order == ["iran", "nba", "dota"]


def test_order_by_appeal_breaks_ties_by_dollar_size():
    picks = [
        {"event_slug": "small", "tags": ["Politics"], "total_usd": 11000},
        {"event_slug": "big", "tags": ["Politics"], "total_usd": 50000},
    ]
    order = [p["event_slug"] for p in digestbot.order_by_appeal(picks)]
    assert order == ["big", "small"]


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
    "leaning": "Lakers (55% implied)",
    "composite_score": 80.0,
}
_WEEK_PICK = {
    "event_slug": "election-x",
    "title": "Will X win?",
    "market_url": "https://polyspotter.com/event/election-x",
    "leaning": "Yes (40% implied)",
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
    assert today_item["leaning"] == "Lakers (55% implied)"
    # links now point to the on-site event page (not polymarket) and carry UTM
    assert today_item["url"] == (
        "https://polyspotter.com/event/nba-finals"
        "?utm_source=digest&utm_medium=email&utm_campaign=daily"
    )
    assert today_item["title"] == "Will the Lakers win?"
    assert sections["top_this_week"]["items"][0]["leaning"] == "Yes (40% implied)"


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
    assert "Lakers (55% implied)" in html
    assert "https://polyspotter.com/event/nba-finals" in html
    assert "Resolving Today" in html
    assert "Top This Week" in html
    # email-safe: no external/embedded stylesheet, inline styles only
    assert "<link" not in html.lower()
    assert "<style" not in html.lower()


def test_render_email_html_shows_category_chip():
    pick = dict(_TODAY_PICK, tags=["Esports", "Dota 2", "Games"])
    content = digestbot.assemble_content(
        _WRITE_OUT, today_picks=[pick], week_picks=[],
    )
    assert content["sections"][0]["items"][0]["category"] == "Esports · Dota 2"
    html = digestbot.render_email_html(content)
    assert "Esports · Dota 2" in html


def test_render_email_html_omits_chip_without_tags():
    # _TODAY_PICK has no tags → category is None → no chip element rendered
    content = digestbot.assemble_content(_WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[])
    assert content["sections"][0]["items"][0]["category"] is None


def test_render_email_html_unsubscribe_link_optional():
    content = digestbot.assemble_content(_WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[])
    # default: no unsubscribe line (preview / pasted version)
    assert "Unsubscribe" not in digestbot.render_email_html(content)
    # with a url: footer carries the link
    html = digestbot.render_email_html(content, unsubscribe_url="https://api.x/api/unsubscribe?token=abc")
    assert "Unsubscribe" in html
    assert "https://api.x/api/unsubscribe?token=abc" in html


def test_unsubscribe_url_uses_base(monkeypatch):
    monkeypatch.setattr(digestbot, "UNSUBSCRIBE_BASE_URL", "https://api.polyspotter.com")
    assert digestbot.unsubscribe_url("tok-123") == "https://api.polyspotter.com/api/unsubscribe?token=tok-123"


def test_send_digest_posts_per_recipient_with_unsubscribe(monkeypatch):
    monkeypatch.setattr(digestbot, "RESEND_API_KEY", "test_key")
    monkeypatch.setattr(digestbot, "DIGEST_FROM_EMAIL", "PolySpotter <team@polyspotter.com>")
    monkeypatch.setattr(digestbot, "UNSUBSCRIBE_BASE_URL", "https://api.polyspotter.com")
    posts = []

    class FakeResp:
        status_code = 200
        def json(self):
            return {"id": "email_abc"}

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append({"url": url, "json": json, "headers": headers})
        return FakeResp()

    monkeypatch.setattr(digestbot.requests, "post", fake_post)
    content = digestbot.assemble_content(_WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[])
    subs = [
        {"email": "a@x.com", "unsubscribe_token": "tok-a"},
        {"email": "b@x.com", "unsubscribe_token": "tok-b"},
    ]
    result = digestbot.send_digest(content, subs)
    assert result == {"sent": 2, "failed": 0}
    assert [p["json"]["to"] for p in posts] == [["a@x.com"], ["b@x.com"]]
    assert posts[0]["headers"]["Authorization"] == "Bearer test_key"
    assert posts[0]["json"]["from"] == "PolySpotter <team@polyspotter.com>"
    assert posts[0]["json"]["subject"] == content["subject"]
    # per-recipient unsubscribe wired into both the body and the List-Unsubscribe header
    assert "token=tok-a" in posts[0]["json"]["html"]
    assert posts[0]["json"]["headers"]["List-Unsubscribe"] == "<https://api.polyspotter.com/api/unsubscribe?token=tok-a>"
    assert posts[0]["json"]["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_send_digest_counts_failures_and_never_raises(monkeypatch):
    monkeypatch.setattr(digestbot, "RESEND_API_KEY", "test_key")

    class FakeResp:
        status_code = 422
        text = "domain not verified"
        def json(self):
            return {}

    def fake_post(url, json=None, headers=None, timeout=None):
        if json["to"] == ["bad@x.com"]:
            return FakeResp()
        raise digestbot.requests.RequestException("network down")

    monkeypatch.setattr(digestbot.requests, "post", fake_post)
    content = digestbot.assemble_content(_WRITE_OUT, today_picks=[_TODAY_PICK], week_picks=[])
    result = digestbot.send_digest(content, [
        {"email": "bad@x.com", "unsubscribe_token": "t1"},
        {"email": "boom@x.com", "unsubscribe_token": "t2"},
    ])
    assert result == {"sent": 0, "failed": 2}


def test_send_digest_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(digestbot, "RESEND_API_KEY", "")
    try:
        digestbot.send_digest({"subject": "s"}, [{"email": "a@x.com", "unsubscribe_token": "t"}])
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_parse_args_send_flag():
    assert digestbot._parse_args([]).send is False
    assert digestbot._parse_args(["--send"]).send is True


def test_output_dir_live_vs_dry(monkeypatch):
    monkeypatch.setattr(digestbot, "DRY_RUN", False)
    assert digestbot.output_dir() == digestbot.DIGESTS_DIR
    monkeypatch.setattr(digestbot, "DRY_RUN", True)
    assert digestbot.output_dir() == digestbot.DRY_RUNS_DIR


def test_persist_digest_skipped_in_dry_run(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(digestbot, "DRY_RUN", True)
    monkeypatch.setattr(digestbot, "_get_conn", lambda: (_ for _ in ()).throw(
        AssertionError("DB must not be touched in DRY_RUN")))
    # Should no-op without raising (DB connection never opened).
    digestbot.persist_digest("2026-06-06", "run123", {"subject": "s", "sections": []})
    assert called["n"] == 0


# --- Event-title grounding (regression: 2026-07-12 digest wrote "Women's World
# --- Cup" for a men's FIFA World Cup match whose market title never named the
# --- tournament or opponent) -------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_event_titles_maps_slug_to_title(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResp([
            {"slug": "fifwc-fra-esp-2026-07-14", "title": "France vs. Spain"},
            {"slug": "will-russia-capture-kostyantynivka-by",
             "title": "Will Russia capture Kostyantynivka by...?"},
        ])

    monkeypatch.setattr(digestbot.requests, "get", fake_get)
    titles = digestbot.fetch_event_titles(
        ["fifwc-fra-esp-2026-07-14", "will-russia-capture-kostyantynivka-by"])
    assert titles["fifwc-fra-esp-2026-07-14"] == "France vs. Spain"
    assert len(calls) == 1
    assert calls[0][0].endswith("/events")
    assert calls[0][1] == [("slug", "fifwc-fra-esp-2026-07-14"),
                           ("slug", "will-russia-capture-kostyantynivka-by")]


def test_fetch_event_titles_skips_condition_ids_dedupes_and_handles_empty(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _FakeResp([{"slug": "a", "title": "A vs. B"}])

    monkeypatch.setattr(digestbot.requests, "get", fake_get)
    titles = digestbot.fetch_event_titles(["0xdeadbeef", "a", "a", None])
    assert titles == {"a": "A vs. B"}
    assert calls == [[("slug", "a")]]
    # nothing real to look up -> no request at all
    assert digestbot.fetch_event_titles(["0xdeadbeef"]) == {}
    assert len(calls) == 1


def test_fetch_event_titles_returns_empty_on_network_error(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise digestbot.requests.RequestException("gamma down")

    monkeypatch.setattr(digestbot.requests, "get", fake_get)
    assert digestbot.fetch_event_titles(["a", "b"]) == {}


def test_attach_event_titles_sets_only_known():
    picks = [{"event_slug": "a"}, {"event_slug": "b"}]
    digestbot.attach_event_titles(picks, {"a": "A vs. B"})
    assert picks[0]["event_title"] == "A vs. B"
    assert "event_title" not in picks[1]


def test_write_prompt_grounds_facts_in_input():
    # The WRITE pass must be told about event_title and explicitly barred from
    # adding qualifiers the input doesn't state (gender, round, edition).
    assert "event_title" in digestbot.WRITE_PROMPT
    assert "Women's World Cup" in digestbot.WRITE_PROMPT
    assert "quarterfinal" in digestbot.WRITE_PROMPT


# --- Settled-market exclusion (handoff 3.1) ----------------------------------

def _alert_row(slug, cid, end=None, usd=50000.0, score=5.0):
    return {
        "event_slug": slug, "condition_id": cid, "market_title": f"{slug}?",
        "market_url": f"https://polyspotter.com/event/{slug}", "market_image": None,
        "end_date": end, "event_end_estimate": None, "total_usd": usd,
        "trade_count": 20, "composite_score": score, "llm_copy_action": None,
        "tags": "[]",
    }


class _FakeCursor:
    def __init__(self, rows_by_sql):
        self._rows_by_sql = rows_by_sql
        self._rows = []

    def execute(self, sql, params=None):
        self._rows = self._rows_by_sql.get(sql, [])

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows_by_sql):
        self._rows_by_sql = rows_by_sql

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._rows_by_sql)

    def close(self):
        pass


def test_digest_candidates_drop_settled_markets(monkeypatch):
    from datetime import datetime, timedelta, timezone
    soon = datetime.now(timezone.utc) + timedelta(hours=3)
    later = datetime.now(timezone.utc) + timedelta(days=3)
    rows = {
        digestbot._RESOLVING_TODAY_SQL: [
            _alert_row("today-live", "0xt1", soon),
            _alert_row("today-settled", "0xt2", soon),
        ],
        digestbot._WEEK_UPCOMING_SQL: [
            _alert_row("week-live", "0xw1", later),
            _alert_row("week-settled", "0xw2", later),
        ],
        digestbot._WEEK_HOT_SQL: [],
    }
    statuses = {
        "0xt1": {"closed": False, "uma_status": "", "max_price": 0.55},
        "0xt2": {"closed": False, "uma_status": "proposed", "max_price": 0.99},
        "0xw1": {"closed": False, "uma_status": "", "max_price": 0.40},
        "0xw2": {"closed": True, "uma_status": "", "max_price": 1.0},
    }
    monkeypatch.setattr(digestbot, "_get_conn", lambda: _FakeConn(rows))
    monkeypatch.setattr(digestbot, "fetch_recent_featured_slugs", lambda: set())
    monkeypatch.setattr(digestbot, "_gamma_status_for_markets",
                        lambda cids: {c: statuses[c] for c in cids if c in statuses})

    cands = digestbot.fetch_candidates()
    today = [c["event_slug"] for c in cands["resolving_today"]]
    week = [c["event_slug"] for c in cands["week_pool"]]
    assert today == ["today-live"]
    assert week == ["week-live"]


def test_week_hot_sql_requires_end_date():
    # A NULL end date gives no evidence the market is still open; the week pool
    # must not feature it.
    sql = " ".join(digestbot._WEEK_HOT_SQL.split())
    assert "COALESCE(a.event_end_estimate, a.end_date) IS NOT NULL" in sql
    assert "IS NULL OR" not in sql


# --- PICK output hygiene (handoff 3.1) ---------------------------------------

def _pool(*slugs):
    return [{"event_slug": s, "title": s} for s in slugs]


def _llm(today=(), week=()):
    return {"resolving_today": [{"event_slug": s, "reason": "r"} for s in today],
            "top_this_week": [{"event_slug": s, "reason": "r"} for s in week]}


def test_today_picks_only_from_today_pool():
    today, week = digestbot.normalise_picks(
        _llm(today=["t1", "w1"], week=["w2"]),
        _pool("t1"), _pool("w1", "w2"), cap=digestbot.TODAY_PICKS_MAX)
    assert [p["event_slug"] for p in today] == ["t1"]
    assert [p["event_slug"] for p in week] == ["w2"]


def test_event_not_in_both_sections():
    # Pools can overlap when the LLM echoes a slug twice; the event belongs to
    # Resolving Today only.
    today, week = digestbot.normalise_picks(
        _llm(today=["t1"], week=["t1", "w1"]),
        _pool("t1"), _pool("t1", "w1"), cap=digestbot.TODAY_PICKS_MAX)
    assert [p["event_slug"] for p in today] == ["t1"]
    assert [p["event_slug"] for p in week] == ["w1"]


def test_resolving_today_capped():
    cap = digestbot.TODAY_PICKS_MAX
    slugs = [f"t{i}" for i in range(cap + 3)]
    today, _ = digestbot.normalise_picks(
        _llm(today=list(reversed(slugs)) + [slugs[-1]]), _pool(*slugs), [], cap=cap)
    assert [p["event_slug"] for p in today] == list(reversed(slugs))[:cap]
    assert f"max {cap}" in digestbot.PICK_PROMPT


# --- Idempotent send (handoff 3.1) --------------------------------------------

def _wire_main(monkeypatch, tmp_path, sent_at=None):
    """Fake every external edge of main(); returns the event log."""
    events = []
    monkeypatch.setattr(digestbot, "DRY_RUN", False)
    monkeypatch.setattr(digestbot, "DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(digestbot, "RESEND_API_KEY", "test_key")
    monkeypatch.setattr(digestbot, "DIGESTS_DIR", str(tmp_path))
    monkeypatch.setattr(digestbot, "fetch_digest_sent_at", lambda d: sent_at)
    monkeypatch.setattr(digestbot, "fetch_candidates", lambda: {
        "resolving_today": [dict(_TODAY_PICK)], "week_pool": []})

    def fake_claude_json(prompt, payload):
        events.append("claude")
        if prompt == digestbot.PICK_PROMPT:
            return {"resolving_today": [{"event_slug": "nba-finals"}], "top_this_week": []}
        return _WRITE_OUT

    monkeypatch.setattr(digestbot, "run_claude_json", fake_claude_json)
    monkeypatch.setattr(digestbot, "fetch_event_titles", lambda slugs: {})
    monkeypatch.setattr(digestbot, "persist_digest",
                        lambda d, r, c: events.append(("persist", d)))
    monkeypatch.setattr(digestbot, "fetch_subscribers", lambda: [
        {"email": "a@x.com", "unsubscribe_token": "tok-a"},
        {"email": "b@x.com", "unsubscribe_token": "tok-b"}])
    monkeypatch.setattr(digestbot, "mark_digest_sent",
                        lambda d: events.append(("sent_at", d)))

    class FakeResp:
        status_code = 200
        def json(self):
            return {"id": "email_1"}

    def fake_post(url, json=None, headers=None, timeout=None):
        events.append(("post", json["to"][0], headers.get("Idempotency-Key")))
        return FakeResp()

    monkeypatch.setattr(digestbot.requests, "post", fake_post)
    return events


def test_send_skipped_when_already_sent_today(monkeypatch, tmp_path):
    events = _wire_main(monkeypatch, tmp_path, sent_at="2026-09-26T13:00:05+00:00")
    assert digestbot.main(["--send"]) == 0
    assert not [e for e in events if e[0] in ("post", "persist")]
    assert "claude" not in events   # no paid LLM passes for a digest already out


def test_send_sets_sent_at_and_idempotency_key(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    events = _wire_main(monkeypatch, tmp_path)
    assert digestbot.main(["--send"]) == 0
    posts = [e for e in events if e[0] == "post"]
    assert [p[1] for p in posts] == ["a@x.com", "b@x.com"]
    keys = [p[2] for p in posts]
    # Keyed by day; one key per recipient (Resend rejects a reused key whose
    # payload differs, so a single shared key would drop every recipient but one).
    assert all(k.startswith(f"digest-{today}") for k in keys)
    assert len(set(keys)) == 2
    assert events[-1] == ("sent_at", today)
    assert events.index(("sent_at", today)) > max(events.index(p) for p in posts)


def test_digest_claude_invocation_disables_tools(monkeypatch):
    # The payload carries market titles and LLM text; the write pass must not
    # be able to act on anything injected there.
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(digestbot.subprocess, "run", fake_run)
    digestbot.run_claude("PROMPT", "PAYLOAD")
    argv = captured["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert "--dangerously-skip-permissions" not in argv
