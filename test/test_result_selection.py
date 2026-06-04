"""Tests for curated result selection in storybot/result_pipeline.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_pipeline as rp  # noqa: E402


def test_classify_outcome_cashed_burned_wash():
    assert rp.classify_outcome({"net_pl_usd": 5000.0,
                                "total_invested_usd": 10000.0}) == "cashed"
    assert rp.classify_outcome({"net_pl_usd": -8000.0,
                                "total_invested_usd": 10000.0}) == "burned"
    # within 1% of invested -> wash
    assert rp.classify_outcome({"net_pl_usd": 50.0,
                                "total_invested_usd": 10000.0}) == "wash"


def test_notable_loss_always_selected_even_with_wins():
    # Honesty floor: a $40k loss is posted even alongside a winning call.
    cands = [
        {"id": "w", "is_win": True, "net_pl_usd": 12000.0, "notability": 12000.0},
        {"id": "L", "is_win": False, "net_pl_usd": -40000.0, "notability": 40000.0},
    ]
    picked = {c["id"] for c in rp.select_results(cands, posted_today=[])}
    assert "L" in picked  # big loss not hidden
    assert len(picked) == 2  # both fit under cap=2


def test_small_loss_suppressed_when_a_win_is_available():
    cands = [
        {"id": "w", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
        {"id": "s", "is_win": False, "net_pl_usd": -3000.0, "notability": 3000.0},
    ]
    picked = [c["id"] for c in rp.select_results(
        cands, posted_today=[], daily_cap=1)]
    assert picked == ["w"]  # win preferred; small loss below honesty floor


def test_daily_cap_and_remaining_slots_respected():
    cands = [
        {"id": "a", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
        {"id": "b", "is_win": True, "net_pl_usd": 8000.0, "notability": 8000.0},
    ]
    # one already posted today -> only one slot left
    picked = rp.select_results(cands, posted_today=[True], daily_cap=2)
    assert len(picked) == 1
    assert picked[0]["id"] == "a"  # higher notability first


def test_win_bias_forces_win_when_share_below_target():
    # No wins posted yet, share would start below target -> prefer the win
    # over an equally-notable big loss for the first slot.
    cands = [
        {"id": "L", "is_win": False, "net_pl_usd": -50000.0, "notability": 50000.0},
        {"id": "w", "is_win": True, "net_pl_usd": 9000.0, "notability": 9000.0},
    ]
    picked = [c["id"] for c in rp.select_results(
        cands, posted_today=[], daily_cap=1, win_bias=0.8)]
    assert picked == ["w"]
