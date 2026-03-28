"""
Tests for story-driven homepage endpoints.

Uses FastAPI TestClient. Requires DATABASE_URL to be set (can point to a test DB).
Run: cd backend && pytest test_endpoints.py -v
"""

import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

from fastapi.testclient import TestClient


# Set a dummy DATABASE_URL if not present (tests that hit DB will be skipped)
_has_db = bool(os.environ.get("DATABASE_URL"))

if not _has_db:
    os.environ["DATABASE_URL"] = "postgresql://localhost/polybot_test"


try:
    from app import app, db
    from database import init_db
    _import_ok = True
except Exception:
    _import_ok = False

client = TestClient(app) if _import_ok else None

skip_no_db = pytest.mark.skipif(not _has_db, reason="DATABASE_URL not set")


def _clean_test_data(conn):
    """Remove test data created during tests."""
    cur = conn.cursor()
    cur.execute("DELETE FROM alert_signals WHERE alert_id IN (SELECT id FROM alerts WHERE market_title LIKE 'TEST:%%')")
    cur.execute("DELETE FROM alert_trades WHERE alert_id IN (SELECT id FROM alerts WHERE market_title LIKE 'TEST:%%')")
    cur.execute("DELETE FROM alerts WHERE market_title LIKE 'TEST:%%'")
    cur.execute("DELETE FROM wallet_theses WHERE thesis_headline LIKE 'TEST:%%'")
    cur.execute("DELETE FROM wallet_profiles WHERE wallet LIKE 'test_%%'")
    cur.execute("DELETE FROM price_candles WHERE condition_id LIKE 'test_%%'")
    conn.commit()


@pytest.fixture(autouse=True)
def clean_db():
    """Clean test data before and after each test."""
    if not _has_db or not _import_ok:
        yield
        return
    with db() as conn:
        _clean_test_data(conn)
    yield
    with db() as conn:
        _clean_test_data(conn)


def _seed_alert(cur, **overrides):
    """Insert a test alert and return its ID."""
    defaults = {
        "alert_type": "composite",
        "composite_score": 10.0,
        "tags": "[]",
        "market_title": "TEST: Will X happen?",
        "condition_id": "test_cond_001",
        "event_slug": "test-event",
        "wallet": "test_wallet_001",
        "total_usd": 5000.0,
        "trade_count": 1,
        "end_date": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "dedup_key": f"test_dedup_{id(overrides)}",
    }
    defaults.update(overrides)
    cur.execute(
        """INSERT INTO alerts
           (alert_type, composite_score, tags, market_title, condition_id,
            event_slug, wallet, total_usd, trade_count, end_date, scanned_at, dedup_key)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            defaults["alert_type"], defaults["composite_score"], defaults["tags"],
            defaults["market_title"], defaults["condition_id"], defaults["event_slug"],
            defaults["wallet"], defaults["total_usd"], defaults["trade_count"],
            defaults["end_date"], defaults["scanned_at"], defaults["dedup_key"],
        ),
    )
    return cur.fetchone()["id"]


def _seed_thesis(cur, **overrides):
    """Insert a test thesis and return its ID."""
    defaults = {
        "wallet": "test_wallet_001",
        "event_slug": "test-event",
        "thesis_headline": "TEST: Markets will rally",
        "markets": json.dumps([{"condition_id": "test_cond_001", "market_title": "Test Market", "outcome": "Yes", "side": "BUY", "usd_value": 1000, "entry_price": 0.6}]),
        "total_usd": 1000.0,
        "composite_score": 8.0,
    }
    defaults.update(overrides)
    cur.execute(
        """INSERT INTO wallet_theses (wallet, event_slug, thesis_headline, markets, total_usd, composite_score, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, NOW())
           RETURNING id""",
        (defaults["wallet"], defaults["event_slug"], defaults["thesis_headline"],
         defaults["markets"], defaults["total_usd"], defaults["composite_score"]),
    )
    return cur.fetchone()["id"]


# ---------------------------------------------------------------------------
# /api/theses/{id} endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestGetThesis:
    def test_get_thesis_returns_200(self):
        with db() as conn:
            cur = conn.cursor()
            thesis_id = _seed_thesis(cur)

        resp = client.get(f"/api/theses/{thesis_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == thesis_id
        assert data["thesis_headline"] == "TEST: Markets will rally"
        assert data["wallet"] == "test_wallet_001"
        assert isinstance(data["markets"], list)
        assert len(data["markets"]) == 1

    def test_get_thesis_404(self):
        resp = client.get("/api/theses/999999")
        assert resp.status_code == 404

    def test_get_thesis_joins_wallet_profile(self):
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, win_rate, total_pnl, total_invested, updated_at)
                   VALUES ('test_wallet_001', 0.72, 5000.0, 10000.0, NOW())
                   ON CONFLICT (wallet) DO UPDATE SET win_rate = 0.72, total_pnl = 5000.0""",
            )
            thesis_id = _seed_thesis(cur)

        resp = client.get(f"/api/theses/{thesis_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["win_rate"] == 0.72
        assert data["total_pnl"] == 5000.0


# ---------------------------------------------------------------------------
# /api/spotlight endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestSpotlight:
    def test_spotlight_returns_list(self):
        with db() as conn:
            cur = conn.cursor()
            _seed_alert(cur, dedup_key="test_spot_1")

        resp = client.get("/api/spotlight")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_spotlight_max_3(self):
        with db() as conn:
            cur = conn.cursor()
            for i in range(5):
                _seed_alert(cur, dedup_key=f"test_spot_{i}", composite_score=10 + i)

        resp = client.get("/api/spotlight")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3


# ---------------------------------------------------------------------------
# /api/resolving-soon endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestResolvingSoon:
    def test_resolving_soon_includes_upcoming(self):
        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_resolving_soon_1",
                end_date=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            )

        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_resolving_soon_excludes_far_future(self):
        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_resolving_far",
                end_date=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                condition_id="test_far_cond",
            )

        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        data = resp.json()
        far_ids = [d for d in data if d.get("condition_id") == "test_far_cond"]
        assert len(far_ids) == 0


# ---------------------------------------------------------------------------
# /api/wallets/{address} endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestWalletProfile:
    def test_wallet_profile_returns_recent_alerts(self):
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, win_rate, total_pnl, updated_at)
                   VALUES ('test_wallet_profile', 0.65, 3000.0, NOW())
                   ON CONFLICT (wallet) DO UPDATE SET win_rate = 0.65""",
            )
            _seed_alert(cur, wallet="test_wallet_profile", dedup_key="test_wp_alert")

        resp = client.get("/api/wallets/test_wallet_profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["wallet"] == "test_wallet_profile"
        assert data["win_rate"] == 0.65
        assert "recent_alerts" in data
        assert len(data["recent_alerts"]) >= 1

    def test_wallet_profile_404(self):
        resp = client.get("/api/wallets/nonexistent_wallet_xyz")
        assert resp.status_code == 404
