"""
/api/wallets/{address}: don't 404 real wallets, and don't show share counts
as dollars.

* The endpoint returned 404 whenever the live Data API call for closed
  positions came back empty -- on a timeout / 5xx / rate limit, and for any
  wallet with open positions only (exactly the wallets new_wallet_large_bet
  flags). The frontend then rendered notFound() for a wallet we link to.
* Data API `totalBought` is a share count, not USD. Stake is avgPrice *
  totalBought, and an early exit price is avgPrice + realizedPnl/totalBought.
"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app, _positions_to_bets, _compute_wallet_stats

client = TestClient(app)


class _Cursor:
    def __init__(self, profile_row, alert_rows):
        self._profile_row = profile_row
        self._alert_rows = alert_rows
        self._last = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT total_positions"):
            self._last = self._profile_row
        elif s.startswith("SELECT a.id, a.market_title"):
            self._last = self._alert_rows
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def fetchall(self):
        return self._last or []


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _fake_db(profile_row, alert_rows):
    @contextmanager
    def fake():
        yield _Conn(_Cursor(profile_row, alert_rows))
    return fake


PROFILE = {"total_positions": 12, "closed_positions": 10, "wins": 7, "losses": 3,
           "total_pnl": 1200.0, "total_invested": 5000.0, "avg_win_price": 0.55,
           "win_rate": 0.7, "times_flagged": 2}


def test_known_wallet_with_no_live_positions_returns_profile(monkeypatch):
    monkeypatch.setattr(app_module, "_fetch_closed_positions", lambda w: [])
    monkeypatch.setattr(app_module, "db", _fake_db(PROFILE, []))

    resp = client.get("/api/wallets/0xABC")

    assert resp.status_code == 200
    body = resp.json()
    assert body["wallet"] == "0xabc"
    assert body["wins"] == 7
    assert body["bet_history"] == []


def test_unknown_wallet_with_no_positions_is_404(monkeypatch):
    monkeypatch.setattr(app_module, "_fetch_closed_positions", lambda w: [])
    monkeypatch.setattr(app_module, "db", _fake_db(None, []))

    resp = client.get("/api/wallets/0xnobody")

    assert resp.status_code == 404


def test_positions_to_bets_uses_dollar_stake_not_share_count():
    bets = _positions_to_bets([{
        "title": "m", "conditionId": "0xc", "outcome": "Yes",
        "avgPrice": 0.2182, "totalBought": 7550, "realizedPnl": 5901.87, "curPrice": 1.0,
    }])
    assert bets[0].total_usd == pytest.approx(0.2182 * 7550, rel=1e-6)
    assert bets[0].resolution_price == 1.0
    assert bets[0].won is True


def test_positions_to_bets_exit_price_from_realized_pnl():
    # bought 100 shares at 0.40, sold at 0.60 -> pnl 20
    bets = _positions_to_bets([{
        "title": "m", "conditionId": "0xc", "outcome": "Yes",
        "avgPrice": 0.40, "totalBought": 100, "realizedPnl": 20.0, "curPrice": 0.55,
    }])
    assert bets[0].resolution_price == pytest.approx(0.60)
    assert bets[0].won is None


def test_compute_wallet_stats_total_invested_in_dollars():
    stats = _compute_wallet_stats([
        {"avgPrice": 0.5, "totalBought": 100, "realizedPnl": 50, "curPrice": 1.0},
        {"avgPrice": 0.25, "totalBought": 200, "realizedPnl": -50, "curPrice": 0.0},
    ])
    assert stats["total_invested"] == pytest.approx(0.5 * 100 + 0.25 * 200)
    assert stats["wins"] == 1 and stats["losses"] == 1
