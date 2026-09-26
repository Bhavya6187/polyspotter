"""
The console summary must rank alerts by compute_composite_score (what the
seeder and the gate use), not by the raw severity sum it used to show.
"""

from detection_strategies import Signal, compute_composite_score
from polybot import _format_summary


def _trade(tx, wallet, cid, title, usd=5000):
    return {
        "transactionHash": tx, "proxyWallet": wallet, "conditionId": cid,
        "eventSlug": f"evt-{cid}", "title": title, "_usd_value": usd,
    }


def _individual_lines(summary):
    lines = summary.splitlines()
    start = lines.index("  Top individual alerts:") + 1
    return [line for line in lines[start:] if line.startswith("    [")]


def test_format_summary_ranks_by_composite_score():
    stacked = _trade("0xtx_a", "0xwallet_a", "cond_a", "Stacked correlated")
    strong = _trade("0xtx_b", "0xwallet_b", "cond_b", "Single strong price impact")
    # Raw sum 9.0 but composite 3.0: one strategy firing three times can't stack.
    stacked_sigs = [
        Signal("correlated_cross_market", 3.0, f"thesis {i}", stacked) for i in range(3)
    ]
    # Raw sum 5.0, composite 6.5 (price_impact weight 1.3).
    strong_sigs = [Signal("price_impact", 5.0, "moved price", strong)]
    assert sum(s.severity for s in stacked_sigs) > sum(s.severity for s in strong_sigs)
    assert compute_composite_score(strong_sigs) > compute_composite_score(stacked_sigs)

    summary = _format_summary([stacked, strong], stacked_sigs + strong_sigs, "test")

    lines = _individual_lines(summary)
    assert len(lines) == 2
    assert "Single strong price impact" in lines[0]
    assert lines[0].startswith("    [6.5]")
    assert lines[1].startswith("    [3.0]")
