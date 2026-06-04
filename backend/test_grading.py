from grading import winning_outcome, is_won, copy_return, pick_call


def test_winning_outcome_resolved():
    assert winning_outcome(["Yes", "No"], [0.99, 0.01]) == "Yes"
    assert winning_outcome(["A", "B"], [0.005, 0.995]) == "B"


def test_winning_outcome_unresolved_returns_none():
    assert winning_outcome(["Yes", "No"], [0.6, 0.4]) is None   # not decided
    assert winning_outcome(["Yes", "No"], [0.5, 0.5]) is None   # 50-50 excluded


def test_winning_outcome_bad_shapes_return_none():
    assert winning_outcome([], []) is None
    assert winning_outcome(["Yes"], [0.99, 0.01]) is None       # length mismatch


def test_winning_outcome_multiple_above_threshold_returns_none():
    # If two outcomes are both >= threshold (shouldn't happen on a real binary
    # market, but guard anyway), the market isn't cleanly decided -> None.
    assert winning_outcome(["A", "B"], [0.99, 0.99]) is None


def test_is_won_case_insensitive():
    assert is_won("San Diego Padres", "san diego padres ") is True
    assert is_won("Padres", "Phillies") is False


def test_copy_return_win_and_loss():
    assert copy_return(0.5, won=True) == 1.0          # 50c -> $1.00 = +100%
    assert round(copy_return(0.38, won=True), 4) == round((1 - 0.38) / 0.38, 4)
    assert copy_return(0.38, won=False) == -1.0


def test_pick_call_takes_highest_score():
    alerts = [
        {"id": 1, "composite_score": 5.0},
        {"id": 2, "composite_score": 14.0},
        {"id": 3, "composite_score": 9.0},
    ]
    assert pick_call(alerts)["id"] == 2


from datetime import datetime, timedelta, timezone
from grading import summarize


def _row(won, return_pct, days_ago):
    return {
        "won": won,
        "return_pct": return_pct,
        "resolved_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


def test_summarize_window_and_alltime():
    rows = [
        _row(True, 1.0, 1),    # in window
        _row(True, 0.5, 5),    # in window
        _row(False, -1.0, 10), # in window
        _row(True, 2.0, 45),   # outside 30d window, in all-time
    ]
    out = summarize(rows, window_days=30)
    # window: 2 wins / 1 loss
    assert out["window"]["wins"] == 2
    assert out["window"]["losses"] == 1
    assert round(out["window"]["hit_rate"], 3) == round(2 / 3, 3)
    # mean return over window rows = (1.0 + 0.5 - 1.0) / 3
    assert round(out["window"]["copy_return_pct"], 4) == round(0.5 / 3, 4)
    # all-time includes the 45-day-old win
    assert out["all_time"]["wins"] == 3
    assert out["all_time"]["losses"] == 1


def test_summarize_empty():
    out = summarize([], window_days=30)
    assert out["window"]["wins"] == 0
    assert out["window"]["losses"] == 0
    assert out["window"]["hit_rate"] == 0.0
    assert out["window"]["copy_return_pct"] == 0.0


from grade_worker import grade_once


class _FakeCursor:
    def __init__(self, candidate_rows, alert_rows_by_cid):
        self._candidate_rows = candidate_rows
        self._alert_rows_by_cid = alert_rows_by_cid
        self.upserts = []
        self._last = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT DISTINCT a.condition_id"):
            self._last = self._candidate_rows
        elif s.startswith("SELECT id, composite_score"):
            self._last = self._alert_rows_by_cid[params[0]]
        elif s.startswith("INSERT INTO graded_calls"):
            self.upserts.append(params)
            self._last = []

    def fetchall(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def test_grade_once_grades_a_won_call():
    cid = "0xabc"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 10, "composite_score": 14.0, "event_slug": "mlb-x",
             "market_title": "Padres vs Phillies",
             "llm_copy_action": '{"outcome": "San Diego Padres", "entry_price": 0.38}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["San Diego Padres", "Philadelphia Phillies"],
                "prices": [0.99, 0.01]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    params = cur.upserts[0]
    # params order: cid, alert_id, event_slug, title, outcome, entry, resolved, won, ret, score
    assert params[0] == cid
    assert params[1] == 10
    assert params[6] == "San Diego Padres"  # resolved_outcome
    assert params[7] is True                # won
    assert round(params[8], 4) == round((1 - 0.38) / 0.38, 4)


def test_grade_once_skips_unresolved():
    cid = "0xopen"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 5.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": '{"outcome": "Yes", "entry_price": 0.5}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["Yes", "No"], "prices": [0.6, 0.4]}  # not decided

    graded = grade_once(conn, fake_fetch)
    assert graded == 0
    assert cur.upserts == []


def test_grade_once_grades_a_lost_call():
    cid = "0xlost"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 7, "composite_score": 14.0, "event_slug": "mlb-y",
             "market_title": "Padres vs Phillies",
             "llm_copy_action": '{"outcome": "San Diego Padres", "entry_price": 0.38}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        # Phillies win -> the Padres call loses
        return {"outcomes": ["San Diego Padres", "Philadelphia Phillies"],
                "prices": [0.01, 0.99]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    params = cur.upserts[0]
    assert params[7] is False        # won
    assert params[8] == -1.0         # return_pct


def test_grade_once_skips_entry_price_zero():
    cid = "0xzero"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 5.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": '{"outcome": "Yes", "entry_price": 0}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["Yes", "No"], "prices": [0.99, 0.01]}  # resolved

    graded = grade_once(conn, fake_fetch)
    assert graded == 0
    assert cur.upserts == []


def test_grade_once_skips_bad_copy_action_json():
    cid = "0xbadjson"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 5.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": "not json"},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["Yes", "No"], "prices": [0.99, 0.01]}  # resolved

    graded = grade_once(conn, fake_fetch)
    assert graded == 0
    assert cur.upserts == []


def test_grade_once_dedup_picks_highest_score():
    cid = "0xdedup"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 5.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": '{"outcome": "No", "entry_price": 0.40}'},
            {"id": 2, "composite_score": 14.0, "event_slug": "e", "market_title": "m",
             "llm_copy_action": '{"outcome": "Yes", "entry_price": 0.38}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        # "Yes" wins -> alert 2's call (the higher-score one) is correct
        return {"outcomes": ["Yes", "No"], "prices": [0.99, 0.01]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    params = cur.upserts[0]
    assert params[1] == 2            # alert_id of the higher-score call


def test_grade_once_one_poison_market_does_not_abort_batch():
    good = "0xgood"
    poison = "0xpoison"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": poison}, {"condition_id": good}],
        alert_rows_by_cid={
            poison: [
                {"id": 1, "composite_score": 14.0, "event_slug": "e", "market_title": "m",
                 "llm_copy_action": '{"outcome": "Yes", "entry_price": 0.38}'},
            ],
            good: [
                {"id": 2, "composite_score": 14.0, "event_slug": "e", "market_title": "m",
                 "llm_copy_action": '{"outcome": "Yes", "entry_price": 0.38}'},
            ],
        },
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        if condition_id == poison:
            raise ValueError("boom")
        return {"outcomes": ["Yes", "No"], "prices": [0.99, 0.01]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    assert len(cur.upserts) == 1
    assert cur.upserts[0][1] == 2   # only the good market's call graded


from datetime import datetime as _dt, timezone as _tz

FIXED_T = _dt(2026, 6, 5, 0, 10, tzinfo=_tz.utc)


def test_grade_once_resolved_at_uses_event_end_estimate():
    cid = "0xtime"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 10, "composite_score": 14.0, "event_slug": "mlb-x",
             "market_title": "Padres vs Phillies", "event_end_estimate": FIXED_T,
             "llm_copy_action": '{"outcome": "San Diego Padres", "entry_price": 0.38}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["San Diego Padres", "Philadelphia Phillies"],
                "prices": [0.99, 0.01]}

    graded = grade_once(conn, fake_fetch)
    assert graded == 1
    assert cur.upserts[0][10] == FIXED_T   # resolved_at = real event time


def test_grade_once_skips_mislabeled_outcome():
    cid = "0xmislabel"
    cur = _FakeCursor(
        candidate_rows=[{"condition_id": cid}],
        alert_rows_by_cid={cid: [
            {"id": 1, "composite_score": 14.0, "event_slug": "nba-z",
             "market_title": "Jazz vs Nuggets",
             "llm_copy_action": '{"outcome": "Utah Jazz", "entry_price": 0.5}'},
        ]},
    )
    conn = _FakeConn(cur)

    def fake_fetch(condition_id):
        return {"outcomes": ["Utah", "Denver"], "prices": [0.99, 0.01]}  # resolves "Utah"

    graded = grade_once(conn, fake_fetch)
    assert graded == 0
    assert cur.upserts == []
