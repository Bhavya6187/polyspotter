"""Trust-critical tests for the result pipeline.

Covers two contracts the accountability layer depends on:

1. The P&L math (`_compute_trade_pl`, `aggregate_result`) that decides what
   the scorecard and the result tweet claim we won/lost.
2. The result-tweet/validator contract: `publish_result.py` re-runs
   `validate_tweet`, whose closer rule rejects single-sentence tweets. The
   result compose prompt therefore MUST force exactly two sentences — these
   tests pin down why.

These are characterization tests against the existing code; bare imports only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))

import result_pipeline as rp
import twitter_pipeline as tp


# --- _compute_trade_pl -------------------------------------------------------

def test_compute_trade_pl_winning_buy_returns_size_minus_usd():
    # A winning BUY pays $1/share at resolution: P&L = size - usd_value.
    trade = {"side": "BUY", "size": 1000.0, "usd_value": 600.0}
    assert rp._compute_trade_pl(trade, True) == 400.0


def test_compute_trade_pl_losing_buy_returns_negative_usd():
    # A losing BUY pays $0: P&L = -usd_value (the whole stake is gone).
    trade = {"side": "BUY", "size": 1000.0, "usd_value": 600.0}
    assert rp._compute_trade_pl(trade, False) == -600.0


def test_compute_trade_pl_non_buy_returns_zero():
    # SELL (any non-BUY) is treated as zero P&L — we only claim BUY-side flow.
    trade = {"side": "SELL", "size": 1000.0, "usd_value": 600.0}
    assert rp._compute_trade_pl(trade, True) == 0.0
    assert rp._compute_trade_pl(trade, False) == 0.0


# --- aggregate_result --------------------------------------------------------

def test_aggregate_result_one_win_one_loss():
    """Two BUY trades on one resolved market: one on the winning outcome,
    one on the losing outcome. Verifies n_won/n_lost/net_pl_usd.

    resolutions is {condition_id: {winning_outcome: ...}} — built directly so
    the test never touches the network or DB.
    """
    cid = "0xabc"
    resolutions = {cid: {"winning_outcome": "Over"}}
    trades = [
        # winner: bought Over for $600, 1000 shares -> +400
        {"alert_id": 1, "wallet": "0xw1", "condition_id": cid,
         "outcome": "Over", "side": "BUY", "usd_value": 600.0, "size": 1000.0},
        # loser: bought Under for $500, 800 shares -> -500
        {"alert_id": 2, "wallet": "0xw2", "condition_id": cid,
         "outcome": "Under", "side": "BUY", "usd_value": 500.0, "size": 800.0},
    ]

    agg = rp.aggregate_result(trades, resolutions)

    assert agg["n_trades"] == 2
    assert agg["n_won"] == 1
    assert agg["n_lost"] == 1
    # net = total_payout (1000 winner shares) - total_invested (600 + 500)
    #     = 1000 - 1100 = -100
    assert agg["net_pl_usd"] == -100.0
    assert agg["total_invested_usd"] == 1100.0
    assert agg["total_payout_usd"] == 1000.0


# --- validator contract ------------------------------------------------------

def test_two_sentence_result_tweet_passes_validate_tweet():
    """A realistic TWO-sentence result tweet must pass validate_tweet — this
    is the shape the compose prompt is required to produce."""
    text = ("Phillies took it, and the cluster that bought the Over cashed. "
            "Net +$31k across the two markets.")
    ok, err = tp.validate_tweet(text)
    assert ok is True, err


def test_one_sentence_result_tweet_fails_validate_tweet():
    """A ONE-sentence result tweet is rejected by validate_tweet's closer
    rule — documents exactly why SYSTEM_PROMPT_RESULT must force two
    sentences (a 1-sentence result would be silently rejected at publish)."""
    text = "The Over cashed +$31k."
    ok, _err = tp.validate_tweet(text)
    assert ok is False
