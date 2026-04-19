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
        "llm_summary": None,
        "llm_copy_action": "{}",
    }
    defaults.update(overrides)
    cur.execute(
        """INSERT INTO alerts
           (alert_type, composite_score, tags, market_title, condition_id,
            event_slug, wallet, total_usd, trade_count, end_date,
            game_start_time, event_end_estimate, scanned_at, dedup_key,
            llm_summary, llm_copy_action)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            defaults["alert_type"], defaults["composite_score"], defaults["tags"],
            defaults["market_title"], defaults["condition_id"], defaults["event_slug"],
            defaults["wallet"], defaults["total_usd"], defaults["trade_count"],
            defaults["end_date"], defaults["game_start_time"],
            defaults["event_end_estimate"], defaults["scanned_at"], defaults["dedup_key"],
            defaults["llm_summary"], defaults["llm_copy_action"],
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


# ---------------------------------------------------------------------------
# /api/top3 endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestTopThree:
    def test_top3_empty_when_no_alerts(self):
        resp = client.get("/api/top3")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_top3_happy_path_three_categories(self):
        """Seed one alert qualifying for each category; expect one per bucket."""
        now = datetime.now(timezone.utc)
        with db() as conn:
            cur = conn.cursor()

            # Sharp wallet profile (HIGHEST_CONVICTION qualifier)
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, win_rate, total_pnl, total_invested, updated_at)
                   VALUES ('test_sharp', 0.92, 482000.0, 520000.0, NOW())
                   ON CONFLICT (wallet) DO UPDATE SET win_rate = 0.92,
                     total_pnl = 482000.0, total_invested = 520000.0""",
            )

            # Conviction alert: sharp wallet, 48h to resolve
            conviction_id = _seed_alert(
                cur, dedup_key="test_top3_conv",
                market_title="TEST: Conviction",
                condition_id="test_top3_cond_a",
                wallet="test_sharp",
                composite_score=80.0,
                total_usd=48000.0,
                tags='["Geopolitics"]',
                end_date=(now + timedelta(hours=48)).isoformat(),
                llm_summary="Sharp wallet loaded up",
                llm_copy_action=json.dumps({"outcome": "YES", "entry_price": 0.18}),
            )

            # Coordinated alert: two trades from two wallets (coordinated flow)
            coord_id = _seed_alert(
                cur, dedup_key="test_top3_coord",
                market_title="TEST: Coordinated",
                condition_id="test_top3_cond_b",
                wallet="test_coord_lead",
                composite_score=60.0,
                total_usd=112000.0,
                end_date=(now + timedelta(days=11)).isoformat(),
                llm_summary="Linked wallets piled on",
                llm_copy_action=json.dumps({"outcome": "YES", "entry_price": 0.41}),
            )
            cur.execute(
                """INSERT INTO alert_signals (alert_id, strategy, severity, headline)
                   VALUES (%s, 'wallet_clustering', 5.0, 'Linked wallets')""",
                (coord_id,),
            )

            # Timing alert: resolves in 30 minutes
            timing_id = _seed_alert(
                cur, dedup_key="test_top3_timing",
                market_title="TEST: Timing",
                condition_id="test_top3_cond_c",
                wallet="test_timing_wallet",
                composite_score=40.0,
                total_usd=22000.0,
                end_date=(now + timedelta(minutes=30)).isoformat(),
                llm_summary="Wallet loaded 47m before tipoff",
                llm_copy_action=json.dumps({"outcome": "YES", "entry_price": 0.55}),
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data) == 3
        categories = [row["category"] for row in data]
        assert categories == ["HIGHEST_CONVICTION", "COORDINATED_FLOW", "TIMING_EDGE"]
        ranks = [row["rank"] for row in data]
        assert ranks == [1, 2, 3]

        by_cat = {row["category"]: row for row in data}
        assert by_cat["HIGHEST_CONVICTION"]["id"] == conviction_id
        assert by_cat["COORDINATED_FLOW"]["id"] == coord_id
        assert by_cat["TIMING_EDGE"]["id"] == timing_id

        # Shape sanity
        conv = by_cat["HIGHEST_CONVICTION"]
        assert conv["market_title"] == "TEST: Conviction"
        assert conv["primary_tag"] == "Geopolitics"
        assert conv["llm_copy_action"]["outcome"] == "YES"
        assert conv["wallet"]["address"] == "test_sharp"
        assert conv["wallet"]["win_rate"] == 0.92
        assert conv["wallet"]["total_invested"] == 520000.0

    def test_top3_fills_empty_buckets_with_top_scorers(self):
        """Only one alert qualifies (coordinated); remaining two slots fill by score."""
        now = datetime.now(timezone.utc)
        with db() as conn:
            cur = conn.cursor()

            # Single coordinated alert (2 wallets)
            coord_id = _seed_alert(
                cur, dedup_key="test_top3_only_coord",
                market_title="TEST: OnlyCoord",
                condition_id="test_top3_cond_only_coord",
                composite_score=40.0,
                end_date=(now + timedelta(days=5)).isoformat(),
            )
            cur.execute(
                """INSERT INTO alert_signals (alert_id, strategy, severity, headline)
                   VALUES (%s, 'wallet_clustering', 5.0, 'Linked')""",
                (coord_id,),
            )

            # Two non-qualifying filler alerts (no sharp wallet, >6h to resolve, no cluster signal)
            filler_a = _seed_alert(
                cur, dedup_key="test_top3_fill_a",
                market_title="TEST: FillA",
                condition_id="test_top3_cond_fill_a",
                composite_score=30.0,
                end_date=(now + timedelta(days=2)).isoformat(),
            )
            filler_b = _seed_alert(
                cur, dedup_key="test_top3_fill_b",
                market_title="TEST: FillB",
                condition_id="test_top3_cond_fill_b",
                composite_score=20.0,
                end_date=(now + timedelta(days=2)).isoformat(),
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data) == 3
        # Fixed display order regardless of selection
        assert [row["category"] for row in data] == [
            "HIGHEST_CONVICTION", "COORDINATED_FLOW", "TIMING_EDGE"
        ]

        # Coordinated slot is the qualifying alert
        by_cat = {row["category"]: row for row in data}
        assert by_cat["COORDINATED_FLOW"]["id"] == coord_id

        # Other two slots are the fillers (higher score first)
        assert by_cat["HIGHEST_CONVICTION"]["id"] == filler_a
        assert by_cat["TIMING_EDGE"]["id"] == filler_b

    def test_top3_excludes_settled_markets(self):
        """Alert with latest price <= 0.03 is excluded."""
        now = datetime.now(timezone.utc)
        with db() as conn:
            cur = conn.cursor()
            settled_id = _seed_alert(
                cur, dedup_key="test_top3_settled",
                market_title="TEST: Settled",
                condition_id="test_top3_cond_settled",
                composite_score=99.0,
                end_date=(now + timedelta(days=1)).isoformat(),
            )
            # Insert a settled candle
            cur.execute(
                """INSERT INTO price_candles (condition_id, token_id, outcome, t, p)
                   VALUES ('test_top3_cond_settled', 'test_top3_token_settled',
                           'Yes', EXTRACT(EPOCH FROM NOW()), 0.02)""",
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        assert all(row["id"] != settled_id for row in resp.json())

    def test_top3_strength_banding(self):
        """Strength is min(4, floor(composite_score/25) + 1)."""
        now = datetime.now(timezone.utc)
        with db() as conn:
            cur = conn.cursor()
            low = _seed_alert(cur, dedup_key="test_top3_s_low",
                              market_title="TEST: Slow",
                              condition_id="test_top3_cond_s_low",
                              composite_score=10.0,
                              end_date=(now + timedelta(days=2)).isoformat())
            mid = _seed_alert(cur, dedup_key="test_top3_s_mid",
                              market_title="TEST: Smid",
                              condition_id="test_top3_cond_s_mid",
                              composite_score=50.0,
                              end_date=(now + timedelta(days=2)).isoformat())
            high = _seed_alert(cur, dedup_key="test_top3_s_high",
                               market_title="TEST: Shigh",
                               condition_id="test_top3_cond_s_high",
                               composite_score=200.0,
                               end_date=(now + timedelta(days=2)).isoformat())

        resp = client.get("/api/top3")
        data = {row["id"]: row for row in resp.json()}
        assert data[low]["strength"] == 1        # floor(10/25)+1 = 1
        assert data[mid]["strength"] == 3        # floor(50/25)+1 = 3
        assert data[high]["strength"] == 4       # capped at 4

    def test_top3_uses_event_end_estimate_over_end_date(self):
        """A sports-style alert where end_date is 7 days out but event_end_estimate
        is in 30 minutes should qualify as TIMING_EDGE."""
        now = datetime.now(timezone.utc)
        with db() as conn:
            cur = conn.cursor()
            # Sports alert: end_date 7 days out (UMA resolution), event_end_estimate 30 min out
            sports_id = _seed_alert(
                cur,
                dedup_key="test_top3_sports_timing",
                market_title="TEST: SportsTiming",
                condition_id="test_top3_cond_sports",
                composite_score=50.0,
                end_date=(now + timedelta(days=7)).isoformat(),
            )
            # Set event_end_estimate directly (not a _seed_alert kwarg)
            cur.execute(
                "UPDATE alerts SET event_end_estimate = %s WHERE id = %s",
                ((now + timedelta(minutes=30)).isoformat(), sports_id),
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        data = resp.json()
        by_cat = {row["category"]: row for row in data}
        # Should land in TIMING_EDGE because effective end time is 30m, not 7d
        assert "TIMING_EDGE" in by_cat
        assert by_cat["TIMING_EDGE"]["id"] == sports_id
        # end_date field in response should surface the event_end_estimate (effective)
        returned = datetime.fromisoformat(by_cat["TIMING_EDGE"]["end_date"])
        diff = (returned - now).total_seconds()
        assert 0 < diff < 3600, f"Expected ~30min, got {diff}s"

    def test_top3_keeps_in_progress_game_visible(self):
        """A sports market whose game started 1h ago (still inside the 3h live
        buffer) must remain visible and qualify as TIMING_EDGE — without the
        live grace, soccer/tennis markets vanish at kickoff because their
        Gamma endDate equals gameStartTime."""
        now = datetime.now(timezone.utc)
        in_progress_start = now - timedelta(hours=1)
        with db() as conn:
            cur = conn.cursor()
            live_id = _seed_alert(
                cur, dedup_key="test_top3_live",
                market_title="TEST: LiveGame",
                condition_id="test_top3_cond_live",
                composite_score=70.0,
                # Mirror Gamma's behavior for soccer: end_date == game_start_time
                end_date=in_progress_start.isoformat(),
                game_start_time=in_progress_start.isoformat(),
                event_end_estimate=in_progress_start.isoformat(),
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        data = resp.json()
        by_id = {row["id"]: row for row in data}
        assert live_id in by_id, "in-progress game should still appear in top3"
        row = by_id[live_id]
        assert row["live"] is True
        assert row["category"] == "TIMING_EDGE"
        assert row["game_start_time"] is not None

    def test_top3_drops_game_past_live_buffer(self):
        """A sports market whose game started 4h ago (past the 3h buffer) is
        stale — must be excluded so post-game alerts don't linger."""
        now = datetime.now(timezone.utc)
        stale_start = now - timedelta(hours=4)
        with db() as conn:
            cur = conn.cursor()
            stale_id = _seed_alert(
                cur, dedup_key="test_top3_stale",
                market_title="TEST: StaleGame",
                condition_id="test_top3_cond_stale",
                composite_score=99.0,  # high score so we'd see it if it leaked
                end_date=stale_start.isoformat(),
                game_start_time=stale_start.isoformat(),
                event_end_estimate=stale_start.isoformat(),
            )

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert stale_id not in ids, "game past 3h live buffer should be filtered out"

    def test_top3_skips_uma_resolved_market(self, monkeypatch):
        """A market whose UMA status is non-empty (proposed/disputed/resolved)
        must be filtered out by the Gamma resolution check, even when its
        Polymarket price hasn't yet pinned to 0/1."""
        import app as app_mod
        now = datetime.now(timezone.utc)

        # Two alerts: a high-score one whose Gamma reports UMA-resolved, and a
        # lower-score "clean" one. The clean one should win the bucket.
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, win_rate, total_pnl, total_invested, updated_at)
                   VALUES ('test_sharp_uma', 0.91, 120000.0, 200000.0, NOW())
                   ON CONFLICT (wallet) DO UPDATE SET win_rate = 0.91, total_pnl = 120000.0""",
            )
            resolved_id = _seed_alert(
                cur, dedup_key="test_top3_uma_resolved",
                market_title="TEST: UmaResolved",
                condition_id="test_top3_cond_uma_resolved",
                wallet="test_sharp_uma",
                composite_score=95.0,
                end_date=(now + timedelta(hours=4)).isoformat(),
            )
            clean_id = _seed_alert(
                cur, dedup_key="test_top3_uma_clean",
                market_title="TEST: UmaClean",
                condition_id="test_top3_cond_uma_clean",
                wallet="test_sharp_uma",
                composite_score=80.0,
                end_date=(now + timedelta(hours=4)).isoformat(),
            )

        # Mock Gamma: the high-score market is UMA-proposed; the other is fine.
        def fake_fetch(cids):
            return {
                "test_top3_cond_uma_resolved": {"closed": False, "uma_status": "proposed", "prices": [0.62, 0.38]},
                "test_top3_cond_uma_clean":    {"closed": False, "uma_status": "", "prices": [0.55, 0.45]},
            }
        monkeypatch.setattr(app_mod, "_fetch_gamma_status", fake_fetch)

        resp = client.get("/api/top3")
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert resolved_id not in ids, "UMA-resolved market should be excluded"
        assert clean_id in ids, "clean lower-score market should fill the bucket"
