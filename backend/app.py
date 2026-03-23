"""
Polybot Backend API

FastAPI service providing CRUD over the alerts database.
Endpoints:
  POST /api/ingest        — bulk ingest alerts from polybot scanner
  GET  /api/alerts        — list alerts (paginated, filterable)
  GET  /api/alerts/{id}   — get single alert with trades + signals
  GET  /api/wallets/{addr} — get wallet profile
  GET  /api/strategies    — list all strategies seen
  GET  /api/health        — health check
"""

from __future__ import annotations

import json
import time as _time
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager

import requests as _requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import get_conn, init_db
from models import (
    IngestPayload,
    AlertOut,
    AlertDetail,
    TradeOut,
    SignalOut,
    WalletProfileOut,
    PaginatedAlerts,
    MarketGroup,
    PaginatedMarkets,
    LiveMarketData,
    OutcomePrice,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Polybot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _alert_from_row(row: dict) -> AlertOut:
    """Build an AlertOut from a DB row, parsing JSON columns."""
    data = dict(row)
    data.pop("latest_trade_at", None)
    raw = data.pop("tags", "[]") or "[]"
    data["tags"] = json.loads(raw) if isinstance(raw, str) else raw
    # Parse llm_bullets (JSON array)
    raw_bullets = data.pop("llm_bullets", "[]") or "[]"
    data["llm_bullets"] = json.loads(raw_bullets) if isinstance(raw_bullets, str) else raw_bullets
    # Parse llm_copy_action (JSON object)
    raw_copy = data.pop("llm_copy_action", "{}") or "{}"
    data["llm_copy_action"] = json.loads(raw_copy) if isinstance(raw_copy, str) else raw_copy
    # Wallet profile fields (present when query joins wallet_profiles)
    data.setdefault("win_rate", None)
    data.setdefault("total_pnl", None)
    return AlertOut(**data)


# ---------------------------------------------------------------------------
# Ingest (called by polybot seeder)
# ---------------------------------------------------------------------------

@app.post("/api/ingest")
def ingest(payload: IngestPayload):
    """Bulk ingest alerts and wallet profiles from polybot."""
    inserted_alerts = 0
    updated_alerts = 0
    skipped_alerts = 0

    with db() as conn:
        cur = conn.cursor()

        for alert in payload.alerts:
            try:
                tags_json = json.dumps(alert.tags) if alert.tags else "[]"
                bullets_json = json.dumps(alert.llm_bullets) if alert.llm_bullets else "[]"
                copy_action_json = json.dumps(
                    alert.llm_copy_action.model_dump() if hasattr(alert.llm_copy_action, "model_dump")
                    else (alert.llm_copy_action or {})
                )
                cur.execute(
                    """INSERT INTO alerts
                       (alert_type, composite_score, tags, market_title, condition_id,
                        event_slug, market_url, wallet, total_usd, trade_count,
                        cluster_headline, end_date, llm_headline, llm_summary,
                        llm_bullets, llm_copy_action, scanned_at, dedup_key)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (dedup_key) DO UPDATE SET
                        composite_score = EXCLUDED.composite_score,
                        tags = EXCLUDED.tags,
                        total_usd = EXCLUDED.total_usd,
                        trade_count = EXCLUDED.trade_count,
                        cluster_headline = EXCLUDED.cluster_headline,
                        end_date = EXCLUDED.end_date,
                        llm_headline = EXCLUDED.llm_headline,
                        llm_summary = EXCLUDED.llm_summary,
                        llm_bullets = EXCLUDED.llm_bullets,
                        llm_copy_action = EXCLUDED.llm_copy_action,
                        scanned_at = EXCLUDED.scanned_at
                       RETURNING id, (xmax = 0) AS inserted""",
                    (
                        alert.alert_type,
                        alert.composite_score,
                        tags_json,
                        alert.market_title,
                        alert.condition_id,
                        alert.event_slug,
                        alert.market_url,
                        alert.wallet,
                        alert.total_usd,
                        alert.trade_count,
                        alert.cluster_headline,
                        alert.end_date,
                        alert.llm_headline,
                        alert.llm_summary,
                        bullets_json,
                        copy_action_json,
                        alert.scanned_at or datetime.now(timezone.utc),
                        alert.dedup_key,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    skipped_alerts += 1
                    continue

                alert_id = row["id"]
                was_insert = row["inserted"]

                if was_insert:
                    inserted_alerts += 1
                else:
                    updated_alerts += 1
                    # Delete + re-insert child rows so updated clusters
                    # reflect the latest trades/signals (inserts below use
                    # ON CONFLICT DO NOTHING, so this isn't strictly required
                    # but keeps the data clean if a trade was dropped)
                    cur.execute("DELETE FROM alert_trades WHERE alert_id = %s", (alert_id,))
                    cur.execute("DELETE FROM alert_signals WHERE alert_id = %s", (alert_id,))

                for trade in alert.trades:
                    cur.execute(
                        """INSERT INTO alert_trades
                           (alert_id, transaction_hash, wallet, condition_id,
                            outcome, side, usd_value, size, price, trade_timestamp)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING""",
                        (
                            alert_id,
                            trade.transaction_hash,
                            trade.wallet,
                            trade.condition_id,
                            trade.outcome,
                            trade.side,
                            trade.usd_value,
                            trade.size,
                            trade.price,
                            trade.trade_timestamp,
                        ),
                    )

                for sig in alert.signals:
                    cur.execute(
                        """INSERT INTO alert_signals
                           (alert_id, strategy, severity, headline)
                           VALUES (%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING""",
                        (alert_id, sig.strategy, sig.severity, sig.headline),
                    )

            except Exception as e:
                # Log but continue — don't fail the whole batch
                print(f"[WARN] Failed to insert alert: {e}")
                skipped_alerts += 1

        # Wallet profiles
        for wp in payload.wallet_profiles:
            cur.execute(
                """INSERT INTO wallet_profiles
                   (wallet, total_positions, closed_positions, wins, losses,
                    total_pnl, total_invested, avg_win_price, win_rate,
                    times_flagged, first_seen_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
                   ON CONFLICT (wallet) DO UPDATE SET
                    total_positions = EXCLUDED.total_positions,
                    closed_positions = EXCLUDED.closed_positions,
                    wins = EXCLUDED.wins,
                    losses = EXCLUDED.losses,
                    total_pnl = EXCLUDED.total_pnl,
                    total_invested = EXCLUDED.total_invested,
                    avg_win_price = EXCLUDED.avg_win_price,
                    win_rate = EXCLUDED.win_rate,
                    times_flagged = EXCLUDED.times_flagged,
                    first_seen_at = COALESCE(EXCLUDED.first_seen_at, wallet_profiles.first_seen_at),
                    updated_at = NOW()""",
                (
                    wp.wallet.lower(),
                    wp.total_positions,
                    wp.closed_positions,
                    wp.wins,
                    wp.losses,
                    wp.total_pnl,
                    wp.total_invested,
                    wp.avg_win_price,
                    wp.win_rate,
                    wp.times_flagged,
                    wp.first_seen_at,
                ),
            )

    return {
        "status": "ok",
        "inserted_alerts": inserted_alerts,
        "updated_alerts": updated_alerts,
        "skipped_alerts": skipped_alerts,
        "wallet_profiles": len(payload.wallet_profiles),
    }


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@app.get("/api/alerts", response_model=PaginatedAlerts)
def list_alerts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0),
    strategy: str | None = Query(None, description="Filter by strategy name"),
    wallet: str | None = Query(None, description="Filter by wallet address"),
    event_slug: str | None = Query(None, description="Filter by event slug"),
    condition_id: str | None = Query(None, description="Filter by condition ID"),
    tag: str | None = Query(None, description="Filter by tag"),
):
    """List alerts ordered by composite score, with optional filters."""
    offset = (page - 1) * per_page
    conditions = ["a.composite_score >= %s"]
    params: list = [min_score]

    if wallet:
        conditions.append("a.wallet = %s")
        params.append(wallet.lower())

    if condition_id:
        conditions.append("a.condition_id = %s")
        params.append(condition_id)

    if event_slug:
        conditions.append("a.event_slug = %s")
        params.append(event_slug)

    if tag:
        conditions.append("a.tags::jsonb ? %s")
        params.append(tag)

    if strategy:
        conditions.append(
            "EXISTS (SELECT 1 FROM alert_signals s WHERE s.alert_id = a.id AND s.strategy = %s)"
        )
        params.append(strategy)

    where = " AND ".join(conditions)

    with db() as conn:
        cur = conn.cursor()

        cur.execute(f"SELECT COUNT(*) as cnt FROM alerts a WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        cur.execute(
            f"""SELECT a.*, wp.win_rate, wp.total_pnl
                FROM alerts a
                LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
                WHERE {where}
                ORDER BY a.composite_score DESC, a.scanned_at DESC
                LIMIT %s OFFSET %s""",
            params + [per_page, offset],
        )
        rows = cur.fetchall()

    return PaginatedAlerts(
        alerts=[_alert_from_row(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


@app.get("/api/alerts/by-market", response_model=PaginatedMarkets)
def list_alerts_by_market(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0),
    strategy: str | None = Query(None),
    wallet: str | None = Query(None),
    event_slug: str | None = Query(None),
    tag: str | None = Query(None),
):
    """List alerts grouped by market (condition_id)."""
    conditions = [
        "a.composite_score >= %s",
        "(a.end_date IS NULL OR a.end_date > NOW())",
    ]
    params: list = [min_score]

    if wallet:
        conditions.append("a.wallet = %s")
        params.append(wallet.lower())
    if event_slug:
        conditions.append("a.event_slug = %s")
        params.append(event_slug)
    if tag:
        conditions.append("a.tags::jsonb ? %s")
        params.append(tag)
    if strategy:
        conditions.append(
            "EXISTS (SELECT 1 FROM alert_signals s WHERE s.alert_id = a.id AND s.strategy = %s)"
        )
        params.append(strategy)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    with db() as conn:
        cur = conn.cursor()

        # Count distinct markets
        cur.execute(
            f"""SELECT COUNT(DISTINCT a.condition_id) as cnt
                FROM alerts a WHERE {where} AND a.condition_id IS NOT NULL""",
            params,
        )
        total = cur.fetchone()["cnt"]

        # Get paginated market groups
        cur.execute(
            f"""SELECT a.condition_id,
                       MAX(a.market_title) as market_title,
                       MAX(a.market_url) as market_url,
                       MAX(a.event_slug) as event_slug,
                       MAX(a.end_date) as end_date,
                       SUM(a.total_usd) as total_usd,
                       COUNT(*) as alert_count,
                       MAX(a.composite_score) as max_score,
                       MAX(a.scanned_at) as scanned_at
                FROM alerts a
                WHERE {where} AND a.condition_id IS NOT NULL
                GROUP BY a.condition_id
                ORDER BY max_score DESC, scanned_at DESC
                LIMIT %s OFFSET %s""",
            params + [per_page, offset],
        )
        market_rows = cur.fetchall()

        # Fetch alerts for each market group
        markets = []
        for mrow in market_rows:
            cid = mrow["condition_id"]
            cur.execute(
                f"""SELECT a.*,
                           wp.win_rate,
                           wp.total_pnl,
                           COALESCE(
                               (SELECT MAX(t.trade_timestamp)
                                FROM alert_trades t
                                WHERE t.alert_id = a.id),
                               a.scanned_at
                           ) AS latest_trade_at
                    FROM alerts a
                    LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
                    WHERE a.condition_id = %s AND {where}
                    ORDER BY latest_trade_at DESC""",
                [cid] + params,
            )
            alert_rows = cur.fetchall()

            # Collect union of tags
            all_tags: list[str] = []
            parsed_alerts = []
            for r in alert_rows:
                alert_out = _alert_from_row(r)
                parsed_alerts.append(alert_out)
                for t in alert_out.tags:
                    if t not in all_tags:
                        all_tags.append(t)

            markets.append(
                MarketGroup(
                    condition_id=cid,
                    market_title=mrow["market_title"],
                    market_url=mrow["market_url"],
                    event_slug=mrow["event_slug"],
                    end_date=mrow["end_date"],
                    total_usd=mrow["total_usd"],
                    alert_count=mrow["alert_count"],
                    max_score=mrow["max_score"],
                    tags=all_tags,
                    scanned_at=mrow["scanned_at"],
                    alerts=parsed_alerts,
                )
            )

    return PaginatedMarkets(
        markets=markets,
        total=total,
        page=page,
        per_page=per_page,
    )


@app.get("/api/alerts/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: int):
    """Get a single alert with its trades and signals."""
    with db() as conn:
        cur = conn.cursor()

        cur.execute(
            """SELECT a.*, wp.win_rate, wp.total_pnl
               FROM alerts a
               LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
               WHERE a.id = %s""",
            (alert_id,),
        )
        alert_row = cur.fetchone()
        if not alert_row:
            raise HTTPException(status_code=404, detail="Alert not found")

        cur.execute(
            "SELECT * FROM alert_trades WHERE alert_id = %s ORDER BY usd_value DESC",
            (alert_id,),
        )
        trades = [TradeOut(**r) for r in cur.fetchall()]

        cur.execute(
            "SELECT * FROM alert_signals WHERE alert_id = %s ORDER BY severity DESC",
            (alert_id,),
        )
        signals = [SignalOut(**r) for r in cur.fetchall()]

    data = dict(alert_row)
    raw = data.pop("tags", "[]") or "[]"
    data["tags"] = json.loads(raw) if isinstance(raw, str) else raw
    raw_bullets = data.pop("llm_bullets", "[]") or "[]"
    data["llm_bullets"] = json.loads(raw_bullets) if isinstance(raw_bullets, str) else raw_bullets
    raw_copy = data.pop("llm_copy_action", "{}") or "{}"
    data["llm_copy_action"] = json.loads(raw_copy) if isinstance(raw_copy, str) else raw_copy
    return AlertDetail(**data, trades=trades, signals=signals)


@app.get("/api/wallets/{wallet_address}", response_model=WalletProfileOut)
def get_wallet(wallet_address: str):
    """Get wallet profile and stats."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM wallet_profiles WHERE wallet = %s",
            (wallet_address.lower(),),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Wallet not found")

    return WalletProfileOut(**row)


@app.get("/api/strategies")
def list_strategies():
    """List all strategies that have produced signals, with counts."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT strategy, COUNT(*) as signal_count, AVG(severity) as avg_severity
               FROM alert_signals
               GROUP BY strategy
               ORDER BY signal_count DESC"""
        )
        return cur.fetchall()


@app.get("/api/tags")
def list_tags():
    """Return top 10 tags using greedy set-cover for maximum diversity.

    Instead of just picking the 10 most frequent tags (which often overlap,
    e.g. "NCAA" and "NCAA Basketball" cover the same alerts), we greedily
    pick the tag that covers the most *uncovered* alerts each round.
    """
    with db() as conn:
        cur = conn.cursor()
        # Build tag -> set of alert IDs
        cur.execute(
            """SELECT tag, array_agg(id) as alert_ids
               FROM alerts, jsonb_array_elements_text(tags::jsonb) AS tag
               GROUP BY tag"""
        )
        tag_alerts = {r["tag"]: set(r["alert_ids"]) for r in cur.fetchall()}

    if not tag_alerts:
        return []

    # Greedy set-cover: pick tag covering most uncovered alerts each round
    selected = []
    covered = set()
    for _ in range(10):
        if not tag_alerts:
            break
        best_tag = max(tag_alerts, key=lambda t: len(tag_alerts[t] - covered))
        new_covered = tag_alerts.pop(best_tag)
        marginal = len(new_covered - covered)
        if marginal == 0:
            break
        covered |= new_covered
        selected.append({"tag": best_tag, "alert_count": len(new_covered)})

    return selected


# ---------------------------------------------------------------------------
# Live market data (proxied from Polymarket APIs)
# ---------------------------------------------------------------------------

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Simple in-memory cache: key -> (expiry_ts, data)
_live_cache: dict[str, tuple[float, LiveMarketData]] = {}
_LIVE_CACHE_TTL = 30  # seconds


def _fetch_live_market(condition_id: str) -> LiveMarketData:
    """Fetch live prices from Gamma + CLOB APIs for a market."""
    # 1. Get market metadata from Gamma (token IDs, outcomes, volume)
    gamma_resp = _requests.get(
        f"{GAMMA_API}/markets",
        params={"condition_ids": condition_id},
        timeout=10,
    )
    gamma_resp.raise_for_status()
    markets = gamma_resp.json()
    if not markets:
        return LiveMarketData(condition_id=condition_id)

    market = markets[0]
    raw_outcomes = market.get("outcomes", "[]")
    raw_token_ids = market.get("clobTokenIds", "[]")
    outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
    token_ids = json.loads(raw_token_ids) if isinstance(raw_token_ids, str) else raw_token_ids

    if not outcomes or not token_ids or len(outcomes) != len(token_ids):
        # Fall back to outcomePrices from Gamma
        raw_prices = market.get("outcomePrices", "[]")
        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
        outcome_prices = [
            OutcomePrice(
                name=outcomes[i] if i < len(outcomes) else f"Outcome {i}",
                token_id=token_ids[i] if i < len(token_ids) else "",
                price=float(prices[i]) if i < len(prices) else 0,
            )
            for i in range(len(prices))
        ]
        return LiveMarketData(
            condition_id=condition_id,
            outcomes=outcome_prices,
            volume_24h=_safe_float(market.get("volume24hr")),
            liquidity=_safe_float(market.get("liquidity")),
            description=market.get("description"),
        )

    # 2. Get live midpoints from CLOB API (batch)
    try:
        clob_resp = _requests.post(
            f"{CLOB_API}/midpoints",
            json={"token_ids": token_ids},
            timeout=10,
        )
        clob_resp.raise_for_status()
        midpoints = clob_resp.json()  # dict: token_id -> midpoint string
    except _requests.RequestException:
        # Fall back to Gamma outcomePrices
        midpoints = {}

    # Build outcome prices — prefer CLOB midpoint, fall back to Gamma
    raw_prices = market.get("outcomePrices", "[]")
    gamma_prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices

    outcome_prices = []
    for i, name in enumerate(outcomes):
        tid = token_ids[i] if i < len(token_ids) else ""
        # CLOB midpoint (most accurate live price)
        mid = midpoints.get(tid)
        if mid is not None:
            price = float(mid)
        elif i < len(gamma_prices):
            price = float(gamma_prices[i])
        else:
            price = 0
        outcome_prices.append(OutcomePrice(name=name, token_id=tid, price=price))

    return LiveMarketData(
        condition_id=condition_id,
        outcomes=outcome_prices,
        volume_24h=_safe_float(market.get("volume24hr")),
        liquidity=_safe_float(market.get("liquidity")),
        description=market.get("description"),
    )


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


@app.get("/api/market/{condition_id}/live", response_model=LiveMarketData)
def get_market_live(condition_id: str):
    """Get live market prices from Polymarket CLOB API.

    Returns current midpoint prices for each outcome, plus market metadata.
    Cached for 30 seconds to avoid hammering upstream APIs."""
    now = _time.time()
    cached = _live_cache.get(condition_id)
    if cached and cached[0] > now:
        return cached[1]

    try:
        data = _fetch_live_market(condition_id)
    except _requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Upstream API error: {e}")

    _live_cache[condition_id] = (now + _LIVE_CACHE_TTL, data)
    return data


@app.get("/api/health")
def health():
    """Health check."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM alerts")
        count = cur.fetchone()["cnt"]
    return {"status": "ok", "alert_count": count}
