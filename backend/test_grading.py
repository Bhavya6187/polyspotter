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
