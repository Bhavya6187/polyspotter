# Dashboard Home Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the PolySpotter home page into an information-dense trading dashboard with a Briefing Banner, sticky sidebar (Resolving Soon, Live Flow, Top Movers), enhanced signal feed with smart sort, and return-visit hooks — all without auth.

**Architecture:** Three-layer layout: full-width Briefing Banner on top, then a 65/35 two-column split with the enhanced signal feed on the left and a sticky sidebar on the right. Five new backend endpoints provide track record, resolved signals, volume spikes, active wallets, and top movers data. Mobile collapses sidebar to horizontal strips above the feed.

**Tech Stack:** Python/FastAPI/PostgreSQL (backend), Next.js 15/React 19/Tailwind CSS 4 (frontend), existing CSS variable theming system.

**Spec:** `docs/superpowers/specs/2026-04-07-dashboard-home-design.md`

---

### Task 1: Backend — Signal Track Record Endpoint

**Files:**
- Modify: `backend/app.py` (add endpoint after `/api/spotlight` block ~line 932)
- Modify: `backend/models.py` (add response model)

- [ ] **Step 1: Add Pydantic response model**

Add to `backend/models.py` after the existing model definitions (before the Basketball models section):

```python
class TrackRecordOut(BaseModel):
    wins: int
    losses: int
    total: int
    win_rate: float
    hypothetical_pnl: float
    days: int
```

- [ ] **Step 2: Add the endpoint to app.py**

Add the import of `TrackRecordOut` to the imports block at the top of `backend/app.py` (line ~36):

```python
from models import (
    # ... existing imports ...
    TrackRecordOut,
)
```

Then add this endpoint after the `/api/spotlight` endpoint (after line 932):

```python
@app.get("/api/signals/track-record", response_model=TrackRecordOut)
def get_signal_track_record(days: int = Query(default=7, ge=1, le=90)):
    """Track record of signals: win/loss/P&L for resolved markets in the last N days.
    A signal 'wins' if the llm_copy_action side matches the resolution outcome
    (price went to >= 0.95 for BUY, or <= 0.05 for SELL)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.llm_copy_action, a.total_usd,
                   latest_candle.p AS latest_price
            FROM alerts a
            LEFT JOIN LATERAL (
                SELECT p FROM price_candles pc
                WHERE pc.condition_id = a.condition_id
                ORDER BY pc.t DESC
                LIMIT 1
            ) latest_candle ON TRUE
            WHERE a.end_date IS NOT NULL
              AND a.end_date <= NOW()
              AND a.end_date > NOW() - make_interval(days => %s)
              AND a.llm_copy_action IS NOT NULL
              AND latest_candle.p IS NOT NULL
              AND (latest_candle.p >= 0.95 OR latest_candle.p <= 0.05)
        """, (days,))
        rows = cur.fetchall()

        wins = 0
        losses = 0
        total_pnl = 0.0

        for row in rows:
            copy_action = row["llm_copy_action"]
            if isinstance(copy_action, str):
                try:
                    copy_action = json.loads(copy_action)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not copy_action or "side" not in copy_action or "entry_price" not in copy_action:
                continue

            side = copy_action.get("side", "").upper()
            entry_price = float(copy_action.get("entry_price", 0))
            latest_price = float(row["latest_price"])

            # BUY wins if price >= 0.95 (resolved to Yes), SELL wins if price <= 0.05 (resolved to No)
            if side == "BUY":
                won = latest_price >= 0.95
                pnl_per_share = (1.0 - entry_price) if won else (-entry_price)
            else:
                won = latest_price <= 0.05
                pnl_per_share = (1.0 - entry_price) if won else (-entry_price)

            if won:
                wins += 1
            else:
                losses += 1

            # Hypothetical P&L = pnl_per_share * shares_bought (total_usd / entry_price)
            if entry_price > 0:
                shares = float(row["total_usd"]) / entry_price
                total_pnl += pnl_per_share * shares

        total = wins + losses
        return TrackRecordOut(
            wins=wins,
            losses=losses,
            total=total,
            win_rate=round(wins / total, 2) if total > 0 else 0.0,
            hypothetical_pnl=round(total_pnl, 2),
            days=days,
        )
```

- [ ] **Step 3: Test the endpoint**

```bash
cd backend && source ../venv/bin/activate
uvicorn app:app --port 8000 &
curl -s http://localhost:8000/api/signals/track-record?days=7 | python -m json.tool
# Expected: {"wins": N, "losses": N, "total": N, "win_rate": 0.XX, "hypothetical_pnl": XXX.XX, "days": 7}
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/app.py backend/models.py
git commit -m "feat(backend): add /api/signals/track-record endpoint"
```

---

### Task 2: Backend — Resolved Signals Endpoint

**Files:**
- Modify: `backend/app.py` (add endpoint after track-record)
- Modify: `backend/models.py` (add response model)

- [ ] **Step 1: Add Pydantic response models**

Add to `backend/models.py`:

```python
class ResolvedSignalOut(BaseModel):
    id: str
    market_title: str
    condition_id: str
    outcome: str
    signal_side: str
    signal_was_correct: bool
    entry_price: float
    pnl_per_share: float
    total_usd: float
    resolved_at: str | None = None
    market_image: str | None = None
```

- [ ] **Step 2: Add the endpoint to app.py**

Add `ResolvedSignalOut` to the imports in `app.py`. Then add:

```python
@app.get("/api/signals/resolved", response_model=list[ResolvedSignalOut])
def get_resolved_signals(limit: int = Query(default=5, ge=1, le=20)):
    """Recently resolved markets that had signals, with outcomes."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.market_title, a.condition_id, a.llm_copy_action,
                   a.total_usd, a.end_date, a.market_image,
                   latest_candle.p AS latest_price
            FROM alerts a
            LEFT JOIN LATERAL (
                SELECT p FROM price_candles pc
                WHERE pc.condition_id = a.condition_id
                ORDER BY pc.t DESC
                LIMIT 1
            ) latest_candle ON TRUE
            WHERE a.end_date IS NOT NULL
              AND a.end_date <= NOW()
              AND a.llm_copy_action IS NOT NULL
              AND latest_candle.p IS NOT NULL
              AND (latest_candle.p >= 0.95 OR latest_candle.p <= 0.05)
            ORDER BY a.end_date DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        results = []
        for row in rows:
            copy_action = row["llm_copy_action"]
            if isinstance(copy_action, str):
                try:
                    copy_action = json.loads(copy_action)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not copy_action or "side" not in copy_action:
                continue

            side = copy_action.get("side", "").upper()
            entry_price = float(copy_action.get("entry_price", 0))
            outcome = copy_action.get("outcome", "")
            latest_price = float(row["latest_price"])

            if side == "BUY":
                won = latest_price >= 0.95
                pnl = (1.0 - entry_price) if won else (-entry_price)
            else:
                won = latest_price <= 0.05
                pnl = (1.0 - entry_price) if won else (-entry_price)

            results.append(ResolvedSignalOut(
                id=row["id"],
                market_title=row["market_title"],
                condition_id=row["condition_id"],
                outcome=outcome,
                signal_side=side,
                signal_was_correct=won,
                entry_price=entry_price,
                pnl_per_share=round(pnl, 4),
                total_usd=float(row["total_usd"]),
                resolved_at=row["end_date"].isoformat() if row["end_date"] else None,
                market_image=row["market_image"],
            ))
        return results
```

- [ ] **Step 3: Test the endpoint**

```bash
cd backend && source ../venv/bin/activate
uvicorn app:app --port 8000 &
curl -s http://localhost:8000/api/signals/resolved?limit=5 | python -m json.tool
# Expected: List of resolved signals with signal_was_correct, pnl_per_share fields
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/app.py backend/models.py
git commit -m "feat(backend): add /api/signals/resolved endpoint"
```

---

### Task 3: Backend — Volume Spikes Endpoint

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add the endpoint**

This endpoint compares each market's last-hour trade count against its 7-day average hourly trade count:

```python
@app.get("/api/flow/volume-spikes")
def get_volume_spikes(limit: int = Query(default=5, ge=1, le=20)):
    """Markets with above-average trade velocity right now (last 1h vs 7d avg)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            WITH recent AS (
                SELECT condition_id, market_title, market_image,
                       COUNT(*) AS recent_count
                FROM alerts a
                JOIN alert_trades at2 ON at2.alert_id = a.id
                WHERE at2.trade_timestamp > NOW() - INTERVAL '1 hour'
                GROUP BY condition_id, market_title, market_image
            ),
            baseline AS (
                SELECT a.condition_id,
                       COUNT(*) / GREATEST(EXTRACT(EPOCH FROM (NOW() - MIN(at2.trade_timestamp))) / 3600, 1) AS avg_hourly
                FROM alerts a
                JOIN alert_trades at2 ON at2.alert_id = a.id
                WHERE at2.trade_timestamp > NOW() - INTERVAL '7 days'
                GROUP BY a.condition_id
            )
            SELECT r.condition_id, r.market_title, r.market_image,
                   r.recent_count,
                   COALESCE(b.avg_hourly, 1) AS avg_hourly,
                   r.recent_count / GREATEST(COALESCE(b.avg_hourly, 1), 1) AS spike_ratio
            FROM recent r
            LEFT JOIN baseline b ON r.condition_id = b.condition_id
            WHERE r.recent_count / GREATEST(COALESCE(b.avg_hourly, 1), 1) > 1.5
            ORDER BY spike_ratio DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        return [
            {
                "condition_id": row["condition_id"],
                "market_title": row["market_title"],
                "market_image": row["market_image"],
                "recent_count": row["recent_count"],
                "avg_hourly": round(float(row["avg_hourly"]), 1),
                "spike_ratio": round(float(row["spike_ratio"]), 1),
            }
            for row in rows
        ]
```

- [ ] **Step 2: Test the endpoint**

```bash
curl -s http://localhost:8000/api/flow/volume-spikes | python -m json.tool
# Expected: List of markets with spike_ratio > 1.5, sorted by spike_ratio DESC
```

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add /api/flow/volume-spikes endpoint"
```

---

### Task 4: Backend — Active Sharp Wallets Endpoint

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add the endpoint**

```python
@app.get("/api/flow/active-wallets")
def get_active_wallets(limit: int = Query(default=5, ge=1, le=20)):
    """Sharp wallets (win_rate >= 0.6) with multiple trades in the last 6 hours."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT at2.wallet,
                   COUNT(DISTINCT a.id) AS trade_count,
                   wp.win_rate,
                   wp.total_pnl,
                   wp.total_invested
            FROM alert_trades at2
            JOIN alerts a ON at2.alert_id = a.id
            JOIN wallet_profiles wp ON at2.wallet = wp.wallet
            WHERE at2.trade_timestamp > NOW() - INTERVAL '6 hours'
              AND wp.win_rate >= 0.6
              AND wp.total_invested > 1000
            GROUP BY at2.wallet, wp.win_rate, wp.total_pnl, wp.total_invested
            HAVING COUNT(DISTINCT a.id) >= 2
            ORDER BY wp.win_rate DESC, trade_count DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        results = []
        for row in rows:
            wr = float(row["win_rate"]) if row["win_rate"] else 0
            invested = float(row["total_invested"]) if row["total_invested"] else 0
            # Tier logic matching frontend WalletBadge
            if wr >= 0.75 and invested >= 50000:
                tier = "diamond"
            elif wr >= 0.65 and invested >= 20000:
                tier = "gold"
            elif wr >= 0.55 and invested >= 5000:
                tier = "silver"
            else:
                tier = "bronze"

            results.append({
                "wallet": row["wallet"],
                "trade_count": row["trade_count"],
                "win_rate": wr,
                "total_pnl": float(row["total_pnl"]) if row["total_pnl"] else 0,
                "tier": tier,
            })
        return results
```

- [ ] **Step 2: Test the endpoint**

```bash
curl -s http://localhost:8000/api/flow/active-wallets | python -m json.tool
# Expected: List of wallets with tier, trade_count, win_rate
```

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add /api/flow/active-wallets endpoint"
```

---

### Task 5: Backend — Top Movers Endpoint

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add the endpoint**

```python
@app.get("/api/markets/top-movers")
def get_top_movers(limit: int = Query(default=6, ge=1, le=20)):
    """Markets with biggest 24h price changes among tracked markets."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            WITH current_prices AS (
                SELECT DISTINCT ON (condition_id) condition_id, p AS current_price, t
                FROM price_candles
                ORDER BY condition_id, t DESC
            ),
            old_prices AS (
                SELECT DISTINCT ON (condition_id) condition_id, p AS old_price
                FROM price_candles
                WHERE t <= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')
                ORDER BY condition_id, t DESC
            ),
            changes AS (
                SELECT cp.condition_id,
                       cp.current_price,
                       op.old_price,
                       cp.current_price - op.old_price AS price_change,
                       CASE WHEN op.old_price > 0
                            THEN ROUND(((cp.current_price - op.old_price) / op.old_price * 100)::numeric, 1)
                            ELSE 0 END AS change_pct
                FROM current_prices cp
                JOIN old_prices op ON cp.condition_id = op.condition_id
                WHERE cp.current_price > 0.03 AND cp.current_price < 0.97
            )
            SELECT c.condition_id, a.market_title, a.market_image,
                   c.current_price, c.change_pct
            FROM changes c
            JOIN LATERAL (
                SELECT market_title, market_image FROM alerts
                WHERE condition_id = c.condition_id
                ORDER BY created_at DESC LIMIT 1
            ) a ON TRUE
            WHERE ABS(c.change_pct) >= 2
            ORDER BY ABS(c.change_pct) DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        return [
            {
                "condition_id": row["condition_id"],
                "market_title": row["market_title"],
                "market_image": row["market_image"],
                "current_price": float(row["current_price"]),
                "change_pct": float(row["change_pct"]),
            }
            for row in rows
        ]
```

- [ ] **Step 2: Test the endpoint**

```bash
curl -s http://localhost:8000/api/markets/top-movers | python -m json.tool
# Expected: List with market_title, change_pct (positive or negative), sorted by |change_pct| DESC
```

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add /api/markets/top-movers endpoint"
```

---

### Task 6: Backend — Briefing Endpoint

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add a combined briefing endpoint**

This endpoint aggregates briefing data in one call (avoids 3 separate requests from the frontend). The `since` parameter accepts an ISO timestamp from the client's localStorage:

```python
@app.get("/api/briefing")
def get_briefing(since: str = Query(default=None)):
    """Briefing data since a given timestamp: new signal count, biggest move, hottest wallet."""
    from datetime import timedelta

    with db() as conn:
        cur = conn.cursor()

        # Parse since timestamp, default to 6h ago
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                since_dt = datetime.now(timezone.utc) - timedelta(hours=6)
        else:
            since_dt = datetime.now(timezone.utc) - timedelta(hours=6)

        since_str = since_dt.isoformat()

        # New signals count since last visit
        cur.execute("SELECT COUNT(*) AS cnt FROM alerts WHERE created_at > %s", (since_str,))
        new_signals = cur.fetchone()["cnt"]

        # Biggest move: alert with highest total_usd since last visit
        cur.execute("""
            SELECT a.market_title, a.condition_id, a.total_usd, a.market_image,
                   (SELECT COUNT(DISTINCT at2.wallet) FROM alert_trades at2 WHERE at2.alert_id = a.id) AS wallet_count
            FROM alerts a
            WHERE a.created_at > %s
            ORDER BY a.total_usd DESC
            LIMIT 1
        """, (since_str,))
        biggest_row = cur.fetchone()
        biggest_move = None
        if biggest_row:
            biggest_move = {
                "market_title": biggest_row["market_title"],
                "condition_id": biggest_row["condition_id"],
                "total_usd": float(biggest_row["total_usd"]),
                "market_image": biggest_row["market_image"],
                "wallet_count": biggest_row["wallet_count"] or 0,
            }

        # Hottest wallet: wallet with most trades since last visit (min win_rate 0.6)
        cur.execute("""
            SELECT at2.wallet, COUNT(*) AS trade_count,
                   wp.win_rate, wp.total_pnl, wp.total_invested
            FROM alert_trades at2
            JOIN alerts a ON at2.alert_id = a.id
            LEFT JOIN wallet_profiles wp ON at2.wallet = wp.wallet
            WHERE a.created_at > %s
              AND wp.win_rate >= 0.6
            GROUP BY at2.wallet, wp.win_rate, wp.total_pnl, wp.total_invested
            ORDER BY trade_count DESC
            LIMIT 1
        """, (since_str,))
        hot_row = cur.fetchone()
        hot_wallet = None
        if hot_row:
            wr = float(hot_row["win_rate"]) if hot_row["win_rate"] else 0
            invested = float(hot_row["total_invested"]) if hot_row["total_invested"] else 0
            if wr >= 0.75 and invested >= 50000:
                tier = "diamond"
            elif wr >= 0.65 and invested >= 20000:
                tier = "gold"
            elif wr >= 0.55 and invested >= 5000:
                tier = "silver"
            else:
                tier = "bronze"
            hot_wallet = {
                "wallet": hot_row["wallet"],
                "trade_count": hot_row["trade_count"],
                "win_rate": wr,
                "tier": tier,
            }

        return {
            "since": since_str,
            "new_signals": new_signals,
            "biggest_move": biggest_move,
            "hot_wallet": hot_wallet,
        }
```

- [ ] **Step 2: Test the endpoint**

```bash
curl -s "http://localhost:8000/api/briefing?since=2026-04-06T00:00:00Z" | python -m json.tool
# Expected: {since, new_signals, biggest_move: {market_title, ...}, hot_wallet: {wallet, ...}}
curl -s "http://localhost:8000/api/briefing" | python -m json.tool
# Expected: Same structure with default 6h window
```

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(backend): add /api/briefing endpoint"
```

---

### Task 7: Frontend — API Client Functions

**Files:**
- Modify: `frontend/src/lib/api.js`

- [ ] **Step 1: Add API client functions for all new endpoints**

Append to `frontend/src/lib/api.js`:

```javascript
export function fetchTrackRecord(days = 7) {
  return request("/api/signals/track-record", { days });
}

export function fetchResolvedSignals(limit = 5) {
  return request("/api/signals/resolved", { limit });
}

export function fetchVolumeSpikes(limit = 5) {
  return request("/api/flow/volume-spikes", { limit });
}

export function fetchActiveWallets(limit = 5) {
  return request("/api/flow/active-wallets", { limit });
}

export function fetchTopMovers(limit = 6) {
  return request("/api/markets/top-movers", { limit });
}

export function fetchBriefing(since = null) {
  return request("/api/briefing", { since: since || undefined });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(frontend): add API client functions for new endpoints"
```

---

### Task 8: Frontend — BriefingBanner Component

**Files:**
- Create: `frontend/src/components/BriefingBanner.jsx`

- [ ] **Step 1: Create the BriefingBanner component**

```jsx
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchBriefing, fetchTrackRecord, fetchResolvedSignals } from "../lib/api";

function formatUsd(n) {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n)}`;
}

function walletName(address) {
  if (!address) return "";
  return `Trader_${address.slice(0, 7)}`;
}

function timeSinceLabel(isoString) {
  if (!isoString) return "";
  const ms = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(ms / 3600000);
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const TIER_COLORS = {
  diamond: { bg: "#58a6ff", label: "DIAMOND" },
  gold: { bg: "#d29922", label: "GOLD" },
  silver: { bg: "#8b949e", label: "SILVER" },
  bronze: { bg: "#a87756", label: "BRONZE" },
};

export default function BriefingBanner() {
  const [briefing, setBriefing] = useState(null);
  const [trackRecord, setTrackRecord] = useState(null);
  const [resolved, setResolved] = useState([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Check if dismissed this session
    try {
      const d = sessionStorage.getItem("polyspotter_briefing_dismissed");
      if (d === "true") { setDismissed(true); return; }
    } catch {}

    // Get last visit timestamp
    let since = null;
    try {
      since = localStorage.getItem("polyspotter_last_visit");
    } catch {}

    // Fetch all briefing data in parallel
    Promise.all([
      fetchBriefing(since).catch(() => null),
      fetchTrackRecord(7).catch(() => null),
      fetchResolvedSignals(5).catch(() => []),
    ]).then(([b, tr, rs]) => {
      setBriefing(b);
      setTrackRecord(tr);
      setResolved(rs || []);
    });

    // Update last visit timestamp
    try {
      localStorage.setItem("polyspotter_last_visit", new Date().toISOString());
    } catch {}

    // Refresh on tab focus
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        let s = null;
        try { s = localStorage.getItem("polyspotter_last_visit"); } catch {}
        fetchBriefing(s).then(setBriefing).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    try { sessionStorage.setItem("polyspotter_briefing_dismissed", "true"); } catch {}
  };

  if (dismissed || (!briefing && !trackRecord)) return null;

  const sinceLabel = briefing ? timeSinceLabel(briefing.since) : "";

  return (
    <div
      className="rounded-xl mb-5"
      style={{
        background: "linear-gradient(135deg, var(--surface-1) 0%, var(--surface-2) 100%)",
        border: "1px solid var(--border)",
        padding: "16px 20px",
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-semibold uppercase tracking-widest"
            style={{ color: "var(--warning)" }}
          >
            Briefing
          </span>
          {sinceLabel && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Since {sinceLabel}
            </span>
          )}
        </div>
        <button
          onClick={handleDismiss}
          className="text-xs hover:opacity-70 transition-opacity"
          style={{ color: "var(--text-muted)" }}
        >
          Dismiss &times;
        </button>
      </div>

      {/* Row 1: Stats | Biggest Move | Hot Wallet */}
      <div className="flex flex-col md:flex-row md:items-center gap-4 md:gap-6">
        {/* Stat cluster */}
        {briefing && (
          <div className="flex gap-5 flex-shrink-0">
            <div className="text-center">
              <div className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                {briefing.new_signals}
              </div>
              <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                New Signals
              </div>
            </div>
            {trackRecord && (
              <>
                <div className="text-center">
                  <div
                    className="text-2xl font-bold"
                    style={{ color: trackRecord.hypothetical_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" }}
                  >
                    {trackRecord.hypothetical_pnl >= 0 ? "+" : ""}{formatUsd(trackRecord.hypothetical_pnl)}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Signal P&L
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                    {trackRecord.total}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Resolved
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold" style={{ color: "var(--bullish)" }}>
                    {trackRecord.wins}/{trackRecord.total}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Won
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Divider */}
        <div className="hidden md:block w-px self-stretch" style={{ background: "var(--border)" }} />

        {/* Biggest move */}
        {briefing?.biggest_move && (
          <Link
            href={`/market/${briefing.biggest_move.condition_id}`}
            className="flex items-center gap-3 flex-1 min-w-0 hover:opacity-80 transition-opacity"
          >
            <div className="flex-shrink-0">
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
                Biggest Move
              </div>
              <div className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)", maxWidth: "200px" }}>
                {briefing.biggest_move.market_title}
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {formatUsd(briefing.biggest_move.total_usd)} smart money &bull; {briefing.biggest_move.wallet_count} wallet{briefing.biggest_move.wallet_count !== 1 ? "s" : ""}
              </div>
            </div>
          </Link>
        )}

        {/* Divider */}
        <div className="hidden md:block w-px self-stretch" style={{ background: "var(--border)" }} />

        {/* Hot wallet */}
        {briefing?.hot_wallet && (
          <Link
            href={`/wallet/${briefing.hot_wallet.wallet}`}
            className="flex items-center gap-2 flex-shrink-0 hover:opacity-80 transition-opacity"
          >
            <div>
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
                Hot Wallet
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="text-xs font-bold px-1.5 py-0.5 rounded"
                  style={{
                    background: TIER_COLORS[briefing.hot_wallet.tier]?.bg || "#8b949e",
                    color: "#0d1117",
                  }}
                >
                  {TIER_COLORS[briefing.hot_wallet.tier]?.label || "BRONZE"}
                </span>
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {walletName(briefing.hot_wallet.wallet)}
                </span>
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {Math.round(briefing.hot_wallet.win_rate * 100)}% WR &bull; {briefing.hot_wallet.trade_count} trades
              </div>
            </div>
          </Link>
        )}
      </div>

      {/* Row 2: Track Record Streak + Just Resolved */}
      {(trackRecord || resolved.length > 0) && (
        <>
          <div className="my-3" style={{ borderTop: "1px solid var(--border)" }} />
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            {/* P&L Streak */}
            {trackRecord && trackRecord.total > 0 && (
              <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--warning)" }}>Last {trackRecord.days}d:</span>{" "}
                {trackRecord.wins}/{trackRecord.total} signals won ({Math.round(trackRecord.win_rate * 100)}%)
                {" — "}
                <span style={{ color: trackRecord.hypothetical_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" }}>
                  {trackRecord.hypothetical_pnl >= 0 ? "+" : ""}{formatUsd(trackRecord.hypothetical_pnl)} hypothetical P&L
                </span>
              </div>
            )}

            {/* Divider */}
            {trackRecord && resolved.length > 0 && (
              <div className="hidden sm:block w-px h-4" style={{ background: "var(--border)" }} />
            )}

            {/* Just Resolved */}
            {resolved.length > 0 && (
              <div className="flex gap-3 overflow-x-auto flex-1">
                {resolved.map((r) => (
                  <Link
                    key={r.id}
                    href={`/market/${r.condition_id}`}
                    className="flex items-center gap-1.5 flex-shrink-0 text-xs hover:opacity-80 transition-opacity"
                  >
                    <span style={{ color: r.signal_was_correct ? "var(--bullish)" : "var(--bearish)" }}>
                      {r.signal_was_correct ? "✓" : "✗"}
                    </span>
                    <span
                      className="truncate"
                      style={{ color: "var(--text-secondary)", maxWidth: "120px" }}
                    >
                      {r.market_title}
                    </span>
                    <span
                      className="font-semibold"
                      style={{ color: r.pnl_per_share >= 0 ? "var(--bullish)" : "var(--bearish)" }}
                    >
                      {r.pnl_per_share >= 0 ? "+" : ""}{Math.round(r.pnl_per_share * 100)}%
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/BriefingBanner.jsx
git commit -m "feat(frontend): add BriefingBanner component"
```

---

### Task 9: Frontend — Sidebar Component

**Files:**
- Create: `frontend/src/components/DashboardSidebar.jsx`

- [ ] **Step 1: Create the DashboardSidebar component**

```jsx
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchResolvingSoon, fetchVolumeSpikes, fetchActiveWallets, fetchTopMovers } from "../lib/api";
import { useCountdown } from "../hooks/useCountdown";

function formatUsd(n) {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n)}`;
}

function walletName(address) {
  if (!address) return "";
  return `Trader_${address.slice(0, 7)}`;
}

const TIER_COLORS = {
  diamond: { bg: "#58a6ff", label: "DIAMOND" },
  gold: { bg: "#d29922", label: "GOLD" },
  silver: { bg: "#8b949e", label: "SILVER" },
  bronze: { bg: "#a87756", label: "BRONZE" },
};

function CountdownLabel({ endDate }) {
  const countdown = useCountdown(endDate);
  if (!countdown || countdown.total <= 0) return <span style={{ color: "var(--text-muted)" }}>Ended</span>;

  const isUrgent = countdown.total < 6 * 3600 * 1000;
  const hours = Math.floor(countdown.total / 3600000);
  const minutes = Math.floor((countdown.total % 3600000) / 60000);

  let label;
  if (hours > 0) label = `${hours}h ${minutes}m`;
  else label = `${minutes}m`;

  return (
    <span className="font-bold text-sm" style={{ color: isUrgent ? "var(--bearish)" : "var(--warning)" }}>
      {label}
    </span>
  );
}

function ResolvingSoonModule() {
  const [markets, setMarkets] = useState([]);

  useEffect(() => {
    fetchResolvingSoon().then(setMarkets).catch(() => setMarkets([]));
  }, []);

  if (!markets.length) return null;

  return (
    <div
      className="rounded-lg p-4 mb-3"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--bearish)" }}>
          Resolving Soon
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{markets.length} markets</span>
      </div>
      <div className="flex flex-col gap-2">
        {markets.slice(0, 5).map((m) => {
          const isUrgent = m.end_date && (new Date(m.end_date) - Date.now()) < 6 * 3600 * 1000;
          return (
            <Link
              key={m.id || m.condition_id}
              href={`/market/${m.condition_id}`}
              className="rounded-md p-2.5 hover:opacity-80 transition-opacity"
              style={{
                background: "var(--surface-2)",
                borderLeft: `3px solid ${isUrgent ? "var(--bearish)" : "var(--warning)"}`,
              }}
            >
              <div className="flex justify-between items-center">
                <span
                  className="text-xs font-semibold truncate"
                  style={{ color: "var(--text-primary)", maxWidth: "160px" }}
                >
                  {m.market_title}
                </span>
                <CountdownLabel endDate={m.end_date} />
              </div>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {formatUsd(m.total_usd)} smart money{m.dominant_side ? ` on ${m.dominant_side}` : ""}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function LiveFlowModule() {
  const [spikes, setSpikes] = useState([]);
  const [wallets, setWallets] = useState([]);

  useEffect(() => {
    const load = () => {
      fetchVolumeSpikes(5).then(setSpikes).catch(() => setSpikes([]));
      fetchActiveWallets(5).then(setWallets).catch(() => setWallets([]));
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!spikes.length && !wallets.length) return null;

  const maxSpike = spikes.length ? Math.max(...spikes.map((s) => s.spike_ratio)) : 1;

  return (
    <div
      className="rounded-lg p-4 mb-3"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--bullish)" }}>
          &#9679; Live Flow
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>last 30m</span>
      </div>

      {/* Volume Spikes */}
      {spikes.length > 0 && (
        <div className="mb-3">
          <div
            className="text-xs uppercase tracking-wide mb-2"
            style={{ color: "var(--text-muted)" }}
          >
            Volume Spikes
          </div>
          {spikes.map((s) => (
            <Link
              key={s.condition_id}
              href={`/market/${s.condition_id}`}
              className="block rounded-md p-2 mb-1 hover:opacity-80 transition-opacity"
              style={{ background: "var(--surface-2)" }}
            >
              <div className="flex justify-between items-center text-xs">
                <span className="truncate" style={{ color: "var(--text-primary)", maxWidth: "150px" }}>
                  {s.market_title}
                </span>
                <span
                  className="font-bold"
                  style={{
                    color: s.spike_ratio >= 3 ? "var(--warning)" : "var(--text-secondary)",
                  }}
                >
                  {s.spike_ratio}x
                </span>
              </div>
              <div
                className="mt-1 rounded-full overflow-hidden"
                style={{ background: "var(--border)", height: "4px" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min((s.spike_ratio / maxSpike) * 100, 100)}%`,
                    background: s.spike_ratio >= 3 ? "var(--warning)" : "var(--text-muted)",
                  }}
                />
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Active Sharp Wallets */}
      {wallets.length > 0 && (
        <div>
          <div
            className="text-xs uppercase tracking-wide mb-2"
            style={{ color: "var(--text-muted)" }}
          >
            Active Sharp Wallets
          </div>
          {wallets.map((w) => (
            <Link
              key={w.wallet}
              href={`/wallet/${w.wallet}`}
              className="flex items-center gap-2 rounded-md p-2 mb-1 hover:opacity-80 transition-opacity"
              style={{ background: "var(--surface-2)" }}
            >
              <span
                className="text-xs font-bold px-1 py-0.5 rounded"
                style={{
                  background: TIER_COLORS[w.tier]?.bg || "#8b949e",
                  color: "#0d1117",
                  fontSize: "8px",
                }}
              >
                {TIER_COLORS[w.tier]?.label || "BRONZE"}
              </span>
              <span className="text-xs" style={{ color: "var(--text-primary)" }}>
                {walletName(w.wallet)}
              </span>
              <span className="text-xs ml-auto" style={{ color: "var(--text-muted)" }}>
                {w.trade_count} trades
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function TopMoversModule() {
  const [movers, setMovers] = useState([]);

  useEffect(() => {
    fetchTopMovers(6).then(setMovers).catch(() => setMovers([]));
  }, []);

  if (!movers.length) return null;

  return (
    <div
      className="rounded-lg p-4"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--warning)" }}>
          Top Movers
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>24h</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {movers.map((m) => (
          <Link
            key={m.condition_id}
            href={`/market/${m.condition_id}`}
            className="flex justify-between items-center rounded-md p-2 hover:opacity-80 transition-opacity text-xs"
            style={{ background: "var(--surface-2)" }}
          >
            <span className="truncate" style={{ color: "var(--text-primary)", maxWidth: "170px" }}>
              {m.market_title}
            </span>
            <span
              className="font-bold"
              style={{ color: m.change_pct >= 0 ? "var(--bullish)" : "var(--bearish)" }}
            >
              {m.change_pct >= 0 ? "+" : ""}{m.change_pct}%
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function DashboardSidebar() {
  return (
    <aside className="sticky top-4" style={{ maxHeight: "calc(100vh - 2rem)", overflowY: "auto" }}>
      <ResolvingSoonModule />
      <LiveFlowModule />
      <TopMoversModule />
    </aside>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DashboardSidebar.jsx
git commit -m "feat(frontend): add DashboardSidebar component with resolving, flow, movers"
```

---

### Task 10: Frontend — Smart Sort in AlertList

**Files:**
- Modify: `frontend/src/components/AlertList.jsx`

- [ ] **Step 1: Add smart sort function**

Add this function near the top of `frontend/src/components/AlertList.jsx` (after the existing imports and utility functions):

```javascript
function computeSmartScore(market) {
  const now = Date.now();
  const bestAlert = market.alerts?.[0] || market;
  const compositeScore = market.max_score || bestAlert.composite_score || 1;

  // Urgency multiplier based on time to resolution
  let urgencyMultiplier = 1;
  if (market.end_date) {
    const hoursLeft = (new Date(market.end_date) - now) / 3600000;
    if (hoursLeft <= 0) urgencyMultiplier = 0.1; // already resolved
    else if (hoursLeft < 1) urgencyMultiplier = 5;
    else if (hoursLeft < 6) urgencyMultiplier = 3;
    else if (hoursLeft < 24) urgencyMultiplier = 2;
    else if (hoursLeft < 168) urgencyMultiplier = 1.5;
  }

  // Recency factor based on signal age
  let recencyFactor = 0.5;
  const scannedAt = bestAlert.scanned_at || bestAlert.created_at || market.scanned_at;
  if (scannedAt) {
    const hoursOld = (now - new Date(scannedAt)) / 3600000;
    if (hoursOld < 1) recencyFactor = 1.0;
    else if (hoursOld < 6) recencyFactor = 0.9;
    else if (hoursOld < 24) recencyFactor = 0.7;
  }

  return compositeScore * urgencyMultiplier * recencyFactor;
}
```

- [ ] **Step 2: Add sort parameter and apply sorting**

In the component that filters and sorts markets (the main `AlertList` function), find the existing client-side filtering section. After the existing filtering logic, add sort support.

Modify the `AlertList` component to accept a `sortMode` prop:

```javascript
function AlertList({ markets, filters, loading, theses = [], sortMode = "smart" })
```

Then in the filtering/sorting section (where markets are processed before rendering), replace the existing sort logic with:

```javascript
// Sort markets based on sortMode
const sortedMarkets = [...filteredMarkets].sort((a, b) => {
  switch (sortMode) {
    case "smart":
      return computeSmartScore(b) - computeSmartScore(a);
    case "newest":
      return new Date(b.scanned_at || 0) - new Date(a.scanned_at || 0);
    case "biggest":
      return (b.total_usd || 0) - (a.total_usd || 0);
    case "closing":
      const aEnd = a.end_date ? new Date(a.end_date) : new Date("2099-01-01");
      const bEnd = b.end_date ? new Date(b.end_date) : new Date("2099-01-01");
      return aEnd - bEnd;
    default:
      return computeSmartScore(b) - computeSmartScore(a);
  }
});
```

Use `sortedMarkets` instead of `filteredMarkets` when rendering.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlertList.jsx
git commit -m "feat(frontend): add smart sort to AlertList"
```

---

### Task 11: Frontend — Sort Controls + Urgency Borders in Filters and AlertList

**Files:**
- Modify: `frontend/src/components/Filters.jsx`
- Modify: `frontend/src/components/AlertList.jsx`

- [ ] **Step 1: Add sort options to Filters component**

In `frontend/src/components/Filters.jsx`, add a sort row above the existing resolution row. The `filters` object gains a `sort` field:

Add this constant near the top of the file:

```javascript
const SORT_OPTIONS = [
  { label: "Smart", value: "smart" },
  { label: "Newest", value: "newest" },
  { label: "Biggest $", value: "biggest" },
  { label: "Closing Soon", value: "closing" },
];
```

Add a sort row in the JSX (before the RESOLVES row):

```jsx
{/* Sort */}
<div className="flex items-center gap-2 flex-wrap">
  <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-muted)' }}>Sort</span>
  {SORT_OPTIONS.map((opt) => (
    <button
      key={opt.value}
      onClick={() => onFilterChange({ ...filters, sort: opt.value })}
      className="text-xs px-3 py-1 rounded-full transition-colors"
      style={{
        background: (filters.sort || "smart") === opt.value ? 'var(--accent-subtle)' : 'var(--surface-2)',
        color: (filters.sort || "smart") === opt.value ? 'var(--accent)' : 'var(--text-secondary)',
        border: `1px solid ${(filters.sort || "smart") === opt.value ? 'var(--accent)' : 'var(--border)'}`,
      }}
    >
      {opt.label}
    </button>
  ))}
</div>
```

- [ ] **Step 2: Pass sortMode to AlertList from HomeClient**

In `frontend/src/app/home-client.jsx`, update the `AlertList` usage:

```jsx
<AlertList
  markets={markets}
  filters={filters}
  loading={loading}
  theses={theses}
  sortMode={filters.sort || "smart"}
/>
```

- [ ] **Step 3: Add urgency and cluster borders to MarketGroupCard**

In `frontend/src/components/AlertList.jsx`, in the `MarketGroupCard` component, add a left border based on urgency and alert type. Find where the card's outer `<div>` is rendered and add a `borderLeft` style:

```javascript
// Inside MarketGroupCard, compute border color
const hoursToEnd = market.end_date
  ? (new Date(market.end_date) - Date.now()) / 3600000
  : Infinity;
const isCluster = market.alerts?.some(a => a.alert_type === "cluster");
const borderLeftColor = hoursToEnd <= 6 && hoursToEnd > 0
  ? "var(--bearish)"       // red for <6h
  : isCluster
  ? "#bc8cff"              // purple for cluster
  : "transparent";
```

Apply it to the card's style: `borderLeft: \`3px solid ${borderLeftColor}\``

- [ ] **Step 4: Add "View market" link to alert cards**

In the `AlertEntry` sub-component inside `AlertList.jsx`, find the CTA row (where "Copy trade" button is rendered). After the CTA button and payout info, add:

```jsx
<Link
  href={`/market/${alert.condition_id || market.condition_id}`}
  className="text-xs ml-auto hover:opacity-70 transition-opacity"
  style={{ color: "var(--text-muted)" }}
>
  View market →
</Link>
```

Add `import Link from "next/link"` to the top of the file if not already present.

- [ ] **Step 5: Update localStorage filter persistence**

In `frontend/src/app/home-client.jsx`, the existing localStorage persistence already saves the full `filters` object including the new `sort` field. Update the default filters to include `sort`:

```javascript
const [filters, setFilters] = useState({
  tag: "",
  resolvesIn: "",
  minScore: "",
  sort: "smart",
});
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Filters.jsx frontend/src/components/AlertList.jsx frontend/src/app/home-client.jsx
git commit -m "feat(frontend): add sort controls, urgency borders, view market link"
```

---

### Task 12: Frontend — Two-Column Dashboard Layout

**Files:**
- Modify: `frontend/src/app/home-client.jsx`

- [ ] **Step 1: Import new components and restructure layout**

Update the imports at the top of `frontend/src/app/home-client.jsx`:

```javascript
import BriefingBanner from "../components/BriefingBanner";
import DashboardSidebar from "../components/DashboardSidebar";
```

- [ ] **Step 2: Restructure the JSX layout**

Replace the current layout structure in the `return` statement. Keep header and HeroSpotlight at full width, then add the two-column layout below. Remove the standalone `<ResolvingSoonStrip />` section (it's now in the sidebar):

```jsx
return (
  <main className="mx-auto max-w-7xl px-4 py-6">
    {/* Header */}
    <header className="mb-8">
      {/* ... existing header JSX unchanged ... */}
    </header>

    {/* Hero Spotlight */}
    <section aria-label="Spotlight" className="mb-5">
      <HeroSpotlight />
    </section>

    {/* Live ticker — hidden on mobile */}
    <section aria-label="Live ticker" className="hidden sm:block mb-5 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
      <Ticker />
    </section>

    {/* Briefing Banner */}
    <section aria-label="Briefing">
      <BriefingBanner />
    </section>

    {/* Mobile: Sidebar strips above feed */}
    <section aria-label="Market overview" className="block lg:hidden mb-5">
      <DashboardSidebar />
    </section>

    {/* Two-column layout */}
    <div className="flex gap-6">
      {/* Main feed column (~65%) */}
      <div className="flex-1 min-w-0">
        {/* Filters */}
        <section aria-label="Filters" className="mb-5">
          <Filters
            tags={tags}
            filters={filters}
            onFilterChange={handleFilterChange}
          />
        </section>

        {/* Alert List */}
        <section aria-label="Notable trades">
          <h2 className="sr-only" aria-hidden="true">Notable Trades</h2>
          <AlertList
            markets={markets}
            filters={filters}
            loading={loading}
            theses={theses}
            sortMode={filters.sort || "smart"}
          />
        </section>

        {/* Pagination */}
        <nav aria-label="Pagination">
          <Pagination
            page={page}
            totalPages={totalPages}
            onPageChange={handlePageChange}
          />
        </nav>
      </div>

      {/* Sidebar column (~35%) — desktop only */}
      <div className="hidden lg:block" style={{ width: "340px", flexShrink: 0 }}>
        <DashboardSidebar />
      </div>
    </div>
  </main>
);
```

Note the key changes:
- `max-w-6xl` → `max-w-7xl` (wider to accommodate sidebar)
- Standalone `<ResolvingSoonStrip />` removed (now inside `DashboardSidebar`)
- Mobile shows `DashboardSidebar` above the feed (stacked)
- Desktop shows sidebar to the right (`lg:block`)

- [ ] **Step 3: Remove ResolvingSoonStrip import**

Remove the `ResolvingSoonStrip` import from the top of `home-client.jsx` since it's no longer used directly (the sidebar handles it):

```javascript
// Remove this line:
// import ResolvingSoonStrip from "../components/ResolvingSoonStrip";
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/home-client.jsx
git commit -m "feat(frontend): two-column dashboard layout with briefing and sidebar"
```

---

### Task 13: Frontend — Inline Sparklines on Signal Cards

**Files:**
- Modify: `frontend/src/components/AlertList.jsx`

- [ ] **Step 1: Add inline market stats to MarketGroupCard**

In the `MarketGroupCard` component inside `AlertList.jsx`, after the alert entries and before the CTA row, add a compact stats row that uses the existing `liveData` state. Find where `liveData[market.condition_id]` is referenced and add:

```jsx
{/* Inline market stats */}
{liveData[market.condition_id] && (
  <div className="flex gap-3 mt-2 mb-2">
    {/* Mini sparkline placeholder — uses Sparkline component */}
    <div
      className="flex-1 rounded-md px-2 py-1.5"
      style={{ background: "var(--surface-2)" }}
    >
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
        {liveData[market.condition_id].outcomes?.[0]?.name || "Price"} 24h
      </div>
      <Sparkline conditionId={market.condition_id} height={20} />
    </div>
    <div
      className="rounded-md px-3 py-1.5 text-center"
      style={{ background: "var(--surface-2)" }}
    >
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>Spread</div>
      <div
        className="text-sm font-bold"
        style={{
          color: (liveData[market.condition_id].spread || 0) <= 0.02
            ? "var(--bullish)"
            : "var(--text-primary)",
        }}
      >
        {((liveData[market.condition_id].spread || 0) * 100).toFixed(1)}¢
      </div>
    </div>
    <div
      className="rounded-md px-3 py-1.5 text-center"
      style={{ background: "var(--surface-2)" }}
    >
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>24h Vol</div>
      <div className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
        {liveData[market.condition_id].volume_24h
          ? `$${(liveData[market.condition_id].volume_24h / 1000).toFixed(1)}K`
          : "—"}
      </div>
    </div>
  </div>
)}
```

Make sure the `Sparkline` component is imported at the top of the file. Check if it's already imported; if not:

```javascript
import Sparkline from "./Sparkline";
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/AlertList.jsx
git commit -m "feat(frontend): add inline sparkline and market stats to signal cards"
```

---

### Task 14: Integration Test — Full Page Load

**Files:**
- No new files — manual verification

- [ ] **Step 1: Start the backend**

```bash
cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate
uvicorn app:app --reload --port 8000
```

- [ ] **Step 2: Verify all new endpoints return data**

```bash
curl -s http://localhost:8000/api/signals/track-record | python -m json.tool
curl -s http://localhost:8000/api/signals/resolved | python -m json.tool
curl -s http://localhost:8000/api/flow/volume-spikes | python -m json.tool
curl -s http://localhost:8000/api/flow/active-wallets | python -m json.tool
curl -s http://localhost:8000/api/markets/top-movers | python -m json.tool
curl -s http://localhost:8000/api/briefing | python -m json.tool
```

Each should return valid JSON (may be empty lists/zeros if no recent data — that's fine).

- [ ] **Step 3: Start the frontend**

```bash
cd /Users/bhavya/git/polybot/frontend && npm run dev
```

- [ ] **Step 4: Verify the page loads without errors**

Open `http://localhost:3000` in a browser. Check:
- Briefing Banner appears at top with stats (or empty gracefully)
- Two-column layout on desktop (feed left, sidebar right)
- Sidebar shows Resolving Soon, Live Flow, Top Movers modules
- Sort options appear in filters (Smart/Newest/Biggest $/Closing Soon)
- Signal cards have urgency borders (red for <6h, purple for cluster)
- "View market →" link appears on cards
- Mobile: sidebar collapses above the feed

- [ ] **Step 5: Check browser console for errors**

Open DevTools → Console. No errors should appear. Warnings about missing data are acceptable.

- [ ] **Step 6: Run existing tests to verify no regressions**

```bash
cd /Users/bhavya/git/polybot && source venv/bin/activate && pytest
cd frontend && npm run lint
```

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: dashboard home redesign — briefing, sidebar, smart sort, market stats"
```
