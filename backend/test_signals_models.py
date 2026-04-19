from datetime import datetime, timezone
from models import SignalView, SignalMarket, SignalWallet, PaginatedSignals

def test_signal_view_validates_minimal():
    s = SignalView(
        id="1",
        created_at=datetime.now(timezone.utc),
        market=SignalMarket(title="x", topic="Politics", icon="⚖️"),
        wallet=SignalWallet(addr="0xabc", alias="WOLF", tier="sharp", color="#00c26a"),
        stake_usd=10_000,
        score=15.0,
        rating=4,
        why="test",
        signals=["win_rate"],
        bullets=["a","b","c"],
    )
    assert s.rating == 4
    assert s.wallet.alias == "WOLF"
    assert s.market.icon == "⚖️"

def test_paginated_signals():
    p = PaginatedSignals(signals=[], total=0)
    assert p.total == 0
