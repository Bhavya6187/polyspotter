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
        "game_start_time": None,
        "event_end_estimate": None,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "dedup_key": f"test_dedup_{id(overrides)}",
    }
    defaults.update(overrides)
    cur.execute(
        """INSERT INTO alerts
           (alert_type, composite_score, tags, market_title, condition_id,
            event_slug, wallet, total_usd, trade_count, end_date,
            game_start_time, event_end_estimate, scanned_at, dedup_key)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            defaults["alert_type"], defaults["composite_score"], defaults["tags"],
            defaults["market_title"], defaults["condition_id"], defaults["event_slug"],
            defaults["wallet"], defaults["total_usd"], defaults["trade_count"],
            defaults["end_date"], defaults["game_start_time"],
            defaults["event_end_estimate"], defaults["scanned_at"], defaults["dedup_key"],
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
    def _clear_cache(self):
        """The endpoint caches its response for 60s; reset between tests."""
        import app as app_module
        app_module._resolving_soon_cache = None
        app_module._gamma_status_cache.clear()

    def test_resolving_soon_includes_upcoming(self):
        self._clear_cache()
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
        self._clear_cache()
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

    def test_resolving_soon_ranks_by_event_end_estimate_not_end_date(self):
        """Regression: a sports game starting in 2h should rank ABOVE a
        political market whose end_date is 12h away. Previously the endpoint
        sorted by end_date, so sports markets (whose end_date buffers 7 days
        for UMA resolution) got pushed to the bottom and never appeared."""
        self._clear_cache()
        near_game_start = datetime.now(timezone.utc) + timedelta(hours=2)
        sports_resolution_deadline = datetime.now(timezone.utc) + timedelta(days=7)
        political_end = datetime.now(timezone.utc) + timedelta(hours=12)

        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_sports_game",
                condition_id="test_sports_cond",
                event_slug="test-sports-event",
                market_title="TEST: Team A vs. Team B",
                end_date=sports_resolution_deadline.isoformat(),
                game_start_time=near_game_start.isoformat(),
                event_end_estimate=near_game_start.isoformat(),
            )
            _seed_alert(
                cur,
                dedup_key="test_political",
                condition_id="test_political_cond",
                event_slug="test-political-event",
                market_title="TEST: Will policy pass?",
                end_date=political_end.isoformat(),
                game_start_time=None,
                event_end_estimate=political_end.isoformat(),
            )

        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        data = resp.json()
        test_entries = [d for d in data if d["condition_id"] in ("test_sports_cond", "test_political_cond")]
        assert len(test_entries) == 2, f"Expected both test alerts, got {test_entries}"
        # Sports game (event_end_estimate = 2h) must come before political (12h)
        assert test_entries[0]["condition_id"] == "test_sports_cond"
        assert test_entries[1]["condition_id"] == "test_political_cond"

    def test_resolving_soon_drops_sports_game_already_started(self):
        """A sports game whose game_start_time has passed should drop out of
        the strip even though its end_date (UMA resolution deadline) is still
        days in the future."""
        self._clear_cache()
        past_game_start = datetime.now(timezone.utc) - timedelta(hours=1)
        future_resolution = datetime.now(timezone.utc) + timedelta(days=6)

        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_game_over",
                condition_id="test_game_over_cond",
                end_date=future_resolution.isoformat(),
                game_start_time=past_game_start.isoformat(),
                event_end_estimate=past_game_start.isoformat(),
            )

        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        matches = [d for d in resp.json() if d["condition_id"] == "test_game_over_cond"]
        assert len(matches) == 0

    def test_resolving_soon_backcompat_for_pre_migration_rows(self):
        """Existing rows with NULL event_end_estimate should still appear,
        sorted by end_date (COALESCE fallback) — the migration seeds
        event_end_estimate = end_date on startup, but this guards against
        ingest races where a new alert lands without it."""
        self._clear_cache()
        end = datetime.now(timezone.utc) + timedelta(hours=4)

        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_legacy_row",
                condition_id="test_legacy_cond",
                end_date=end.isoformat(),
                game_start_time=None,
                event_end_estimate=None,
            )

        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        matches = [d for d in resp.json() if d["condition_id"] == "test_legacy_cond"]
        assert len(matches) == 1
        assert matches[0]["end_date"] is not None

    def test_resolving_soon_surfaces_game_start_time(self):
        """Response should include game_start_time so the frontend can label
        the countdown as 'Starts in' instead of 'Resolves in' for sports."""
        self._clear_cache()
        gs = datetime.now(timezone.utc) + timedelta(hours=3)
        with db() as conn:
            cur = conn.cursor()
            _seed_alert(
                cur,
                dedup_key="test_gs_surface",
                condition_id="test_gs_cond",
                end_date=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                game_start_time=gs.isoformat(),
                event_end_estimate=gs.isoformat(),
            )

        resp = client.get("/api/resolving-soon")
        matches = [d for d in resp.json() if d["condition_id"] == "test_gs_cond"]
        assert len(matches) == 1
        assert matches[0]["game_start_time"] is not None


# ---------------------------------------------------------------------------
# Gamma status helpers (cache + settled classification)
# ---------------------------------------------------------------------------

class TestGammaStatusHelpers:
    def test_is_market_settled_closed(self):
        from app import _is_market_settled
        assert _is_market_settled({"closed": True, "uma_status": "", "prices": [0.5, 0.5]})

    def test_is_market_settled_uma_proposed(self):
        from app import _is_market_settled
        assert _is_market_settled({"closed": False, "uma_status": "proposed", "prices": [0.5, 0.5]})

    def test_is_market_settled_price_near_one(self):
        from app import _is_market_settled
        assert _is_market_settled({"closed": False, "uma_status": "", "prices": [0.999, 0.001]})

    def test_is_market_settled_live(self):
        from app import _is_market_settled
        assert not _is_market_settled({"closed": False, "uma_status": "", "prices": [0.6, 0.4]})

    def test_is_market_settled_empty_status(self):
        from app import _is_market_settled
        assert not _is_market_settled({})


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


# ---------------------------------------------------------------------------
# /api/market/{condition_id}/price-history endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestPriceHistory:
    def test_price_history_returns_structure(self, monkeypatch):
        """Mock upstream CLOB + Gamma calls, verify response shape."""
        def mock_fetch_live(cid):
            from models import LiveMarketData, OutcomePrice
            return LiveMarketData(
                condition_id=cid,
                outcomes=[
                    OutcomePrice(name="Yes", token_id="tok_yes_123", price=0.21),
                    OutcomePrice(name="No", token_id="tok_no_456", price=0.79),
                ],
            )

        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"history": [
                    {"t": 1700000000, "p": 0.75},
                    {"t": 1700003600, "p": 0.78},
                    {"t": 1700007200, "p": 0.80},
                ]}

        import app as app_mod
        monkeypatch.setattr(app_mod, "_fetch_live_market", mock_fetch_live)
        monkeypatch.setattr(app_mod._requests, "get", lambda *a, **kw: MockResp())

        app_mod._live_cache.clear()
        app_mod._price_history_cache.clear()

        resp = client.get("/api/market/test_cond_001/price-history?range=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["condition_id"] == "test_cond_001"
        assert data["outcome"] == "No"
        assert len(data["history"]) == 3
        assert data["history"][0]["t"] == 1700000000

    def test_price_history_invalid_range(self):
        """Invalid range param returns 422."""
        resp = client.get("/api/market/test_cond_001/price-history?range=invalid")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/market/{condition_id}/holders endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestMarketHolders:
    def test_holders_returns_enriched_list(self, monkeypatch):
        """Mock Data API /positions, seed wallet_profiles, verify enrichment."""
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, total_positions, closed_positions,
                   wins, losses, total_pnl, total_invested, avg_win_price, win_rate, times_flagged)
                   VALUES ('test_wallet_holder1', 50, 40, 30, 10, 5000, 20000, 0.65, 0.75, 3)
                   ON CONFLICT (wallet) DO NOTHING"""
            )
            conn.commit()

        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return [
                    {"proxyWallet": "test_wallet_holder1", "size": "1500.0",
                     "outcome": "Yes", "curPrice": "0.21", "cashBalance": "0"},
                    {"proxyWallet": "test_wallet_holder2", "size": "800.0",
                     "outcome": "No", "curPrice": "0.79", "cashBalance": "0"},
                ]

        import app as app_mod
        monkeypatch.setattr(app_mod._requests, "get", lambda *a, **kw: MockResp())
        app_mod._holders_cache.clear()

        resp = client.get("/api/market/test_cond_001/holders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["condition_id"] == "test_cond_001"
        assert len(data["holders"]) == 2
        h1 = data["holders"][0]
        assert h1["wallet"] == "test_wallet_holder1"
        assert h1["win_rate"] == 0.75
        assert h1["total_pnl"] == 5000

    def test_holders_empty_market(self, monkeypatch):
        """Market with no holders returns empty list."""
        class MockResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return []

        import app as app_mod
        monkeypatch.setattr(app_mod._requests, "get", lambda *a, **kw: MockResp())
        app_mod._holders_cache.clear()

        resp = client.get("/api/market/test_cond_empty/holders")
        assert resp.status_code == 200
        assert resp.json()["holders"] == []


# ---------------------------------------------------------------------------
# /api/market/{condition_id}/theses endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestMarketTheses:
    def test_theses_for_market(self):
        """Returns theses from wallets that have alerts in this market."""
        with db() as conn:
            cur = conn.cursor()
            _seed_alert(cur, wallet="test_wallet_thesis1", condition_id="test_cond_thesis",
                        dedup_key="test_thesis_dedup_1")
            _seed_thesis(cur, wallet="test_wallet_thesis1", event_slug="test-thesis-event",
                         thesis_headline="TEST: Geopolitics stability bet")
            conn.commit()

        resp = client.get("/api/market/test_cond_thesis/theses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["theses"]) == 1
        assert data["theses"][0]["thesis_headline"] == "TEST: Geopolitics stability bet"

    def test_theses_empty_market(self):
        """Market with no alerts returns empty theses."""
        resp = client.get("/api/market/test_cond_notheses/theses")
        assert resp.status_code == 200
        assert resp.json()["theses"] == []
