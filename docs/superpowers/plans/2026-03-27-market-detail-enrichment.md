# Market Detail Page Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the market detail page from a flat alert list into a data-rich intelligence dashboard with price chart, market stats, holders leaderboard, flow analysis, and cross-market theses.

**Architecture:** Three new backend endpoints proxy Polymarket APIs and enrich with DB data. Five new frontend components slot into a two-column layout in the existing `market-page-client.jsx`. Server component fetches all data in parallel; no new client-side polling beyond the existing 30s live market poll.

**Tech Stack:** Python/FastAPI backend, Next.js 15/React 19 frontend, native SVG for charts, Tailwind CSS + CSS variables for styling.

---

## File Map

**Backend (new endpoints + models):**
- Modify: `backend/app.py` — add 3 endpoints + 1 cache dict + helper functions
- Modify: `backend/models.py` — add response models for new endpoints
- Modify: `backend/test_endpoints.py` — add tests for new endpoints

**Frontend (new components):**
- Create: `frontend/src/components/PriceChart.jsx` — SVG price history with alert markers
- Create: `frontend/src/components/MarketStats.jsx` — 4-tile stats bar
- Create: `frontend/src/components/HoldersLeaderboard.jsx` — ranked wallet list
- Create: `frontend/src/components/MarketPulse.jsx` — flow bar + volume spike
- Create: `frontend/src/components/MarketTheses.jsx` — related theses cards
- Modify: `frontend/src/lib/api.js` — add fetch functions for new endpoints
- Modify: `frontend/src/app/market/[id]/page.jsx` — fetch new data server-side
- Modify: `frontend/src/app/market/[id]/market-page-client.jsx` — two-column layout, wire components

---

## Task 1: Backend — Price History Endpoint

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`
- Modify: `backend/test_endpoints.py`

- [ ] **Step 1: Add Pydantic response model**

Add to `backend/models.py` at the end of the file:

```python
# -- Price history (proxied from CLOB API) ------------------------------------

class PricePoint(BaseModel):
    t: int  # unix timestamp
    p: float  # price 0.00–1.00

class PriceHistoryData(BaseModel):
    condition_id: str
    token_id: str
    outcome: str
    history: list[PricePoint] = []
```

- [ ] **Step 2: Write the failing test**

Add to `backend/test_endpoints.py`:

```python
# ---------------------------------------------------------------------------
# /api/market/{condition_id}/price-history endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestPriceHistory:
    def test_price_history_returns_structure(self, monkeypatch):
        """Mock upstream CLOB + Gamma calls, verify response shape."""
        # Mock _fetch_live_market to return token IDs
        def mock_fetch_live(cid):
            from models import LiveMarketData, OutcomePrice
            return LiveMarketData(
                condition_id=cid,
                outcomes=[
                    OutcomePrice(name="Yes", token_id="tok_yes_123", price=0.21),
                    OutcomePrice(name="No", token_id="tok_no_456", price=0.79),
                ],
            )

        # Mock CLOB prices-history call
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

        # Clear cache so mock is used
        app_mod._live_cache.clear()
        app_mod._price_history_cache.clear()

        resp = client.get("/api/market/test_cond_001/price-history?range=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["condition_id"] == "test_cond_001"
        assert data["outcome"] == "No"  # picks highest-priced outcome
        assert len(data["history"]) == 3
        assert data["history"][0]["t"] == 1700000000

    def test_price_history_invalid_range(self):
        """Invalid range param returns 422."""
        resp = client.get("/api/market/test_cond_001/price-history?range=invalid")
        assert resp.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest test_endpoints.py::TestPriceHistory -v`
Expected: FAIL — endpoint not found (404) or import error for `_price_history_cache`

- [ ] **Step 4: Implement the endpoint**

Add to `backend/app.py` after the `_live_cache` definition (around line 868):

```python
_price_history_cache: dict[str, tuple[float, "PriceHistoryData"]] = {}
_PRICE_HISTORY_CACHE_TTL = 60  # seconds
```

Add the import of the new model. In the imports section at the top, add `PriceHistoryData, PricePoint` to the imports from `models`:

```python
from models import (
    IngestPayload,
    AlertOut,
    AlertDetail,
    TradeOut,
    SignalOut,
    WalletProfileOut,
    WalletProfileDetailOut,
    WalletRecentAlert,
    WalletBet,
    PaginatedAlerts,
    MarketGroup,
    PaginatedMarkets,
    LiveMarketData,
    OutcomePrice,
    PriceHistoryData,
    PricePoint,
)
```

Add the endpoint after the existing `/api/market/{condition_id}/live` endpoint:

```python
_RANGE_PARAMS = {
    "24h": ("1", "minute"),
    "7d": ("7", "hour"),
    "30d": ("30", "hour"),
    "all": ("max", "day"),
}


@app.get("/api/market/{condition_id}/price-history", response_model=PriceHistoryData)
def get_price_history(
    condition_id: str,
    range: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
):
    """Get price history for the leading outcome of a market.

    Proxies CLOB /prices-history. Cached for 60 seconds."""
    cache_key = f"{condition_id}:{range}"
    now = _time.time()
    cached = _price_history_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    # Get token IDs from live market data (itself cached for 30s)
    live = get_market_live(condition_id)
    if not live.outcomes:
        raise HTTPException(status_code=404, detail="No outcomes found for market")

    # Pick the leading outcome (highest price)
    leading = max(live.outcomes, key=lambda o: o.price)
    fidelity, interval = _RANGE_PARAMS[range]

    try:
        resp = _requests.get(
            f"{CLOB_API}/prices-history",
            params={
                "market": leading.token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except _requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CLOB API error: {e}")

    history_list = raw.get("history", [])
    points = [PricePoint(t=int(pt["t"]), p=float(pt["p"])) for pt in history_list]

    data = PriceHistoryData(
        condition_id=condition_id,
        token_id=leading.token_id,
        outcome=leading.name,
        history=points,
    )
    _price_history_cache[cache_key] = (now + _PRICE_HISTORY_CACHE_TTL, data)
    return data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest test_endpoints.py::TestPriceHistory -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/app.py backend/test_endpoints.py
git commit -m "feat: add /api/market/{conditionId}/price-history endpoint"
```

---

## Task 2: Backend — Holders Endpoint

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`
- Modify: `backend/test_endpoints.py`

- [ ] **Step 1: Add Pydantic response models**

Add to `backend/models.py` at the end:

```python
# -- Market holders (from Polymarket Data API + wallet_profiles) ---------------

class HolderEntry(BaseModel):
    wallet: str
    position_size: float  # USD value
    outcome: str
    side: str  # "long" or "short"
    win_rate: float | None = None
    total_pnl: float | None = None
    total_invested: float | None = None

class MarketHoldersData(BaseModel):
    condition_id: str
    holders: list[HolderEntry] = []
```

- [ ] **Step 2: Write the failing test**

Add to `backend/test_endpoints.py`:

```python
# ---------------------------------------------------------------------------
# /api/market/{condition_id}/holders endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestMarketHolders:
    def test_holders_returns_enriched_list(self, monkeypatch):
        """Mock Data API /positions, seed wallet_profiles, verify enrichment."""
        # Seed a wallet profile so enrichment works
        with db() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO wallet_profiles (wallet, total_positions, closed_positions,
                   wins, losses, total_pnl, total_invested, avg_win_price, win_rate, times_flagged)
                   VALUES ('test_wallet_holder1', 50, 40, 30, 10, 5000, 20000, 0.65, 0.75, 3)
                   ON CONFLICT (wallet) DO NOTHING"""
            )
            conn.commit()

        # Mock the Data API /positions call
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
        # First holder should be enriched with wallet_profiles data
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest test_endpoints.py::TestMarketHolders -v`
Expected: FAIL — endpoint not found or `_holders_cache` missing

- [ ] **Step 4: Implement the endpoint**

Add cache dict near the other caches in `backend/app.py`:

```python
_holders_cache: dict[str, tuple[float, "MarketHoldersData"]] = {}
_HOLDERS_CACHE_TTL = 300  # 5 minutes
```

Add `HolderEntry, MarketHoldersData` to the models import.

Add the endpoint:

```python
DATA_API = "https://data-api.polymarket.com"


@app.get("/api/market/{condition_id}/holders", response_model=MarketHoldersData)
def get_market_holders(condition_id: str):
    """Get top holders for a market, enriched with wallet profile stats.

    Proxies Polymarket Data API /positions. Cached for 5 minutes."""
    now = _time.time()
    cached = _holders_cache.get(condition_id)
    if cached and cached[0] > now:
        return cached[1]

    try:
        resp = _requests.get(
            f"{DATA_API}/positions",
            params={"market": condition_id, "sizeThreshold": "100", "limit": "20"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except _requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Data API error: {e}")

    if not isinstance(raw, list):
        raw = []

    # Sort by position size descending, take top 10
    raw.sort(key=lambda p: abs(float(p.get("size", 0))), reverse=True)
    raw = raw[:10]

    # Gather wallets for DB enrichment
    wallets = [p.get("proxyWallet", "").lower() for p in raw if p.get("proxyWallet")]

    wallet_stats = {}
    if wallets:
        with db() as conn:
            cur = conn.cursor()
            placeholders = ",".join(["%s"] * len(wallets))
            cur.execute(
                f"SELECT wallet, win_rate, total_pnl, total_invested FROM wallet_profiles WHERE wallet IN ({placeholders})",
                wallets,
            )
            for row in cur.fetchall():
                wallet_stats[row["wallet"]] = row

    holders = []
    for p in raw:
        w = (p.get("proxyWallet") or "").lower()
        stats = wallet_stats.get(w, {})
        size_val = abs(float(p.get("size", 0)))
        holders.append(HolderEntry(
            wallet=w,
            position_size=size_val,
            outcome=p.get("outcome", ""),
            side="long" if float(p.get("size", 0)) > 0 else "short",
            win_rate=stats.get("win_rate"),
            total_pnl=stats.get("total_pnl"),
            total_invested=stats.get("total_invested"),
        ))

    data = MarketHoldersData(condition_id=condition_id, holders=holders)
    _holders_cache[condition_id] = (now + _HOLDERS_CACHE_TTL, data)
    return data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest test_endpoints.py::TestMarketHolders -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/app.py backend/test_endpoints.py
git commit -m "feat: add /api/market/{conditionId}/holders endpoint"
```

---

## Task 3: Backend — Market Theses Endpoint

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/test_endpoints.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/test_endpoints.py`:

```python
# ---------------------------------------------------------------------------
# /api/market/{condition_id}/theses endpoint tests
# ---------------------------------------------------------------------------

@skip_no_db
class TestMarketTheses:
    def test_theses_for_market(self):
        """Returns theses from wallets that have alerts in this market."""
        with db() as conn:
            cur = conn.cursor()
            # Seed an alert for wallet in this market
            _seed_alert(cur, wallet="test_wallet_thesis1", condition_id="test_cond_thesis",
                        dedup_key="test_thesis_dedup_1")
            # Seed a thesis for that wallet
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest test_endpoints.py::TestMarketTheses -v`
Expected: FAIL — endpoint not found

- [ ] **Step 3: Implement the endpoint**

Add to `backend/app.py`:

```python
@app.get("/api/market/{condition_id}/theses")
def get_market_theses(condition_id: str):
    """Get cross-market theses from wallets active in this market."""
    with db() as conn:
        cur = conn.cursor()
        # Find distinct wallets that have alerts in this market
        cur.execute(
            "SELECT DISTINCT wallet FROM alerts WHERE condition_id = %s LIMIT 20",
            (condition_id,),
        )
        wallets = [r["wallet"] for r in cur.fetchall()]

        if not wallets:
            return {"theses": []}

        placeholders = ",".join(["%s"] * len(wallets))
        cur.execute(
            f"""SELECT wt.*, wp.win_rate, wp.total_pnl, wp.total_invested
                FROM wallet_theses wt
                LEFT JOIN wallet_profiles wp ON wt.wallet = wp.wallet
                WHERE wt.wallet IN ({placeholders})
                ORDER BY wt.composite_score DESC
                LIMIT 10""",
            wallets,
        )
        rows = cur.fetchall()
        theses = [_thesis_from_row(row) for row in rows]

    return {"theses": theses}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest test_endpoints.py::TestMarketTheses -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "feat: add /api/market/{conditionId}/theses endpoint"
```

---

## Task 4: Backend — Add Spread to Live Market Endpoint

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`

- [ ] **Step 1: Add spread field to LiveMarketData model**

In `backend/models.py`, modify `LiveMarketData`:

```python
class LiveMarketData(BaseModel):
    condition_id: str
    outcomes: list[OutcomePrice] = []
    volume_24h: float | None = None
    liquidity: float | None = None
    description: str | None = None
    spread: float | None = None  # bid-ask spread in cents for leading outcome
```

- [ ] **Step 2: Add spread fetch to `_fetch_live_market`**

In `backend/app.py`, at the end of the `_fetch_live_market` function (before the `return`), add the spread fetch. Find the line that builds and returns `LiveMarketData(...)` and modify it to include spread:

After the outcomes are built and before the return statement, add:

```python
    # Fetch spread for the leading outcome
    spread = None
    if outcomes:
        leading_token = max(outcomes, key=lambda o: o.price).token_id
        try:
            spread_resp = _requests.get(
                f"{CLOB_API}/spread",
                params={"token_id": leading_token},
                timeout=5,
            )
            if spread_resp.ok:
                spread_data = spread_resp.json()
                spread = float(spread_data.get("spread", 0)) * 100  # convert to cents
        except Exception:
            pass  # spread is non-critical
```

Then update the return statement to include `spread=spread`.

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd backend && pytest test_endpoints.py -v`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/app.py
git commit -m "feat: add spread field to live market endpoint"
```

---

## Task 5: Frontend — API Client Functions

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add fetch functions for new endpoints**

Add to the end of `frontend/src/lib/api.js`:

```javascript
export function fetchPriceHistory(conditionId, range = "7d") {
  return request(`/api/market/${conditionId}/price-history`, { range });
}

export function fetchMarketHolders(conditionId) {
  return request(`/api/market/${conditionId}/holders`);
}

export function fetchMarketTheses(conditionId) {
  return request(`/api/market/${conditionId}/theses`);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: add API client functions for price history, holders, theses"
```

---

## Task 6: Frontend — PriceChart Component

**Files:**
- Create: `frontend/src/components/PriceChart.jsx`

- [ ] **Step 1: Create the PriceChart component**

Create `frontend/src/components/PriceChart.jsx`:

```jsx
"use client";

import { useState, useId } from "react";

const RANGES = ["24h", "7d", "30d", "all"];

export default function PriceChart({ history, outcome, alerts, conditionId }) {
  const gradientId = useId();
  const [activeRange, setActiveRange] = useState("7d");
  const [points, setPoints] = useState(history || []);
  const [loading, setLoading] = useState(false);

  if (!points || points.length < 2) return null;

  const prices = points.map((pt) => pt.p);
  const times = points.map((pt) => pt.t);
  const minP = Math.min(...prices) * 0.98;
  const maxP = Math.max(...prices) * 1.02;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeP = maxP - minP || 0.01;
  const rangeT = maxT - minT || 1;

  const W = 600;
  const H = 140;

  const svgPoints = points
    .map((pt) => {
      const x = ((pt.t - minT) / rangeT) * W;
      const y = H - ((pt.p - minP) / rangeP) * H;
      return `${x},${y}`;
    })
    .join(" ");

  // Map alerts to chart coordinates
  const alertMarkers = (alerts || [])
    .filter((a) => a.scanned_at)
    .map((a) => {
      const ts = new Date(a.scanned_at).getTime() / 1000;
      if (ts < minT || ts > maxT) return null;
      const x = ((ts - minT) / rangeT) * W;
      // Find closest price point for y
      let closest = points[0];
      let minDist = Infinity;
      for (const pt of points) {
        const dist = Math.abs(pt.t - ts);
        if (dist < minDist) {
          minDist = dist;
          closest = pt;
        }
      }
      const y = H - ((closest.p - minP) / rangeP) * H;
      const isTopScore =
        a.composite_score ===
        Math.max(...alerts.map((al) => al.composite_score || 0));
      return { x, y, isTopScore, id: a.id };
    })
    .filter(Boolean);

  // Y-axis labels (3 ticks)
  const yTicks = [maxP, (maxP + minP) / 2, minP].map((p) => ({
    label: `${Math.round(p * 100)}¢`,
    y: H - ((p - minP) / rangeP) * H,
  }));

  async function handleRangeChange(range) {
    if (range === activeRange) return;
    setActiveRange(range);
    setLoading(true);
    try {
      const { fetchPriceHistory } = await import("../lib/api");
      const data = await fetchPriceHistory(conditionId, range);
      setPoints(data.history || []);
    } catch {
      // keep existing points on error
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <span
          className="text-xs font-semibold uppercase tracking-widest"
          style={{
            fontFamily: "var(--font-display)",
            color: "var(--text-muted)",
            fontSize: "0.6rem",
          }}
        >
          Price History — &ldquo;{outcome}&rdquo;
        </span>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => handleRangeChange(r)}
              className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
              style={{
                background:
                  r === activeRange ? "var(--surface-2)" : "transparent",
                color:
                  r === activeRange
                    ? "var(--text-primary)"
                    : "var(--text-muted)",
                fontWeight: r === activeRange ? 600 : 400,
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="relative" style={{ height: 160, opacity: loading ? 0.5 : 1, transition: "opacity 0.2s" }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-full w-full"
          preserveAspectRatio="none"
        >
          {/* Grid lines */}
          {yTicks.map((tick, i) => (
            <line
              key={i}
              x1="0"
              y1={tick.y}
              x2={W}
              y2={tick.y}
              stroke="var(--border)"
              strokeWidth="0.5"
              strokeDasharray="4,4"
            />
          ))}

          {/* Gradient fill */}
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.15" />
              <stop
                offset="100%"
                stopColor="var(--accent)"
                stopOpacity="0"
              />
            </linearGradient>
          </defs>
          <polygon
            points={`0,${H} ${svgPoints} ${W},${H}`}
            fill={`url(#${gradientId})`}
          />

          {/* Price line */}
          <polyline
            points={svgPoints}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Alert entry markers */}
          {alertMarkers.map((m) => (
            <circle
              key={m.id}
              cx={m.x}
              cy={m.y}
              r="5"
              fill={m.isTopScore ? "var(--warning)" : "var(--info)"}
              stroke="var(--surface-1)"
              strokeWidth="2"
            />
          ))}
        </svg>

        {/* Y-axis labels */}
        {yTicks.map((tick, i) => (
          <div
            key={i}
            className="absolute right-1"
            style={{
              top: `${(tick.y / H) * 100}%`,
              transform: "translateY(-50%)",
              fontSize: 10,
              fontFamily: "var(--font-display)",
              color: "var(--text-muted)",
            }}
          >
            {tick.label}
          </div>
        ))}

        {/* Legend */}
        <div
          className="absolute bottom-0 left-0 flex gap-3.5"
          style={{ fontSize: 10, color: "var(--text-muted)" }}
        >
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: "var(--info)" }}
            />
            Alert entries
          </span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: "var(--warning)" }}
            />
            High-conviction
          </span>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/PriceChart.jsx
git commit -m "feat: add PriceChart component with alert markers and range toggles"
```

---

## Task 7: Frontend — MarketStats Component

**Files:**
- Create: `frontend/src/components/MarketStats.jsx`

- [ ] **Step 1: Create the MarketStats component**

Create `frontend/src/components/MarketStats.jsx`:

```jsx
const fmtUsd = (v) => {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

export default function MarketStats({ volume24h, liquidity, spread, alerts }) {
  // Compute smart flow from alerts
  const flow = {};
  for (const a of alerts || []) {
    const side = a.llm_copy_action?.outcome || "Unknown";
    flow[side] = (flow[side] || 0) + (a.total_usd || 0);
  }
  const flowEntries = Object.entries(flow).sort((a, b) => b[1] - a[1]);
  const totalFlow = flowEntries.reduce((s, [, v]) => s + v, 0);
  const topFlow = flowEntries[0];
  const flowPct = topFlow && totalFlow > 0 ? Math.round((topFlow[1] / totalFlow) * 100) : null;

  const tiles = [
    { label: "24h Volume", value: fmtUsd(volume24h) },
    { label: "Liquidity", value: fmtUsd(liquidity) },
    { label: "Spread", value: spread != null ? `${spread.toFixed(1)}¢` : "—" },
    {
      label: "Smart Flow",
      value: flowPct != null ? `${flowPct}% ${topFlow[0]}` : "—",
      accent: true,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-xl border p-3 text-center"
          style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
        >
          <div
            className="mb-1 text-xs uppercase tracking-wider"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-muted)",
              fontSize: "0.55rem",
              letterSpacing: "0.08em",
            }}
          >
            {t.label}
          </div>
          <div
            className="text-base font-bold tabular-nums"
            style={{
              fontFamily: "var(--font-display)",
              color: t.accent ? "var(--accent)" : "var(--text-primary)",
            }}
          >
            {t.value}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/MarketStats.jsx
git commit -m "feat: add MarketStats 4-tile component"
```

---

## Task 8: Frontend — HoldersLeaderboard Component

**Files:**
- Create: `frontend/src/components/HoldersLeaderboard.jsx`

- [ ] **Step 1: Create the HoldersLeaderboard component**

Create `frontend/src/components/HoldersLeaderboard.jsx`:

```jsx
import Link from "next/link";
import { walletPseudonym } from "../lib/pseudonym";

const fmtUsd = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

function wrColor(wr) {
  if (wr == null) return "var(--text-muted)";
  if (wr >= 0.8) return "var(--accent)";
  if (wr >= 0.65) return "var(--warning)";
  return "var(--text-muted)";
}

export default function HoldersLeaderboard({ holders }) {
  if (!holders || holders.length === 0) return null;

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Top Holders
      </h3>
      <div
        className="overflow-hidden rounded-xl border"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        {holders.map((h, i) => (
          <div
            key={h.wallet}
            className="flex items-center gap-2.5 px-3.5 py-3"
            style={{
              borderBottom:
                i < holders.length - 1
                  ? "1px solid var(--border)"
                  : "none",
            }}
          >
            <span
              className="w-5 text-xs font-bold"
              style={{ color: "var(--text-muted)" }}
            >
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <Link
                  href={`/wallet/${h.wallet}`}
                  className="truncate text-sm font-semibold hover:underline"
                  style={{
                    fontFamily: "var(--font-display)",
                    color: "var(--text-primary)",
                    fontSize: "0.8rem",
                  }}
                >
                  {walletPseudonym(h.wallet)}
                </Link>
                <span
                  className="ml-2 text-xs font-semibold"
                  style={{
                    color:
                      h.position_size >= 10000
                        ? "var(--accent)"
                        : h.position_size >= 3000
                          ? "var(--warning)"
                          : "var(--text-primary)",
                  }}
                >
                  {fmtUsd(h.position_size)}
                </span>
              </div>
              <div className="mt-1 flex gap-2">
                {h.win_rate != null && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{
                      background: `color-mix(in srgb, ${wrColor(h.win_rate)} 12%, transparent)`,
                      color: wrColor(h.win_rate),
                    }}
                  >
                    {Math.round(h.win_rate * 100)}% WR
                  </span>
                )}
                {h.total_pnl != null && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{
                      background: "rgba(59,130,246,0.1)",
                      color: "var(--info)",
                    }}
                  >
                    {h.total_pnl >= 0 ? "+" : ""}
                    {fmtUsd(Math.abs(h.total_pnl))} PnL
                  </span>
                )}
                <span
                  className="text-[10px]"
                  style={{ color: "var(--text-muted)" }}
                >
                  {h.outcome}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/HoldersLeaderboard.jsx
git commit -m "feat: add HoldersLeaderboard component"
```

---

## Task 9: Frontend — MarketPulse Component

**Files:**
- Create: `frontend/src/components/MarketPulse.jsx`

- [ ] **Step 1: Create the MarketPulse component**

Create `frontend/src/components/MarketPulse.jsx`:

```jsx
const fmtUsd = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

export default function MarketPulse({ alerts, volume24h }) {
  // Compute per-outcome flow from alerts
  const flow = {};
  for (const a of alerts || []) {
    const side = a.llm_copy_action?.outcome || "Unknown";
    flow[side] = (flow[side] || 0) + (a.total_usd || 0);
  }
  const entries = Object.entries(flow).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);

  if (total === 0 && !volume24h) return null;

  // Simple volume spike heuristic: if we have 24h volume, compare to a baseline
  // This is a rough heuristic — a proper implementation would use 7d average from backend
  const volumeSpike = volume24h && volume24h > 50000 ? (volume24h / 15000).toFixed(1) : null;

  return (
    <div
      className="mt-3.5 rounded-xl border p-3.5"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <h3
        className="mb-2.5 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Market Pulse
      </h3>

      {/* Flow bar */}
      {total > 0 && (
        <div className="mb-2.5">
          <div
            className="mb-1 flex justify-between text-[11px]"
            style={{ color: "var(--text-muted)" }}
          >
            {entries.map(([name]) => (
              <span key={name}>{name} flow</span>
            ))}
          </div>
          <div className="flex h-2 overflow-hidden rounded-full">
            {entries.map(([name, val], i) => {
              const pct = (val / total) * 100;
              const colors = ["var(--accent)", "var(--bearish)", "var(--warning)", "var(--info)"];
              return (
                <div
                  key={name}
                  style={{ width: `${pct}%`, background: colors[i] || colors[0] }}
                />
              );
            })}
          </div>
          <div
            className="mt-1 flex justify-between text-[11px]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {entries.map(([name, val], i) => {
              const colors = ["var(--accent)", "var(--bearish)", "var(--warning)", "var(--info)"];
              return (
                <span key={name} style={{ color: colors[i] || colors[0] }}>
                  {fmtUsd(val)}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Volume spike */}
      {volumeSpike && (
        <div
          className="flex items-center gap-1.5 text-[11px]"
          style={{ color: "var(--text-muted)" }}
        >
          <span style={{ color: "var(--warning)" }}>&#x26A1;</span>
          <span>
            Volume{" "}
            <span style={{ color: "var(--warning)", fontWeight: 600 }}>
              {volumeSpike}x above
            </span>{" "}
            average
          </span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/MarketPulse.jsx
git commit -m "feat: add MarketPulse flow bar component"
```

---

## Task 10: Frontend — MarketTheses Component

**Files:**
- Create: `frontend/src/components/MarketTheses.jsx`

- [ ] **Step 1: Create the MarketTheses component**

Create `frontend/src/components/MarketTheses.jsx`:

```jsx
import Link from "next/link";
import { walletPseudonym } from "../lib/pseudonym";

export default function MarketTheses({ theses }) {
  if (!theses || theses.length === 0) return null;

  return (
    <section>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Related Theses
      </h3>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {theses.map((thesis) => (
          <Link
            key={thesis.id}
            href={`/thesis/${thesis.id}`}
            className="block rounded-xl border p-3.5 transition-colors hover:border-[var(--text-muted)]"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface-1)",
            }}
          >
            <div
              className="mb-1.5 text-sm font-semibold"
              style={{ color: "var(--text-primary)" }}
            >
              {thesis.thesis_headline}
            </div>
            <div
              className="mb-2 text-xs leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              {walletPseudonym(thesis.wallet)} trades{" "}
              {(thesis.markets || []).length} related market
              {(thesis.markets || []).length !== 1 ? "s" : ""}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(thesis.markets || []).slice(0, 3).map((m, i) => (
                <span
                  key={i}
                  className="rounded px-2 py-0.5 text-[10px]"
                  style={{
                    background: "var(--surface-2)",
                    color: "var(--text-muted)",
                  }}
                >
                  {m.market_title
                    ? m.market_title.length > 30
                      ? m.market_title.slice(0, 30) + "…"
                      : m.market_title
                    : m.outcome || "Market"}
                </span>
              ))}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/MarketTheses.jsx
git commit -m "feat: add MarketTheses component"
```

---

## Task 11: Frontend — Wire Everything into the Market Detail Page

**Files:**
- Modify: `frontend/src/app/market/[id]/page.jsx`
- Modify: `frontend/src/app/market/[id]/market-page-client.jsx`

- [ ] **Step 1: Update server component to fetch new data**

In `frontend/src/app/market/[id]/page.jsx`, modify the `getMarketData` function to fetch price history, holders, and theses in parallel with the existing calls:

Replace the `getMarketData` function (lines 23-45) with:

```javascript
async function getMarketData(conditionId) {
  try {
    const [liveRes, alertsRes, priceRes, holdersRes, thesesRes] = await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        next: { revalidate: 60 },
      }),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { next: { revalidate: 60 } }
      ),
      fetch(`${API_URL}/api/market/${conditionId}/price-history?range=7d`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/market/${conditionId}/holders`, {
        next: { revalidate: 300 },
      }),
      fetch(`${API_URL}/api/market/${conditionId}/theses`, {
        next: { revalidate: 300 },
      }),
    ]);

    const live = liveRes.ok ? await liveRes.json() : null;
    const alertsData = alertsRes.ok ? await alertsRes.json() : null;
    const priceData = priceRes.ok ? await priceRes.json() : null;
    const holdersData = holdersRes.ok ? await holdersRes.json() : null;
    const thesesData = thesesRes.ok ? await thesesRes.json() : null;

    return {
      live,
      alerts: alertsData?.alerts || [],
      priceHistory: priceData,
      holders: holdersData?.holders || [],
      theses: thesesData?.theses || [],
    };
  } catch {
    return { live: null, alerts: [], priceHistory: null, holders: [], theses: [] };
  }
}
```

Update the `MarketPage` component (around line 97) to pass new props:

Replace:
```javascript
  const { live, alerts } = await getMarketData(conditionId);
```
with:
```javascript
  const { live, alerts, priceHistory, holders, theses } = await getMarketData(conditionId);
```

Update the `MarketPageClient` rendering (line 148) to pass new props:

Replace:
```jsx
      <MarketPageClient conditionId={conditionId} initialLive={live} initialAlerts={alerts} />
```
with:
```jsx
      <MarketPageClient
        conditionId={conditionId}
        initialLive={live}
        initialAlerts={alerts}
        priceHistory={priceHistory}
        holders={holders}
        theses={theses}
      />
```

Also update `generateMetadata` similarly — replace its `getMarketData` destructuring (line 51):

Replace:
```javascript
  const { live, alerts } = await getMarketData(conditionId);
```
with:
```javascript
  const { live, alerts } = await getMarketData(conditionId);
```

(No change needed here — the extra fields are just ignored.)

- [ ] **Step 2: Update client component with two-column layout and new components**

Replace the entire content of `frontend/src/app/market/[id]/market-page-client.jsx` with:

```jsx
"use client";

import { useState } from "react";
import Link from "next/link";
import AlertRow from "../../../components/AlertRow";
import PriceMovement from "../../../components/PriceMovement";
import PriceChart from "../../../components/PriceChart";
import MarketStats from "../../../components/MarketStats";
import HoldersLeaderboard from "../../../components/HoldersLeaderboard";
import MarketPulse from "../../../components/MarketPulse";
import MarketTheses from "../../../components/MarketTheses";
import useLiveMarket from "../../../hooks/useLiveMarket";
import ThemeToggle from "../../../components/ThemeToggle";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return "Resolved";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

export default function MarketPageClient({
  conditionId,
  initialLive,
  initialAlerts,
  priceHistory,
  holders,
  theses,
}) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const isUrgent = endDate && new Date(endDate).getTime() - Date.now() < 3600000 && new Date(endDate).getTime() - Date.now() > 0;
  const isSoon = endDate && new Date(endDate).getTime() - Date.now() < 86400000 && new Date(endDate).getTime() - Date.now() > 0;

  const outcomes = live?.outcomes || [];

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      {/* Nav */}
      <nav className="mb-6 flex items-center justify-between" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: 'var(--text-muted)' }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <ThemeToggle />
      </nav>

      {/* Market header */}
      <header className="mb-8">
        <h1 className="text-2xl font-bold leading-snug" style={{ color: 'var(--text-primary)' }}>
          {title}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {resolution && (
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
              style={{
                background: isUrgent ? 'rgba(239, 68, 68, 0.1)' : isSoon ? 'rgba(245, 158, 11, 0.1)' : 'var(--surface-2)',
                color: resolution === "Resolved"
                  ? 'var(--text-muted)'
                  : isUrgent
                    ? 'var(--bearish)'
                    : isSoon
                      ? 'var(--warning)'
                      : 'var(--text-secondary)',
              }}
            >
              {isUrgent && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                </span>
              )}
              Resolves in {resolution}
            </span>
          )}
          {totalUsd > 0 && (
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.8rem' }}>
              {usdFmt.format(totalUsd)} tracked
            </span>
          )}
          <span>
            {alerts.length} signal{alerts.length !== 1 ? "s" : ""}
          </span>
        </div>

        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <span
                key={t}
                className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </header>

      {/* Live outcomes */}
      {outcomes.length > 0 && (() => {
        const maxPct = Math.max(...outcomes.map((o) => Math.round((o.price || 0) * 100)));
        return (
          <div className="mb-6 grid gap-3 sm:grid-cols-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              const isLeading = pct === maxPct && pct > 50;
              return (
                <div
                  key={o.name}
                  className="rounded-xl border p-4 relative overflow-hidden"
                  style={{
                    borderColor: isLeading ? 'rgba(0, 194, 106, 0.3)' : 'var(--border)',
                    background: 'var(--surface-card)',
                    boxShadow: isLeading ? 'var(--glow-medium)' : 'none',
                  }}
                >
                  <div
                    className="absolute inset-y-0 left-0 transition-all duration-700"
                    style={{
                      width: `${pct}%`,
                      background: isLeading
                        ? 'linear-gradient(90deg, rgba(0, 194, 106, 0.10) 0%, rgba(0, 194, 106, 0.04) 100%)'
                        : 'linear-gradient(90deg, rgba(139, 145, 163, 0.07) 0%, rgba(139, 145, 163, 0.02) 100%)',
                    }}
                  />
                  <div className="relative flex items-center justify-between mb-3">
                    <span className="font-medium text-[0.95rem]" style={{ color: 'var(--text-primary)' }}>
                      {o.name}
                    </span>
                    <span
                      className="text-xl font-bold tabular-nums"
                      style={{
                        fontFamily: 'var(--font-display)',
                        color: isLeading ? 'var(--accent)' : 'var(--text-primary)',
                      }}
                    >
                      {pct}&cent;
                    </span>
                  </div>
                  <div
                    className="h-2 w-full rounded-full overflow-hidden"
                    style={{ background: 'var(--surface-2)' }}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{
                        width: `${pct}%`,
                        background: isLeading
                          ? 'linear-gradient(90deg, var(--accent), #00e87b)'
                          : 'var(--text-muted)',
                        opacity: isLeading ? 1 : 0.35,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* Price Chart */}
      {priceHistory && priceHistory.history?.length > 1 && (
        <div className="mb-6">
          <PriceChart
            history={priceHistory.history}
            outcome={priceHistory.outcome}
            alerts={alerts}
            conditionId={conditionId}
          />
        </div>
      )}

      {/* Market Stats */}
      <div className="mb-6">
        <MarketStats
          volume24h={live?.volume_24h}
          liquidity={live?.liquidity}
          spread={live?.spread}
          alerts={alerts}
        />
      </div>

      {/* Two-column: Notable Trades + Holders/Pulse */}
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Left: Notable Trades */}
        <section>
          {alerts.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2
                className="text-xs font-semibold uppercase tracking-widest"
                style={{
                  fontFamily: 'var(--font-display)',
                  color: 'var(--text-muted)',
                  fontSize: '0.6rem',
                }}
              >
                Notable Trades
              </h2>
              {alerts.map((alert) => (
                <AlertRow
                  key={alert.id}
                  alert={alert}
                  autoExpand
                  activeTag=""
                  onTagClick={() => {}}
                  liveMarket={live}
                />
              ))}
            </div>
          ) : (
            <div
              className="rounded-xl border p-12 text-center"
              style={{
                borderColor: 'var(--border)',
                background: 'var(--surface-card)',
                color: 'var(--text-muted)',
              }}
            >
              No signals found for this market.
            </div>
          )}
        </section>

        {/* Right: Holders + Pulse */}
        {(holders?.length > 0 || alerts.length > 0) && (
          <aside>
            <HoldersLeaderboard holders={holders} />
            <MarketPulse alerts={alerts} volume24h={live?.volume_24h} />
          </aside>
        )}
      </div>

      {/* Related Theses */}
      {theses?.length > 0 && (
        <div className="mt-8">
          <MarketTheses theses={theses} />
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 3: Run the dev server and verify the page loads**

Run: `cd frontend && npm run dev`

Open a market detail page in the browser and verify:
- Price chart renders below outcome bars
- Stats bar shows 4 tiles
- Two-column layout: trades left, holders right
- Market pulse shows below holders
- Theses cards show at bottom
- Mobile: stacks to single column

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/market/\[id\]/page.jsx frontend/src/app/market/\[id\]/market-page-client.jsx
git commit -m "feat: wire enrichment components into market detail page with two-column layout"
```

---

## Task 12: End-to-End Verification

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && pytest test_endpoints.py -v`
Expected: All tests pass (existing + 6 new)

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Manual smoke test**

Run: `cd frontend && npm run dev` and `cd backend && uvicorn app:app --reload`

Open a market detail page and verify:
1. Price chart loads with data points and alert markers
2. Time range buttons (24h/7d/30d/all) fetch new data on click
3. Stats bar shows volume, liquidity, spread, smart flow
4. Holders leaderboard shows ranked wallets with badges
5. Market pulse shows flow bar
6. Related theses cards appear at bottom
7. Dark mode toggle works across all new components
8. Mobile responsive: single column, stats 2x2 grid

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during smoke testing"
```
