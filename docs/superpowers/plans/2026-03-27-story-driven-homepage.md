# Story-Driven Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 engagement features to the PolySpotter homepage: Hero Spotlight, Cross-Market Thesis Cards, Resolution Countdown & Outcome Tracker, One-Click Share Cards, and Wallet Tier Badges.

**Architecture:** Backend-first approach — new PostgreSQL tables and endpoints, then seeder pipeline changes to populate them, then frontend components consuming the new data. Each feature is end-to-end testable independently.

**Tech Stack:** FastAPI (backend), Python/SQLite (seeder/scanner), Next.js 15 / React 19 / Tailwind CSS 4 (frontend)

**Spec:** `docs/superpowers/specs/2026-03-27-story-driven-homepage-design.md`

---

## File Structure

### Backend (new/modified)
- **Modify:** `backend/schema.sql` — add `price_candles`, `wallet_theses`, `alert_outcomes` tables; alter `wallet_profiles`
- **Modify:** `backend/models.py` — add Pydantic models for new tables/endpoints
- **Modify:** `backend/app.py` — add 5 new endpoints, modify ingest + wallet endpoints
- **Create:** `backend/test_new_endpoints.py` — tests for all new endpoints

### Seeder/Scanner (new/modified)
- **Modify:** `seeder.py` — add price candle push, thesis generation, resolution checking, streak computation
- **Modify:** `db.py` — add streak computation helper
- **Create:** `test/test_seeder_new.py` — tests for new seeder functions

### Frontend (new)
- **Create:** `frontend/src/lib/tiers.js` — tier computation + pseudonym generation
- **Create:** `frontend/src/components/WalletBadge.jsx` — reusable tier badge
- **Create:** `frontend/src/components/Sparkline.jsx` — lightweight SVG sparkline
- **Create:** `frontend/src/components/ShareButton.jsx` — copy-to-clipboard share with toast
- **Create:** `frontend/src/components/HeroSpotlight.jsx` — rotating hero carousel
- **Create:** `frontend/src/components/ResolvingSoonStrip.jsx` — countdown strip
- **Create:** `frontend/src/components/ThesisCard.jsx` — cross-market thesis card
- **Create:** `frontend/src/components/ResolvedSection.jsx` — outcome tracker grid
- **Create:** `frontend/src/hooks/useCountdown.js` — live countdown timer hook
- **Create:** `frontend/src/hooks/useSpotlight.js` — spotlight polling hook
- **Create:** `frontend/src/app/api/og/[alertId]/route.jsx` — OG image generation
- **Create:** `frontend/src/app/wallet/[address]/page.jsx` — wallet profile page (server component)
- **Create:** `frontend/src/app/wallet/[address]/wallet-page-client.jsx` — wallet profile client
- **Create:** `frontend/src/app/thesis/[id]/page.jsx` — thesis detail page for sharing

### Frontend (modified)
- **Modify:** `frontend/src/lib/api.js` — add new API fetch functions
- **Modify:** `frontend/src/app/home-client.jsx` — integrate all new sections
- **Modify:** `frontend/src/app/page.jsx` — fetch new data server-side
- **Modify:** `frontend/src/components/AlertRow.jsx` — add WalletBadge + ShareButton

---

## Task 1: Backend Schema — New Tables + Altered Columns

**Files:**
- Modify: `backend/schema.sql`

- [ ] **Step 1: Add price_candles table to schema.sql**

Append after the `wallet_profiles` table definition (after line 102):

```sql
-- Price candle data for sparklines (pushed from local SQLite)
CREATE TABLE IF NOT EXISTS price_candles (
    id SERIAL PRIMARY KEY,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    outcome TEXT,
    t DOUBLE PRECISION NOT NULL,
    p DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_candles_unique ON price_candles (token_id, t);
CREATE INDEX IF NOT EXISTS idx_price_candles_condition ON price_candles (condition_id, t);
```

- [ ] **Step 2: Add wallet_theses table to schema.sql**

```sql
-- Cross-market thesis groupings
CREATE TABLE IF NOT EXISTS wallet_theses (
    id SERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    event_slug TEXT NOT NULL,
    thesis_headline TEXT,
    markets JSONB NOT NULL DEFAULT '[]',
    total_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    composite_score DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(wallet, event_slug)
);
CREATE INDEX IF NOT EXISTS idx_wallet_theses_score ON wallet_theses (composite_score DESC);
```

- [ ] **Step 3: Add alert_outcomes table to schema.sql**

```sql
-- Resolved alert outcomes (win/loss tracking)
CREATE TABLE IF NOT EXISTS alert_outcomes (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    condition_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    won BOOLEAN NOT NULL,
    entry_price DOUBLE PRECISION,
    resolution_price DOUBLE PRECISION,
    pnl_usd DOUBLE PRECISION,
    resolved_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_outcomes_resolved ON alert_outcomes (resolved_at DESC);
```

- [ ] **Step 4: Add current_streak column to wallet_profiles**

```sql
ALTER TABLE wallet_profiles ADD COLUMN IF NOT EXISTS current_streak INTEGER DEFAULT 0;
```

- [ ] **Step 5: Apply schema to database**

Run: `psql $DATABASE_URL -f backend/schema.sql`

- [ ] **Step 6: Commit**

```bash
git add backend/schema.sql
git commit -m "feat: add price_candles, wallet_theses, alert_outcomes tables and current_streak column"
```

---

## Task 2: Backend Models — New Pydantic Models

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add PriceCandleIn model**

Add after `WalletProfileIn` (after line 72):

```python
class PriceCandleIn(BaseModel):
    condition_id: str
    token_id: str
    outcome: str | None = None
    t: float
    p: float


class PriceCandleOut(BaseModel):
    t: float
    p: float
```

- [ ] **Step 2: Add ThesisIn and ThesisOut models**

```python
class ThesisMarket(BaseModel):
    condition_id: str
    market_title: str
    outcome: str
    side: str
    usd_value: float = 0
    entry_price: float = 0


class ThesisIn(BaseModel):
    wallet: str
    event_slug: str
    thesis_headline: str | None = None
    markets: list[ThesisMarket] = []
    total_usd: float = 0
    composite_score: float = 0


class ThesisOut(BaseModel):
    id: int
    wallet: str
    event_slug: str
    thesis_headline: str | None = None
    markets: list[dict] = []
    total_usd: float = 0
    composite_score: float = 0
    win_rate: float | None = None
    total_pnl: float | None = None
    total_invested: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 3: Add AlertOutcomeIn and AlertOutcomeOut models**

```python
class AlertOutcomeIn(BaseModel):
    alert_id: int | None = None
    condition_id: str
    market_title: str
    won: bool
    entry_price: float | None = None
    resolution_price: float | None = None
    pnl_usd: float | None = None
    resolved_at: datetime
    dedup_key: str | None = None  # to find alert_id if not provided


class AlertOutcomeOut(BaseModel):
    id: int
    alert_id: int | None = None
    condition_id: str
    market_title: str
    won: bool
    entry_price: float | None = None
    resolution_price: float | None = None
    pnl_usd: float | None = None
    resolved_at: datetime | None = None
```

- [ ] **Step 4: Add SpotlightOut model**

```python
class SpotlightAlert(BaseModel):
    id: int
    market_title: str | None = None
    condition_id: str | None = None
    event_slug: str | None = None
    composite_score: float = 0
    total_usd: float = 0
    end_date: datetime | None = None
    llm_headline: str | None = None
    llm_summary: str | None = None
    wallet_count: int = 0
    best_win_rate: float | None = None
    best_total_pnl: float | None = None
    current_price: float | None = None
    price_change_24h: float | None = None
    candles: list[PriceCandleOut] = []
    llm_copy_action: dict | None = None
```

- [ ] **Step 5: Update IngestPayload to accept new data**

Change `IngestPayload` (line 75) to:

```python
class IngestPayload(BaseModel):
    alerts: list[AlertIn] = []
    wallet_profiles: list[WalletProfileIn] = []
    price_candles: list[PriceCandleIn] = []
    theses: list[ThesisIn] = []
    alert_outcomes: list[AlertOutcomeIn] = []
```

- [ ] **Step 6: Update WalletProfileIn to include current_streak**

Add field to `WalletProfileIn` (around line 72):

```python
    current_streak: int | None = None
```

- [ ] **Step 7: Update WalletProfileOut to include new fields**

Add fields to `WalletProfileOut` (around line 141):

```python
    current_streak: int | None = None
```

- [ ] **Step 8: Commit**

```bash
git add backend/models.py
git commit -m "feat: add Pydantic models for price_candles, theses, outcomes, spotlight"
```

---

## Task 3: Backend — Extend Ingest Endpoint

**Files:**
- Modify: `backend/app.py`
- Test: `backend/test_new_endpoints.py`

- [ ] **Step 1: Write test for price_candles ingestion**

Create `backend/test_new_endpoints.py`:

```python
"""Tests for new story-driven homepage endpoints."""
import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Use the same test client setup as existing tests
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def _ingest(payload: dict) -> dict:
    resp = client.post("/api/ingest", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPriceCandlesIngestion:
    def test_ingest_price_candles(self):
        result = _ingest({
            "alerts": [],
            "wallet_profiles": [],
            "price_candles": [
                {"condition_id": "0xtest1", "token_id": "tok1", "outcome": "Yes", "t": 1700000000.0, "p": 0.65},
                {"condition_id": "0xtest1", "token_id": "tok1", "outcome": "Yes", "t": 1700000060.0, "p": 0.67},
            ],
        })
        assert result["price_candles"] == 2

    def test_ingest_price_candles_dedup(self):
        """Same token_id + t should not create duplicates."""
        _ingest({
            "price_candles": [
                {"condition_id": "0xtest2", "token_id": "tok_dup", "outcome": "Yes", "t": 1700000000.0, "p": 0.65},
            ],
        })
        result = _ingest({
            "price_candles": [
                {"condition_id": "0xtest2", "token_id": "tok_dup", "outcome": "Yes", "t": 1700000000.0, "p": 0.66},
            ],
        })
        # Should upsert, not fail
        assert result["price_candles"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestPriceCandlesIngestion -v`
Expected: FAIL — ingest endpoint doesn't handle price_candles yet

- [ ] **Step 3: Add price_candles handling to ingest endpoint**

In `backend/app.py`, inside the `ingest()` function (around line 240, before the return), add:

```python
        # Ingest price candles
        candles_count = 0
        for pc in payload.price_candles:
            cur.execute("""
                INSERT INTO price_candles (condition_id, token_id, outcome, t, p)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (token_id, t) DO UPDATE SET p = EXCLUDED.p
            """, (pc.condition_id, pc.token_id, pc.outcome, pc.t, pc.p))
            candles_count += 1
```

Update the return dict to include `"price_candles": candles_count`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestPriceCandlesIngestion -v`
Expected: PASS

- [ ] **Step 5: Write test for theses ingestion**

Add to `test_new_endpoints.py`:

```python
class TestThesesIngestion:
    def test_ingest_thesis(self):
        result = _ingest({
            "theses": [
                {
                    "wallet": "0xthesis_wallet",
                    "event_slug": "iran-ceasefire",
                    "thesis_headline": "Iran talks will collapse",
                    "markets": [
                        {"condition_id": "0xm1", "market_title": "Ceasefire by March 31?", "outcome": "No", "side": "BUY", "usd_value": 31000, "entry_price": 0.28},
                        {"condition_id": "0xm2", "market_title": "Ceasefire by April 15?", "outcome": "No", "side": "BUY", "usd_value": 38000, "entry_price": 0.44},
                    ],
                    "total_usd": 69000,
                    "composite_score": 7.5,
                },
            ],
        })
        assert result["theses"] == 1

    def test_ingest_thesis_upsert(self):
        """Same wallet + event_slug should update, not duplicate."""
        _ingest({
            "theses": [{
                "wallet": "0xthesis_upsert", "event_slug": "test-event",
                "thesis_headline": "V1", "markets": [], "total_usd": 1000, "composite_score": 3.0,
            }],
        })
        result = _ingest({
            "theses": [{
                "wallet": "0xthesis_upsert", "event_slug": "test-event",
                "thesis_headline": "V2 updated", "markets": [], "total_usd": 2000, "composite_score": 5.0,
            }],
        })
        assert result["theses"] == 1
```

- [ ] **Step 6: Implement theses ingestion in ingest endpoint**

Add to `ingest()` in `app.py`:

```python
        # Ingest theses
        theses_count = 0
        for th in payload.theses:
            cur.execute("""
                INSERT INTO wallet_theses (wallet, event_slug, thesis_headline, markets, total_usd, composite_score, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (wallet, event_slug) DO UPDATE SET
                    thesis_headline = EXCLUDED.thesis_headline,
                    markets = EXCLUDED.markets,
                    total_usd = EXCLUDED.total_usd,
                    composite_score = EXCLUDED.composite_score,
                    updated_at = NOW()
            """, (th.wallet, th.event_slug, th.thesis_headline,
                  json.dumps([m.model_dump() for m in th.markets]),
                  th.total_usd, th.composite_score))
            theses_count += 1
```

Update the return dict to include `"theses": theses_count`.

- [ ] **Step 7: Run tests to verify theses pass**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestThesesIngestion -v`
Expected: PASS

- [ ] **Step 8: Write test for alert_outcomes ingestion**

Add to `test_new_endpoints.py`:

```python
class TestAlertOutcomesIngestion:
    def test_ingest_alert_outcome(self):
        # First create an alert to reference
        _ingest({
            "alerts": [{
                "composite_score": 5.0,
                "condition_id": "0xoutcome_test",
                "market_title": "Test Market",
                "dedup_key": "outcome_test_dedup",
                "wallet": "0xwallet",
                "trades": [], "signals": [],
            }],
        })
        result = _ingest({
            "alert_outcomes": [{
                "condition_id": "0xoutcome_test",
                "market_title": "Test Market",
                "won": True,
                "entry_price": 0.65,
                "resolution_price": 1.0,
                "pnl_usd": 538.46,
                "resolved_at": "2026-03-27T12:00:00Z",
                "dedup_key": "outcome_test_dedup",
            }],
        })
        assert result["alert_outcomes"] == 1
```

- [ ] **Step 9: Implement alert_outcomes ingestion**

Add to `ingest()` in `app.py`:

```python
        # Ingest alert outcomes
        outcomes_count = 0
        for ao in payload.alert_outcomes:
            alert_id = ao.alert_id
            if not alert_id and ao.dedup_key:
                cur.execute("SELECT id FROM alerts WHERE dedup_key = %s", (ao.dedup_key,))
                row = cur.fetchone()
                alert_id = row["id"] if row else None
            cur.execute("""
                INSERT INTO alert_outcomes (alert_id, condition_id, market_title, won, entry_price, resolution_price, pnl_usd, resolved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (alert_id, ao.condition_id, ao.market_title, ao.won,
                  ao.entry_price, ao.resolution_price, ao.pnl_usd, ao.resolved_at))
            outcomes_count += 1
```

Update the return dict to include `"alert_outcomes": outcomes_count`.

- [ ] **Step 10: Update wallet_profiles ingestion for current_streak**

In the existing wallet_profiles upsert SQL in `ingest()`, add `current_streak` to the INSERT and ON CONFLICT clauses:

Find the wallet_profiles INSERT statement and add `current_streak` column + value. The ON CONFLICT UPDATE should set `current_streak = EXCLUDED.current_streak`.

- [ ] **Step 11: Run all ingestion tests**

Run: `cd backend && python -m pytest test_new_endpoints.py -v`
Expected: ALL PASS

- [ ] **Step 12: Commit**

```bash
git add backend/app.py backend/test_new_endpoints.py
git commit -m "feat: extend ingest endpoint for price_candles, theses, alert_outcomes, current_streak"
```

---

## Task 4: Backend — Spotlight Endpoint

**Files:**
- Modify: `backend/app.py`
- Test: `backend/test_new_endpoints.py`

- [ ] **Step 1: Write test for spotlight endpoint**

Add to `test_new_endpoints.py`:

```python
class TestSpotlightEndpoint:
    def _seed_alert(self, condition_id, score, title, end_date=None, wallet="0xspot"):
        _ingest({
            "alerts": [{
                "composite_score": score,
                "condition_id": condition_id,
                "market_title": title,
                "wallet": wallet,
                "end_date": end_date or (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                "dedup_key": f"spot_{condition_id}_{wallet}",
                "trades": [{"transaction_hash": f"0xtx_{condition_id}", "wallet": wallet,
                            "condition_id": condition_id, "outcome": "Yes", "side": "BUY",
                            "usd_value": 5000, "price": 0.65}],
                "signals": [{"strategy": "win_rate_tracking", "severity": score, "headline": "test"}],
            }],
            "wallet_profiles": [{"wallet": wallet, "win_rate": 0.78, "total_pnl": 50000}],
        })

    def test_spotlight_returns_top_3(self):
        self._seed_alert("0xsp1", 20.0, "Market A")
        self._seed_alert("0xsp2", 15.0, "Market B")
        self._seed_alert("0xsp3", 10.0, "Market C")
        self._seed_alert("0xsp4", 5.0, "Market D")

        resp = client.get("/api/spotlight")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 3
        # Should be ordered by composite_score DESC
        scores = [a["composite_score"] for a in data]
        assert scores == sorted(scores, reverse=True)

    def test_spotlight_excludes_resolved(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self._seed_alert("0xsp_resolved", 25.0, "Resolved Market", end_date=past)
        resp = client.get("/api/spotlight")
        data = resp.json()
        condition_ids = [a["condition_id"] for a in data]
        assert "0xsp_resolved" not in condition_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestSpotlightEndpoint -v`
Expected: FAIL — 404 on /api/spotlight

- [ ] **Step 3: Implement spotlight endpoint**

Add to `app.py`:

```python
@app.get("/api/spotlight")
async def get_spotlight():
    """Top 3 unresolved alerts by composite score, enriched with wallet count and candles."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.market_title, a.condition_id, a.event_slug,
                   a.composite_score, a.total_usd, a.end_date,
                   a.llm_headline, a.llm_summary, a.llm_copy_action,
                   (SELECT COUNT(DISTINCT at2.wallet) FROM alert_trades at2 WHERE at2.alert_id = a.id) AS wallet_count,
                   wp.win_rate AS best_win_rate, wp.total_pnl AS best_total_pnl
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON a.wallet = wp.wallet
            WHERE a.end_date IS NOT NULL AND a.end_date > NOW()
            ORDER BY a.composite_score DESC
            LIMIT 3
        """)
        rows = cur.fetchall()

        results = []
        for row in rows:
            # Fetch price candles for sparkline (last 24h, ~50 points)
            candles = []
            if row["condition_id"]:
                cur.execute("""
                    SELECT t, p FROM price_candles
                    WHERE condition_id = %s AND t > EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')
                    ORDER BY t ASC
                """, (row["condition_id"],))
                candles = [{"t": c["t"], "p": c["p"]} for c in cur.fetchall()]

            copy_action = row["llm_copy_action"]
            if isinstance(copy_action, str):
                try:
                    copy_action = json.loads(copy_action)
                except (json.JSONDecodeError, TypeError):
                    copy_action = {}

            results.append({
                "id": row["id"],
                "market_title": row["market_title"],
                "condition_id": row["condition_id"],
                "event_slug": row["event_slug"],
                "composite_score": row["composite_score"],
                "total_usd": row["total_usd"],
                "end_date": row["end_date"].isoformat() if row["end_date"] else None,
                "llm_headline": row["llm_headline"],
                "llm_summary": row["llm_summary"],
                "llm_copy_action": copy_action,
                "wallet_count": row["wallet_count"] or 0,
                "best_win_rate": row["best_win_rate"],
                "best_total_pnl": row["best_total_pnl"],
                "candles": candles,
            })
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestSpotlightEndpoint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_new_endpoints.py
git commit -m "feat: add GET /api/spotlight endpoint for hero section"
```

---

## Task 5: Backend — Resolving Soon + Resolved Endpoints

**Files:**
- Modify: `backend/app.py`
- Test: `backend/test_new_endpoints.py`

- [ ] **Step 1: Write test for resolving-soon endpoint**

Add to `test_new_endpoints.py`:

```python
class TestResolvingSoonEndpoint:
    def test_resolving_soon_returns_upcoming(self):
        # Seed alert resolving in 3 hours
        end = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        _ingest({
            "alerts": [{
                "composite_score": 8.0, "condition_id": "0xresoon1",
                "market_title": "Soon Market", "wallet": "0xw1",
                "end_date": end, "dedup_key": "resoon1",
                "llm_copy_action": json.dumps({"outcome": "Yes", "side": "BUY", "entry_price": 0.6, "max_price": 0.7}),
                "trades": [], "signals": [],
            }],
        })
        resp = client.get("/api/resolving-soon")
        assert resp.status_code == 200
        data = resp.json()
        cids = [a["condition_id"] for a in data]
        assert "0xresoon1" in cids

    def test_resolving_soon_excludes_past(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _ingest({
            "alerts": [{
                "composite_score": 8.0, "condition_id": "0xresoon_past",
                "market_title": "Past Market", "wallet": "0xw2",
                "end_date": past, "dedup_key": "resoon_past",
                "trades": [], "signals": [],
            }],
        })
        resp = client.get("/api/resolving-soon")
        data = resp.json()
        cids = [a["condition_id"] for a in data]
        assert "0xresoon_past" not in cids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestResolvingSoonEndpoint -v`
Expected: FAIL

- [ ] **Step 3: Implement resolving-soon endpoint**

```python
@app.get("/api/resolving-soon")
async def get_resolving_soon():
    """Alerts resolving within 6 hours, sorted by end_date ASC."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (a.condition_id)
                a.id, a.condition_id, a.market_title, a.end_date,
                a.total_usd, a.composite_score, a.llm_copy_action
            FROM alerts a
            WHERE a.end_date IS NOT NULL
              AND a.end_date > NOW()
              AND a.end_date <= NOW() + INTERVAL '6 hours'
            ORDER BY a.condition_id, a.composite_score DESC
        """)
        rows = cur.fetchall()

        results = []
        for row in rows:
            copy_action = row["llm_copy_action"]
            if isinstance(copy_action, str):
                try:
                    copy_action = json.loads(copy_action)
                except (json.JSONDecodeError, TypeError):
                    copy_action = {}
            results.append({
                "id": row["id"],
                "condition_id": row["condition_id"],
                "market_title": row["market_title"],
                "end_date": row["end_date"].isoformat() if row["end_date"] else None,
                "total_usd": row["total_usd"],
                "composite_score": row["composite_score"],
                "dominant_side": copy_action.get("side") if copy_action else None,
            })

        results.sort(key=lambda x: x["end_date"] or "")
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestResolvingSoonEndpoint -v`
Expected: PASS

- [ ] **Step 5: Write test for resolved endpoint**

Add to `test_new_endpoints.py`:

```python
class TestResolvedEndpoint:
    def test_resolved_returns_outcomes(self):
        # Seed an alert + outcome
        _ingest({
            "alerts": [{
                "composite_score": 6.0, "condition_id": "0xresolved1",
                "market_title": "Resolved Test", "wallet": "0xrw1",
                "dedup_key": "resolved1", "trades": [], "signals": [],
            }],
            "alert_outcomes": [{
                "condition_id": "0xresolved1", "market_title": "Resolved Test",
                "won": True, "entry_price": 0.65, "resolution_price": 1.0,
                "pnl_usd": 538.0, "resolved_at": datetime.now(timezone.utc).isoformat(),
                "dedup_key": "resolved1",
            }],
        })
        resp = client.get("/api/resolved?hours=24")
        assert resp.status_code == 200
        data = resp.json()
        assert "outcomes" in data
        assert "win_rate_7d" in data
        cids = [o["condition_id"] for o in data["outcomes"]]
        assert "0xresolved1" in cids

    def test_resolved_excludes_old(self):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        _ingest({
            "alerts": [{
                "composite_score": 6.0, "condition_id": "0xresolved_old",
                "market_title": "Old Resolved", "wallet": "0xrw2",
                "dedup_key": "resolved_old", "trades": [], "signals": [],
            }],
            "alert_outcomes": [{
                "condition_id": "0xresolved_old", "market_title": "Old Resolved",
                "won": False, "entry_price": 0.5, "resolution_price": 0.0,
                "pnl_usd": -500.0, "resolved_at": old_time,
                "dedup_key": "resolved_old",
            }],
        })
        resp = client.get("/api/resolved?hours=24")
        data = resp.json()
        cids = [o["condition_id"] for o in data["outcomes"]]
        assert "0xresolved_old" not in cids
```

- [ ] **Step 6: Implement resolved endpoint**

```python
@app.get("/api/resolved")
async def get_resolved(hours: int = 24):
    """Recently resolved alerts with win/loss outcomes."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ao.id, ao.alert_id, ao.condition_id, ao.market_title,
                   ao.won, ao.entry_price, ao.resolution_price, ao.pnl_usd, ao.resolved_at
            FROM alert_outcomes ao
            WHERE ao.resolved_at > NOW() - INTERVAL '%s hours'
            ORDER BY ao.resolved_at DESC
        """, (hours,))
        outcomes = [dict(row) for row in cur.fetchall()]
        for o in outcomes:
            if o.get("resolved_at"):
                o["resolved_at"] = o["resolved_at"].isoformat()

        # 7-day aggregate win rate
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE won = TRUE) AS wins,
                   COUNT(*) AS total
            FROM alert_outcomes
            WHERE resolved_at > NOW() - INTERVAL '7 days'
        """)
        stats = cur.fetchone()
        wins_7d = stats["wins"] or 0
        total_7d = stats["total"] or 0
        win_rate_7d = round(wins_7d / total_7d, 2) if total_7d > 0 else None

        return {
            "outcomes": outcomes,
            "wins_7d": wins_7d,
            "total_7d": total_7d,
            "win_rate_7d": win_rate_7d,
        }
```

- [ ] **Step 7: Run all tests**

Run: `cd backend && python -m pytest test_new_endpoints.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app.py backend/test_new_endpoints.py
git commit -m "feat: add GET /api/resolving-soon and GET /api/resolved endpoints"
```

---

## Task 6: Backend — Theses Endpoint + Extended Wallet Endpoint

**Files:**
- Modify: `backend/app.py`
- Test: `backend/test_new_endpoints.py`

- [ ] **Step 1: Write test for theses endpoint**

```python
class TestThesesEndpoint:
    def test_theses_returns_paginated(self):
        _ingest({
            "theses": [{
                "wallet": "0xthesis_ep", "event_slug": "iran-event",
                "thesis_headline": "Iran talks collapse",
                "markets": [
                    {"condition_id": "0xt1", "market_title": "M1", "outcome": "No", "side": "BUY", "usd_value": 30000, "entry_price": 0.28},
                ],
                "total_usd": 30000, "composite_score": 7.0,
            }],
            "wallet_profiles": [{"wallet": "0xthesis_ep", "win_rate": 0.82, "total_pnl": 100000, "total_invested": 200000}],
        })
        resp = client.get("/api/theses?page=1&per_page=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "theses" in data
        assert "total" in data
        assert len(data["theses"]) >= 1
        thesis = next(t for t in data["theses"] if t["wallet"] == "0xthesis_ep")
        assert thesis["thesis_headline"] == "Iran talks collapse"
        assert thesis["win_rate"] == 0.82
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestThesesEndpoint -v`
Expected: FAIL

- [ ] **Step 3: Implement theses endpoint**

```python
@app.get("/api/theses")
async def list_theses(page: int = 1, per_page: int = 10):
    """Active cross-market thesis cards, sorted by composite_score."""
    offset = (page - 1) * per_page
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM wallet_theses")
        total = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT wt.*, wp.win_rate, wp.total_pnl, wp.total_invested
            FROM wallet_theses wt
            LEFT JOIN wallet_profiles wp ON wt.wallet = wp.wallet
            ORDER BY wt.composite_score DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = cur.fetchall()

        theses = []
        for row in rows:
            markets = row["markets"]
            if isinstance(markets, str):
                try:
                    markets = json.loads(markets)
                except (json.JSONDecodeError, TypeError):
                    markets = []
            theses.append({
                "id": row["id"],
                "wallet": row["wallet"],
                "event_slug": row["event_slug"],
                "thesis_headline": row["thesis_headline"],
                "markets": markets,
                "total_usd": row["total_usd"],
                "composite_score": row["composite_score"],
                "win_rate": row["win_rate"],
                "total_pnl": row["total_pnl"],
                "total_invested": row["total_invested"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            })

        return {"theses": theses, "total": total, "page": page, "per_page": per_page}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest test_new_endpoints.py::TestThesesEndpoint -v`
Expected: PASS

- [ ] **Step 5: Write test for extended wallet endpoint**

```python
class TestExtendedWalletEndpoint:
    def test_wallet_includes_streak_and_recent_alerts(self):
        _ingest({
            "alerts": [{
                "composite_score": 5.0, "condition_id": "0xwallet_ext",
                "market_title": "Wallet Test", "wallet": "0xext_wallet",
                "dedup_key": "ext_wallet_1",
                "trades": [{"transaction_hash": "0xtx_ext", "wallet": "0xext_wallet",
                            "condition_id": "0xwallet_ext", "outcome": "Yes", "side": "BUY",
                            "usd_value": 3000, "price": 0.5}],
                "signals": [],
            }],
            "wallet_profiles": [{
                "wallet": "0xext_wallet", "win_rate": 0.75, "total_pnl": 50000,
                "total_invested": 100000, "current_streak": 5,
                "wins": 30, "losses": 10,
            }],
        })
        resp = client.get("/api/wallets/0xext_wallet")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_streak"] == 5
        assert "recent_alerts" in data
```

- [ ] **Step 6: Extend wallet endpoint with recent_alerts**

Modify the `get_wallet()` function in `app.py` (around line 495) to also query recent alerts:

```python
@app.get("/api/wallets/{wallet_address}")
async def get_wallet(wallet_address: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM wallet_profiles WHERE wallet = %s", (wallet_address.lower(),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Wallet not found")

        profile = dict(row)
        if profile.get("first_seen_at"):
            profile["first_seen_at"] = profile["first_seen_at"].isoformat()
        if profile.get("updated_at"):
            profile["updated_at"] = profile["updated_at"].isoformat()

        # Fetch recent alerts for this wallet
        cur.execute("""
            SELECT a.id, a.market_title, a.composite_score, a.total_usd,
                   a.llm_headline, a.created_at, a.condition_id
            FROM alerts a
            WHERE a.wallet = %s
            ORDER BY a.created_at DESC
            LIMIT 5
        """, (wallet_address.lower(),))
        recent_alerts = []
        for arow in cur.fetchall():
            recent_alerts.append({
                "id": arow["id"],
                "market_title": arow["market_title"],
                "composite_score": arow["composite_score"],
                "total_usd": arow["total_usd"],
                "llm_headline": arow["llm_headline"],
                "created_at": arow["created_at"].isoformat() if arow["created_at"] else None,
                "condition_id": arow["condition_id"],
            })

        profile["recent_alerts"] = recent_alerts
        return profile
```

- [ ] **Step 7: Run all tests**

Run: `cd backend && python -m pytest test_new_endpoints.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app.py backend/test_new_endpoints.py
git commit -m "feat: add GET /api/theses endpoint and extend wallet endpoint with recent_alerts"
```

---

## Task 7: Seeder — Price Candle Push + Extended Wallet Profiles

**Files:**
- Modify: `seeder.py`
- Modify: `db.py`

- [ ] **Step 1: Add streak computation helper to db.py**

Add near the other wallet query helpers:

```python
def get_wallet_current_streak(wallet: str) -> int:
    """Count consecutive wins from the most recent resolved bet backward."""
    conn = get_connection()
    cur = conn.execute("""
        SELECT won FROM tracked_bets
        WHERE wallet = ? AND resolved = 1 AND won IS NOT NULL
        ORDER BY trade_timestamp DESC
    """, (wallet,))
    streak = 0
    for row in cur.fetchall():
        if row[0] == 1:
            streak += 1
        else:
            break
    return streak
```

- [ ] **Step 2: Add price candle extraction helper to db.py**

```python
def get_recent_price_candles(condition_ids: list[str], since_hours: int = 24) -> list[dict]:
    """Get price candles for given condition_ids from the last N hours."""
    if not condition_ids:
        return []
    conn = get_connection()
    import time
    cutoff = time.time() - (since_hours * 3600)
    placeholders = ",".join("?" for _ in condition_ids)
    cur = conn.execute(f"""
        SELECT condition_id, token_id, outcome, t, p FROM price_candles
        WHERE condition_id IN ({placeholders}) AND t > ?
        ORDER BY t ASC
    """, (*condition_ids, cutoff))
    return [{"condition_id": r[0], "token_id": r[1], "outcome": r[2], "t": r[3], "p": r[4]}
            for r in cur.fetchall()]
```

- [ ] **Step 3: Commit db.py changes**

```bash
git add db.py
git commit -m "feat: add streak computation and price candle extraction helpers"
```

- [ ] **Step 4: Update seeder wallet profile building to include current_streak**

In `seeder.py`, in the `build_alerts_payload` function where wallet profiles are built (around line 392-413), update to include streak:

```python
        from db import get_wallet_current_streak
        # ... existing wallet profile building code ...
        profile["current_streak"] = get_wallet_current_streak(wallet)
```

Add the `current_streak` field to the profile dict being built.

- [ ] **Step 5: Add price candle push to push_to_backend**

In `seeder.py`, update `push_to_backend` to gather and send price candles. After `build_alerts_payload` (around line 429), add:

```python
    # Gather price candles for alerted markets
    from db import get_recent_price_candles
    alerted_cids = list({a["condition_id"] for a in payload["alerts"] if a.get("condition_id")})
    raw_candles = get_recent_price_candles(alerted_cids, since_hours=24)
    payload["price_candles"] = [
        {"condition_id": c["condition_id"], "token_id": c["token_id"],
         "outcome": c["outcome"], "t": c["t"], "p": c["p"]}
        for c in raw_candles
    ]
```

- [ ] **Step 6: Commit seeder changes**

```bash
git add seeder.py
git commit -m "feat: push price candles and wallet streaks to backend"
```

---

## Task 8: Seeder — Thesis Generation

**Files:**
- Modify: `seeder.py`

- [ ] **Step 1: Add thesis building function to seeder.py**

Add after `build_alerts_payload`:

```python
def build_theses_payload(signals: list, trades: list[dict]) -> list[dict]:
    """Build thesis payloads from correlated_cross_market signals."""
    from db import get_wallet_event_history
    from gamma_cache import get_market_by_condition

    cross_signals = [s for s in signals if s.strategy == "correlated_cross_market"]
    if not cross_signals:
        return []

    # Group by (wallet, event_slug)
    groups: dict[tuple[str, str], list] = {}
    for sig in cross_signals:
        wallet = sig.trade.get("proxyWallet", "").lower()
        event_slug = sig.trade.get("eventSlug", "")
        if wallet and event_slug:
            groups.setdefault((wallet, event_slug), []).append(sig)

    theses = []
    for (wallet, event_slug), sigs in groups.items():
        # Collect all markets for this wallet+event
        seen_cids = set()
        markets = []
        for sig in sigs:
            cid = sig.condition_id or sig.trade.get("conditionId", "")
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            market_info = get_market_by_condition(cid) or {}
            markets.append({
                "condition_id": cid,
                "market_title": market_info.get("title", sig.trade.get("title", "")),
                "outcome": sig.trade.get("outcome", ""),
                "side": sig.trade.get("side", ""),
                "usd_value": float(sig.trade.get("_usd_value", 0)),
                "entry_price": float(sig.trade.get("price", 0)),
            })

        # Also pull historical positions from wallet_event_history
        history = get_wallet_event_history(wallet, event_slug)
        for h in history:
            if h["condition_id"] not in seen_cids:
                seen_cids.add(h["condition_id"])
                hmarket = get_market_by_condition(h["condition_id"]) or {}
                markets.append({
                    "condition_id": h["condition_id"],
                    "market_title": hmarket.get("title", ""),
                    "outcome": h["outcome"],
                    "side": h["side"],
                    "usd_value": float(h["usd_value"]),
                    "entry_price": 0,
                })

        total_usd = sum(m["usd_value"] for m in markets)
        composite_score = max((s.severity for s in sigs), default=0)

        theses.append({
            "wallet": wallet,
            "event_slug": event_slug,
            "thesis_headline": None,  # Will be filled by LLM below
            "markets": markets,
            "total_usd": total_usd,
            "composite_score": composite_score,
        })

    return theses
```

- [ ] **Step 2: Add LLM thesis headline generation**

Add a function to generate thesis headlines via the existing LLM infrastructure:

```python
def _generate_thesis_headline(thesis: dict) -> str | None:
    """Generate a short thesis headline from market titles and bet directions."""
    market_descriptions = []
    for m in thesis["markets"]:
        direction = f"{m['side']} {m['outcome']}" if m.get("side") and m.get("outcome") else ""
        market_descriptions.append(f"{m.get('market_title', '')} ({direction})")

    prompt = (
        f"A trader is betting across these related markets:\n"
        + "\n".join(f"- {d}" for d in market_descriptions)
        + f"\nTotal position: ${thesis['total_usd']:,.0f}"
        + "\n\nWrite a 3-6 word thesis headline capturing what this trader believes. "
        + "Examples: 'Iran talks will collapse', 'Lakers sweep the series', 'Fed holds rates steady'. "
        + "Return ONLY the headline, no quotes."
    )

    try:
        import os
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip().strip('"')
    except Exception:
        return None
```

- [ ] **Step 3: Integrate thesis building into push_to_backend**

In `push_to_backend`, after building the main payload and before the POST:

```python
    # Build and add theses
    theses = build_theses_payload(signals, trades)
    for thesis in theses:
        if not thesis["thesis_headline"]:
            thesis["thesis_headline"] = _generate_thesis_headline(thesis)
    payload["theses"] = theses
```

- [ ] **Step 4: Commit**

```bash
git add seeder.py
git commit -m "feat: generate cross-market thesis payloads with LLM headlines"
```

---

## Task 9: Seeder — Resolution Checking

**Files:**
- Modify: `seeder.py`
- Modify: `db.py`

- [ ] **Step 1: Add resolution check function to seeder.py**

```python
def check_resolutions_and_push() -> int:
    """Check if any previously-alerted markets have resolved, compute outcomes, push to backend."""
    import requests
    from gamma_cache import get_market_by_condition

    BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

    # Get all alerts with end_date in the past that don't have outcomes yet
    resp = requests.get(f"{BACKEND_URL}/api/alerts", params={"per_page": 100, "page": 1})
    if resp.status_code != 200:
        return 0

    alerts = resp.json().get("alerts", [])
    outcomes = []

    for alert in alerts:
        end_date = alert.get("end_date")
        condition_id = alert.get("condition_id")
        if not end_date or not condition_id:
            continue

        # Check if market has resolved via Gamma API
        market = get_market_by_condition(condition_id)
        if not market:
            continue

        # Check if resolved: any outcome price >= 0.95 from CLOB
        try:
            clob_resp = requests.get(
                f"https://clob.polymarket.com/midpoints",
                params={"token_ids": ",".join(
                    t.get("token_id", "") for t in market.get("tokens", []) if t.get("token_id")
                )},
                timeout=5,
            )
            if clob_resp.status_code != 200:
                continue
            midpoints = clob_resp.json()
        except Exception:
            continue

        resolved_outcome = None
        resolution_price = None
        for token in market.get("tokens", []):
            tid = token.get("token_id", "")
            price = float(midpoints.get(tid, 0))
            if price >= 0.95:
                resolved_outcome = token.get("outcome", "")
                resolution_price = price
                break

        if not resolved_outcome:
            continue

        # Determine if alert's bet won
        copy_action = alert.get("llm_copy_action") or {}
        if isinstance(copy_action, str):
            try:
                copy_action = json.loads(copy_action)
            except Exception:
                copy_action = {}

        alert_outcome = copy_action.get("outcome", "")
        alert_side = copy_action.get("side", "")
        entry_price = copy_action.get("entry_price", 0)

        # Won if: BUY on winning outcome, or SELL on losing outcome
        won = False
        if alert_side == "BUY" and alert_outcome == resolved_outcome:
            won = True
        elif alert_side == "SELL" and alert_outcome != resolved_outcome:
            won = True

        pnl_usd = 0
        if won and entry_price > 0:
            pnl_usd = alert.get("total_usd", 0) * ((1.0 / entry_price) - 1.0)
        elif not won:
            pnl_usd = -alert.get("total_usd", 0)

        outcomes.append({
            "condition_id": condition_id,
            "market_title": alert.get("market_title", ""),
            "won": won,
            "entry_price": entry_price,
            "resolution_price": resolution_price,
            "pnl_usd": round(pnl_usd, 2),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "dedup_key": alert.get("dedup_key"),
        })

    if not outcomes:
        return 0

    # Push outcomes to backend
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/ingest",
            json={"alert_outcomes": outcomes},
            timeout=30,
        )
        return resp.json().get("alert_outcomes", 0) if resp.status_code == 200 else 0
    except Exception:
        return 0
```

- [ ] **Step 2: Call resolution checking from push_to_backend**

At the end of `push_to_backend`, after the main POST succeeds:

```python
    # Check for newly resolved markets
    try:
        resolved_count = check_resolutions_and_push()
        if resolved_count:
            print(f"  📊 Pushed {resolved_count} resolution outcomes")
    except Exception as e:
        print(f"  ⚠️ Resolution check failed: {e}")
```

- [ ] **Step 3: Commit**

```bash
git add seeder.py
git commit -m "feat: add resolution checking and outcome push to seeder pipeline"
```

---

## Task 10: Frontend — Tier + Pseudonym Libs

**Files:**
- Create: `frontend/src/lib/tiers.js`
- Create: `frontend/src/lib/pseudonym.js`

- [ ] **Step 1: Create tiers.js**

```javascript
/**
 * Wallet tier computation from win_rate + total_invested.
 * Both thresholds must be met.
 */

const TIERS = [
  { name: "Diamond", minWinRate: 0.85, minInvested: 100_000, color: "#8b5cf6", prefix: "Whale" },
  { name: "Gold",    minWinRate: 0.75, minInvested: 50_000,  color: "#f59e0b", prefix: "Sharp" },
  { name: "Silver",  minWinRate: 0.65, minInvested: 10_000,  color: "#94a3b8", prefix: "Trader" },
  { name: "Bronze",  minWinRate: 0.50, minInvested: 0,       color: "#b45309", prefix: "Wallet" },
];

export function computeTier(winRate, totalInvested) {
  if (winRate == null || winRate < 0.5) return null;
  const invested = totalInvested || 0;
  for (const tier of TIERS) {
    if (winRate >= tier.minWinRate && invested >= tier.minInvested) {
      return tier;
    }
  }
  return null;
}

export function tierBgClass(tierName) {
  switch (tierName) {
    case "Diamond": return "bg-purple-500/15 text-purple-400";
    case "Gold":    return "bg-amber-500/15 text-amber-400";
    case "Silver":  return "bg-slate-400/15 text-slate-400";
    case "Bronze":  return "bg-amber-700/15 text-amber-700";
    default:        return "bg-gray-500/15 text-gray-400";
  }
}
```

- [ ] **Step 2: Create pseudonym.js**

```javascript
/**
 * Deterministic wallet pseudonyms from address + tier.
 */

export function walletPseudonym(address, tier) {
  if (!address) return "Unknown";
  const prefix = tier?.prefix || "Wallet";
  const short = address.startsWith("0x") ? address.slice(2, 7) : address.slice(0, 5);
  return `${prefix}_0x${short}`;
}

export function shortenAddress(address) {
  if (!address) return "";
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/tiers.js frontend/src/lib/pseudonym.js
git commit -m "feat: add wallet tier computation and pseudonym generation"
```

---

## Task 11: Frontend — WalletBadge Component

**Files:**
- Create: `frontend/src/components/WalletBadge.jsx`

- [ ] **Step 1: Create WalletBadge.jsx**

```jsx
"use client";

import { computeTier, tierBgClass } from "../lib/tiers";
import { walletPseudonym } from "../lib/pseudonym";

export default function WalletBadge({ wallet, winRate, totalPnl, totalInvested, compact = false }) {
  const tier = computeTier(winRate, totalInvested);
  const name = walletPseudonym(wallet, tier);

  if (!tier) {
    return (
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        {wallet ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}` : "Unknown"}
      </span>
    );
  }

  const winPct = winRate != null ? `${Math.round(winRate * 100)}%` : null;

  return (
    <div className="flex items-center gap-2">
      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full text-xs font-bold shrink-0"
        style={{
          width: compact ? 24 : 32,
          height: compact ? 24 : 32,
          background: `${tier.color}22`,
          border: `2px solid ${tier.color}`,
          color: tier.color,
        }}
      >
        {tier.name === "Diamond" ? "💎" : tier.name === "Gold" ? "🏆" : tier.name === "Silver" ? "🥈" : "🥉"}
      </div>

      <div className="flex flex-col min-w-0">
        {/* Name */}
        <span className="text-xs font-bold truncate" style={{ color: "var(--text-primary)" }}>
          {name}
        </span>

        {/* Badges row */}
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-bold ${tierBgClass(tier.name)}`}>
            {tier.name.toUpperCase()}
          </span>
          {winPct && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px]"
              style={{ background: "rgba(0,194,106,0.12)", color: "var(--bullish)" }}>
              {winPct} WR
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/WalletBadge.jsx
git commit -m "feat: add WalletBadge component with tier badges and pseudonyms"
```

---

## Task 12: Frontend — Sparkline + ShareButton Components

**Files:**
- Create: `frontend/src/components/Sparkline.jsx`
- Create: `frontend/src/components/ShareButton.jsx`

- [ ] **Step 1: Create Sparkline.jsx**

```jsx
"use client";

export default function Sparkline({ candles, entryPrice, width = 200, height = 50 }) {
  if (!candles || candles.length < 2) return null;

  const prices = candles.map((c) => c.p);
  const times = candles.map((c) => c.t);
  const minP = Math.min(...prices) * 0.98;
  const maxP = Math.max(...prices) * 1.02;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeP = maxP - minP || 1;
  const rangeT = maxT - minT || 1;

  const points = candles.map((c) => {
    const x = ((c.t - minT) / rangeT) * width;
    const y = height - ((c.p - minP) / rangeP) * height;
    return `${x},${y}`;
  }).join(" ");

  // Entry price marker
  let entryY = null;
  if (entryPrice != null) {
    entryY = height - ((entryPrice - minP) / rangeP) * height;
  }

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      {/* Gradient fill */}
      <defs>
        <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.15" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Fill area */}
      <polygon
        points={`0,${height} ${points} ${width},${height}`}
        fill="url(#sparkFill)"
      />

      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Entry price dot */}
      {entryY != null && (
        <circle
          cx={width * 0.85}
          cy={entryY}
          r="3"
          fill="var(--accent)"
          style={{ filter: "drop-shadow(0 0 4px var(--accent))" }}
        />
      )}
    </svg>
  );
}
```

- [ ] **Step 2: Create ShareButton.jsx**

```jsx
"use client";

import { useState } from "react";

export default function ShareButton({ url, compact = false }) {
  const [copied, setCopied] = useState(false);

  async function handleShare() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS contexts
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <button
      onClick={handleShare}
      className="inline-flex items-center gap-1.5 rounded-lg text-xs transition-colors"
      style={{
        padding: compact ? "4px 8px" : "6px 14px",
        background: "var(--surface-1)",
        color: copied ? "var(--accent)" : "var(--text-muted)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {copied ? "✓ Copied" : "📤 Share"}
    </button>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sparkline.jsx frontend/src/components/ShareButton.jsx
git commit -m "feat: add Sparkline and ShareButton components"
```

---

## Task 13: Frontend — API Functions for New Endpoints

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add new API functions**

Add at the end of `api.js`:

```javascript
export function fetchSpotlight() {
  return request("/api/spotlight");
}

export function fetchResolvingSoon() {
  return request("/api/resolving-soon");
}

export function fetchResolved(hours = 24) {
  return request("/api/resolved", { hours });
}

export function fetchTheses(page = 1, perPage = 5) {
  return request("/api/theses", { page, per_page: perPage });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: add API functions for spotlight, resolving-soon, resolved, theses"
```

---

## Task 14: Frontend — Countdown Hook

**Files:**
- Create: `frontend/src/hooks/useCountdown.js`

- [ ] **Step 1: Create useCountdown.js**

```javascript
"use client";

import { useState, useEffect } from "react";

export function useCountdown(targetDate) {
  const [timeLeft, setTimeLeft] = useState(() => getTimeLeft(targetDate));

  useEffect(() => {
    const timer = setInterval(() => {
      setTimeLeft(getTimeLeft(targetDate));
    }, 1000);
    return () => clearInterval(timer);
  }, [targetDate]);

  return timeLeft;
}

function getTimeLeft(targetDate) {
  if (!targetDate) return { total: 0, hours: 0, minutes: 0, seconds: 0, label: "—" };
  const diff = new Date(targetDate).getTime() - Date.now();
  if (diff <= 0) return { total: 0, hours: 0, minutes: 0, seconds: 0, label: "Resolved" };

  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
  const seconds = Math.floor((diff % (1000 * 60)) / 1000);

  let label;
  if (hours > 0) label = `${hours}h ${minutes}m`;
  else if (minutes > 0) label = `${minutes}m ${seconds}s`;
  else label = `${seconds}s`;

  return { total: diff, hours, minutes, seconds, label };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useCountdown.js
git commit -m "feat: add useCountdown hook for live countdown timers"
```

---

## Task 15: Frontend — HeroSpotlight Component

**Files:**
- Create: `frontend/src/components/HeroSpotlight.jsx`
- Create: `frontend/src/hooks/useSpotlight.js`

- [ ] **Step 1: Create useSpotlight.js**

```javascript
"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSpotlight } from "../lib/api";

export function useSpotlight() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const result = await fetchSpotlight();
      setData(result);
    } catch {
      // silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}
```

- [ ] **Step 2: Create HeroSpotlight.jsx**

```jsx
"use client";

import { useState, useEffect } from "react";
import { useSpotlight } from "../hooks/useSpotlight";
import { useCountdown } from "../hooks/useCountdown";
import Sparkline from "./Sparkline";
import WalletBadge from "./WalletBadge";

function SpotlightSlide({ alert }) {
  const countdown = useCountdown(alert.end_date);
  const copyAction = alert.llm_copy_action || {};
  const entryPrice = copyAction.entry_price;

  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div className="flex flex-col gap-3 px-5 py-5 rounded-xl"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Biggest move right now
          </p>
          <h2 className="text-lg font-bold mt-1 truncate" style={{ color: "var(--text-primary)" }}>
            {alert.market_title}
          </h2>
          <p className="text-sm mt-1" style={{ color: "var(--accent)" }}>
            {usdFmt.format(alert.total_usd)} in smart money flow
            {alert.wallet_count > 1 ? ` · ${alert.wallet_count} sharp wallets aligned` : ""}
          </p>
        </div>
        {alert.candles?.length > 0 && (
          <div className="shrink-0">
            <Sparkline candles={alert.candles} entryPrice={entryPrice} width={140} height={48} />
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        {alert.best_win_rate != null && (
          <span>🎯 {Math.round(alert.best_win_rate * 100)}% win rate wallet</span>
        )}
        <span>⏱ Resolves in {countdown.label}</span>
      </div>
    </div>
  );
}

export default function HeroSpotlight() {
  const { data, loading } = useSpotlight();
  const [activeIndex, setActiveIndex] = useState(0);

  // Auto-rotate every 8s
  useEffect(() => {
    if (data.length <= 1) return;
    const timer = setInterval(() => {
      setActiveIndex((i) => (i + 1) % data.length);
    }, 8000);
    return () => clearInterval(timer);
  }, [data.length]);

  if (loading || data.length === 0) return null;

  return (
    <div className="mb-4"
      onMouseEnter={() => {/* pause handled by clearing interval on unmount */}}
    >
      <SpotlightSlide alert={data[activeIndex]} />

      {data.length > 1 && (
        <div className="flex justify-center gap-1.5 mt-2">
          {data.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className="rounded-full transition-all"
              style={{
                width: i === activeIndex ? 16 : 6,
                height: 6,
                background: i === activeIndex ? "var(--accent)" : "var(--border)",
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HeroSpotlight.jsx frontend/src/hooks/useSpotlight.js
git commit -m "feat: add HeroSpotlight carousel component with sparkline and countdown"
```

---

## Task 16: Frontend — ResolvingSoonStrip Component

**Files:**
- Create: `frontend/src/components/ResolvingSoonStrip.jsx`

- [ ] **Step 1: Create ResolvingSoonStrip.jsx**

```jsx
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchResolvingSoon } from "../lib/api";
import { useCountdown } from "../hooks/useCountdown";
import { marketSlug } from "../lib/slugify";

function ResolvingCard({ alert }) {
  const countdown = useCountdown(alert.end_date);
  const urgent = countdown.total > 0 && countdown.total < 3600_000; // < 1 hour
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const slug = marketSlug(alert.market_title, alert.condition_id);

  return (
    <Link href={`/market/${slug}`} className="shrink-0">
      <div
        className={`rounded-lg px-4 py-3 transition-all ${urgent ? "animate-urgency" : ""}`}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderLeftWidth: 3,
          borderLeftColor: urgent ? "var(--bearish)" : "var(--warning)",
          minWidth: 200,
          maxWidth: 260,
        }}
      >
        <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
          {alert.market_title}
        </p>
        <p
          className="text-lg font-bold mt-0.5"
          style={{ color: urgent ? "var(--bearish)" : "var(--warning)", fontFamily: "var(--font-display)" }}
        >
          {countdown.label}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {usdFmt.format(alert.total_usd)} smart money
          {alert.dominant_side ? ` on ${alert.dominant_side}` : ""}
        </p>
      </div>
    </Link>
  );
}

export default function ResolvingSoonStrip() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    fetchResolvingSoon().then(setAlerts).catch(() => {});
    const interval = setInterval(() => {
      fetchResolvingSoon().then(setAlerts).catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div className="mb-4">
      <p className="text-[11px] uppercase tracking-wider mb-2 px-1"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        Resolving Soon
      </p>
      <div className="flex gap-3 overflow-x-auto pb-2" style={{ scrollbarWidth: "thin" }}>
        {alerts.map((a) => (
          <ResolvingCard key={a.condition_id} alert={a} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ResolvingSoonStrip.jsx
git commit -m "feat: add ResolvingSoonStrip component with live countdown timers"
```

---

## Task 17: Frontend — ThesisCard Component

**Files:**
- Create: `frontend/src/components/ThesisCard.jsx`

- [ ] **Step 1: Create ThesisCard.jsx**

```jsx
"use client";

import WalletBadge from "./WalletBadge";
import ShareButton from "./ShareButton";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export default function ThesisCard({ thesis }) {
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div
      className="rounded-xl p-4 mb-3 animate-fade-up"
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
        borderLeftWidth: 4,
        borderLeftColor: "#8b5cf6",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider font-bold" style={{ color: "#8b5cf6" }}>
            Cross-Market Thesis
          </p>
          <h3 className="text-base font-bold mt-0.5" style={{ color: "var(--text-primary)" }}>
            &ldquo;{thesis.thesis_headline || "Multi-market position"}&rdquo;
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {thesis.markets?.length || 0} markets · {usdFmt.format(thesis.total_usd)} total
          </p>
        </div>
        <WalletBadge
          wallet={thesis.wallet}
          winRate={thesis.win_rate}
          totalPnl={thesis.total_pnl}
          totalInvested={thesis.total_invested}
          compact
        />
      </div>

      {/* Market list */}
      <div className="flex flex-col gap-1.5 mb-3">
        {(thesis.markets || []).map((m, i) => (
          <div
            key={m.condition_id || i}
            className="flex items-center justify-between rounded-md px-3 py-2 text-xs"
            style={{ background: "var(--surface-1)" }}
          >
            <span className="truncate mr-2" style={{ color: "var(--text-primary)", maxWidth: "60%" }}>
              {m.market_title}
            </span>
            <span style={{ color: "var(--accent)", fontFamily: "var(--font-display)", whiteSpace: "nowrap" }}>
              {usdFmt.format(m.usd_value)} @ {Math.round(m.entry_price * 100)}¢
            </span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <ShareButton url={`${SITE_URL}/thesis/${thesis.id}`} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ThesisCard.jsx
git commit -m "feat: add ThesisCard component for cross-market thesis display"
```

---

## Task 18: Frontend — ResolvedSection Component

**Files:**
- Create: `frontend/src/components/ResolvedSection.jsx`

- [ ] **Step 1: Create ResolvedSection.jsx**

```jsx
"use client";

import { useState, useEffect } from "react";
import { fetchResolved } from "../lib/api";

export default function ResolvedSection() {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetchResolved(24).then(setData).catch(() => {});
  }, []);

  if (!data || !data.outcomes || data.outcomes.length === 0) return null;

  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div className="mt-6 mb-4">
      {/* Header with aggregate stats */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs mb-3 w-full"
        style={{ color: "var(--text-muted)" }}
      >
        <span className="uppercase tracking-wider" style={{ fontFamily: "var(--font-display)" }}>
          Recently Resolved ({data.outcomes.length})
        </span>
        {data.win_rate_7d != null && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold"
            style={{ background: "rgba(0,194,106,0.12)", color: "var(--accent)" }}>
            {Math.round(data.win_rate_7d * 100)}% win rate this week ({data.wins_7d}/{data.total_7d})
          </span>
        )}
        <span className="ml-auto">{expanded ? "▼" : "▶"}</span>
      </button>

      {expanded && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {data.outcomes.map((o) => (
            <div
              key={o.id}
              className="rounded-lg px-4 py-3"
              style={{
                background: "var(--surface-1)",
                borderLeft: `3px solid ${o.won ? "var(--bullish)" : "var(--bearish)"}`,
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium truncate" style={{ color: "var(--text-primary)", maxWidth: "70%" }}>
                  {o.market_title}
                </span>
                <span className="text-xs font-bold" style={{ color: o.won ? "var(--bullish)" : "var(--bearish)" }}>
                  {o.won ? "✅ WIN" : "❌ LOSS"}
                </span>
              </div>
              <p className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
                {o.entry_price != null && `Entry ${Math.round(o.entry_price * 100)}¢`}
                {o.resolution_price != null && ` → ${Math.round(o.resolution_price * 100)}¢`}
                {o.pnl_usd != null && ` (${o.pnl_usd >= 0 ? "+" : ""}${usdFmt.format(o.pnl_usd)})`}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ResolvedSection.jsx
git commit -m "feat: add ResolvedSection component with outcome tracking and aggregate stats"
```

---

## Task 19: Frontend — Integrate All Sections into Homepage

**Files:**
- Modify: `frontend/src/app/page.jsx`
- Modify: `frontend/src/app/home-client.jsx`
- Modify: `frontend/src/components/AlertRow.jsx`

- [ ] **Step 1: Update page.jsx to fetch theses server-side**

In `page.jsx`, update `getHomeData()` to also fetch theses:

```javascript
async function getHomeData() {
  try {
    const [marketsRes, tagsRes, thesesRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/theses?page=1&per_page=5`, { next: { revalidate: 60 } }),
    ]);
    const markets = marketsRes.ok ? await marketsRes.json() : { markets: [], total: 0 };
    const tags = tagsRes.ok ? await tagsRes.json() : [];
    const theses = thesesRes.ok ? await thesesRes.json() : { theses: [] };
    return {
      markets: markets.markets || [],
      total: markets.total || 0,
      tags,
      theses: theses.theses || [],
    };
  } catch {
    return { markets: [], total: 0, tags: [], theses: [] };
  }
}
```

Pass `initialTheses={data.theses}` to `HomeClient`.

- [ ] **Step 2: Update home-client.jsx layout**

Add imports at top:

```javascript
import HeroSpotlight from "../components/HeroSpotlight";
import ResolvingSoonStrip from "../components/ResolvingSoonStrip";
import ThesisCard from "../components/ThesisCard";
import ResolvedSection from "../components/ResolvedSection";
```

Add `initialTheses` to the component props. Add theses state:

```javascript
const [theses] = useState(initialTheses || []);
```

Update the JSX layout to insert new sections in order:

1. After stats bar, before Ticker: `<HeroSpotlight />`
2. After Ticker, before Filters: `<ResolvingSoonStrip />`
3. Pass `theses` to `AlertList` (or render thesis cards interspersed)
4. After AlertList, before Pagination: `<ResolvedSection />`

For thesis card interspersion in the feed, update the `AlertList` rendering section. After every 4th market card, insert a `ThesisCard` if available:

```javascript
{/* Alert feed with interspersed thesis cards */}
{markets.map((market, i) => (
  <Fragment key={market.condition_id || i}>
    {/* Existing market/alert card rendering */}
    {/* ... */}

    {/* Insert thesis card after every 4th item */}
    {(i + 1) % 4 === 0 && theses[Math.floor(i / 4)] && (
      <ThesisCard thesis={theses[Math.floor(i / 4)]} />
    )}
  </Fragment>
))}
```

- [ ] **Step 3: Update AlertRow.jsx with WalletBadge and ShareButton**

At the top of `AlertRow.jsx`, add imports:

```javascript
import WalletBadge from "./WalletBadge";
import ShareButton from "./ShareButton";
```

In the AlertRow component, replace the existing win rate display line (around line 136 where `compactLabel` is built) with a `WalletBadge`:

Find the section that displays `{alert.win_rate}% win rate · +${alert.total_pnl}` and replace with:

```jsx
<WalletBadge
  wallet={alert.wallet}
  winRate={alert.win_rate}
  totalPnl={alert.total_pnl}
  totalInvested={alert.total_invested}
  compact
/>
```

Add `ShareButton` next to the "Copy trade" button in the detail section (around line 260):

```jsx
<ShareButton url={`${process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com"}/alert/${alert.id}`} compact />
```

- [ ] **Step 4: Verify the page renders**

Run: `cd frontend && npm run dev`

Open http://localhost:3000 and verify:
- Hero spotlight appears below stats bar (or is hidden if no data)
- Resolving soon strip appears below ticker (or is hidden)
- Alert cards show wallet badges instead of plain win rate text
- Share buttons appear on alert detail cards
- Thesis cards appear interspersed in the feed (if thesis data exists)
- Resolved section appears at bottom with toggle

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/page.jsx frontend/src/app/home-client.jsx frontend/src/components/AlertRow.jsx
git commit -m "feat: integrate all story-driven sections into homepage layout"
```

---

## Task 20: Frontend — OG Image Generation Route

**Files:**
- Create: `frontend/src/app/api/og/[alertId]/route.jsx`

- [ ] **Step 1: Install @vercel/og (if not already available)**

Run: `cd frontend && npm install @vercel/og`

Note: Next.js 15 may have `ImageResponse` built in via `next/og`. Check first:

```bash
cd frontend && grep -r "ImageResponse" node_modules/next/dist/server/web/spec-extension/ 2>/dev/null | head -1
```

If found, use `import { ImageResponse } from "next/og"` instead of `@vercel/og`.

- [ ] **Step 2: Create OG image route**

```jsx
import { ImageResponse } from "next/og";

export const runtime = "edge";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request, { params }) {
  const { alertId } = await params;

  let alert;
  try {
    const res = await fetch(`${API_URL}/api/alerts/${alertId}`);
    if (!res.ok) return new Response("Not found", { status: 404 });
    alert = await res.json();
  } catch {
    return new Response("Error fetching alert", { status: 500 });
  }

  const winPct = alert.win_rate != null ? `${Math.round(alert.win_rate * 100)}%` : null;
  const pnl = alert.total_pnl != null ? `$${Math.round(alert.total_pnl).toLocaleString()}` : null;
  const amount = `$${Math.round(alert.total_usd || 0).toLocaleString()}`;
  const copyAction = alert.llm_copy_action || {};
  const entryPct = copyAction.entry_price ? `${Math.round(copyAction.entry_price * 100)}¢` : "";
  const betLine = copyAction.outcome
    ? `${amount} on ${copyAction.outcome} at ${entryPct}`
    : amount;

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          padding: "48px",
          background: "linear-gradient(135deg, #060a12 0%, #0c1120 50%, #162030 100%)",
          color: "#e8ecf4",
          fontFamily: "monospace",
        }}
      >
        {/* Logo bar */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
          <div style={{ width: "32px", height: "32px", background: "#00c26a", borderRadius: "8px" }} />
          <span style={{ fontSize: "16px", color: "#8b91a3" }}>PolySpotter · Follow the smart money</span>
        </div>

        {/* Market title */}
        <div style={{ fontSize: "32px", fontWeight: "bold", marginBottom: "12px", lineHeight: 1.2 }}>
          {alert.market_title || "Unknown Market"}
        </div>

        {/* Bet line */}
        <div style={{ fontSize: "40px", fontWeight: "bold", color: "#00c26a", marginBottom: "24px" }}>
          {betLine}
        </div>

        {/* Stats row */}
        <div style={{ display: "flex", gap: "32px", fontSize: "18px", color: "#8b91a3" }}>
          {winPct && <span>{winPct} win rate</span>}
          {pnl && <span>{pnl} P&L</span>}
        </div>

        {/* Win rate bar */}
        {alert.win_rate != null && (
          <div style={{ marginTop: "24px", display: "flex", flexDirection: "column", gap: "4px" }}>
            <div style={{ width: "100%", height: "8px", background: "#1a2535", borderRadius: "4px", overflow: "hidden" }}>
              <div style={{ width: `${Math.round(alert.win_rate * 100)}%`, height: "100%", background: "linear-gradient(90deg, #00c26a, #00e87b)", borderRadius: "4px" }} />
            </div>
          </div>
        )}

        {/* Footer */}
        <div style={{ marginTop: "auto", fontSize: "14px", color: "#5a6073" }}>
          polyspotter.com
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    }
  );
}
```

- [ ] **Step 3: Verify OG image renders**

Run: `cd frontend && npm run dev`

Open `http://localhost:3000/api/og/1` in browser (replace 1 with a valid alert ID). Should render a PNG image card.

- [ ] **Step 4: Update alert detail page meta tags**

In `frontend/src/app/market/[id]/page.jsx`, update the `generateMetadata` function to include OG image:

```javascript
export async function generateMetadata({ params }) {
  // ... existing metadata generation ...
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  return {
    // ... existing fields ...
    openGraph: {
      // ... existing fields ...
      images: alertId ? [`${siteUrl}/api/og/${alertId}`] : [],
    },
    twitter: {
      card: "summary_large_image",
      // ... existing fields ...
    },
  };
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/og/[alertId]/route.jsx frontend/src/app/market/[id]/page.jsx
git commit -m "feat: add OG image generation route and meta tags for social sharing"
```

---

## Task 21: Frontend — Wallet Profile Page

**Files:**
- Create: `frontend/src/app/wallet/[address]/page.jsx`
- Create: `frontend/src/app/wallet/[address]/wallet-page-client.jsx`

- [ ] **Step 1: Create server component**

```jsx
import { fetchWalletProfile } from "../../../lib/api";
import WalletPageClient from "./wallet-page-client";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getWalletData(address) {
  try {
    const res = await fetch(`${API_URL}/api/wallets/${address}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { address } = await params;
  return { title: `Wallet ${address.slice(0, 8)}... | PolySpotter` };
}

export default async function WalletPage({ params }) {
  const { address } = await params;
  const data = await getWalletData(address);

  if (!data) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12 text-center" style={{ color: "var(--text-muted)" }}>
        Wallet not found
      </div>
    );
  }

  return <WalletPageClient wallet={data} address={address} />;
}
```

- [ ] **Step 2: Create client component**

```jsx
"use client";

import WalletBadge from "../../../components/WalletBadge";
import { computeTier } from "../../../lib/tiers";
import { walletPseudonym } from "../../../lib/pseudonym";
import Link from "next/link";

export default function WalletPageClient({ wallet, address }) {
  const tier = computeTier(wallet.win_rate, wallet.total_invested);
  const name = walletPseudonym(address, tier);
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  const stats = [
    { label: "P&L", value: wallet.total_pnl != null ? usdFmt.format(wallet.total_pnl) : "—", color: wallet.total_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" },
    { label: "Win Rate", value: wallet.win_rate != null ? `${Math.round(wallet.win_rate * 100)}%` : "—" },
    { label: "Streak", value: wallet.current_streak ? `🔥 ${wallet.current_streak}W` : "—", color: "var(--warning)" },
    { label: "Markets", value: wallet.total_positions || 0 },
    { label: "W/L", value: `${wallet.wins || 0}/${wallet.losses || 0}` },
    { label: "Flagged", value: `${wallet.times_flagged || 0}x` },
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <WalletBadge wallet={address} winRate={wallet.win_rate} totalPnl={wallet.total_pnl} totalInvested={wallet.total_invested} />
        <p className="text-xs mt-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
          {address}
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-8">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg p-3 text-center" style={{ background: "var(--surface-1)" }}>
            <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{s.label}</p>
            <p className="text-sm font-bold mt-0.5" style={{ color: s.color || "var(--text-primary)", fontFamily: "var(--font-display)" }}>
              {s.value}
            </p>
          </div>
        ))}
      </div>

      {/* Recent alerts */}
      {wallet.recent_alerts?.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Recent Alerts
          </h3>
          <div className="flex flex-col gap-2">
            {wallet.recent_alerts.map((a) => (
              <Link key={a.id} href={`/market/${a.condition_id?.slice(0, 7) || a.id}`}
                className="flex items-center justify-between rounded-lg px-4 py-3"
                style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{a.market_title}</p>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>{a.llm_headline}</p>
                </div>
                <span className="text-xs font-bold" style={{ color: "var(--accent)", fontFamily: "var(--font-display)" }}>
                  {usdFmt.format(a.total_usd)}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Update WalletBadge to link to wallet page**

In `WalletBadge.jsx`, wrap the badge in a `Link`:

```jsx
import Link from "next/link";

// Wrap the outer div with:
<Link href={`/wallet/${wallet}`} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
  {/* ... existing badge content ... */}
</Link>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/wallet frontend/src/components/WalletBadge.jsx
git commit -m "feat: add wallet profile page and link wallet badges"
```

---

## Task 22: Final Verification

- [ ] **Step 1: Run backend tests**

Run: `cd backend && python -m pytest test_new_endpoints.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/bhavya/git/polybot && python -m pytest`
Expected: ALL PASS (no regressions)

- [ ] **Step 3: Run frontend dev server and visually verify**

Run: `cd frontend && npm run dev`

Check:
- Homepage loads with all new sections
- Hero spotlight renders or gracefully hides
- Resolving soon strip shows countdown timers
- Alert cards have wallet badges
- Share button copies URL to clipboard
- Thesis cards appear in feed (if data exists)
- Resolved section toggles open/closed
- Wallet badge links to wallet profile page
- OG image route renders at `/api/og/{alertId}`

- [ ] **Step 4: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: address any issues found during final verification"
```
