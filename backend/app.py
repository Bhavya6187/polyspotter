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
    HolderEntry,
    MarketHoldersData,
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


POLYMARKET_DATA_API = "https://data-api.polymarket.com"


def _fetch_closed_positions(wallet: str) -> list[dict]:
    """Fetch the most recent closed positions from Polymarket Data API (single call, max 50)."""
    try:
        resp = _requests.get(
            f"{POLYMARKET_DATA_API}/closed-positions",
            params={"user": wallet, "limit": 50,
                    "sortBy": "timestamp", "sortDir": "desc"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def _positions_to_bets(positions: list[dict]) -> list[WalletBet]:
    """Convert raw API positions to WalletBet models."""
    bets = []
    for pos in positions:
        cur_price = pos.get("curPrice")
        won = cur_price == 1.0 if cur_price is not None else None
        bets.append(WalletBet(
            market_title=pos.get("title"),
            condition_id=pos.get("conditionId"),
            won=won,
            outcome=pos.get("outcome"),
            entry_price=pos.get("avgPrice"),
            resolution_price=cur_price,
            pnl_usd=pos.get("realizedPnl"),
            total_usd=pos.get("totalBought"),
            resolved_at=None,
        ))
    return bets


def _compute_wallet_stats(positions: list[dict]) -> dict:
    """Compute wallet profile stats from raw closed positions."""
    wins = sum(1 for p in positions if p.get("curPrice") == 1.0)
    losses = sum(1 for p in positions if p.get("curPrice") == 0.0)
    resolved = wins + losses
    win_rate = wins / resolved if resolved > 0 else None
    total_pnl = sum(p.get("realizedPnl", 0) or 0 for p in positions)
    total_invested = sum(p.get("totalBought", 0) or 0 for p in positions)
    avg_win_price = None
    win_prices = [p.get("avgPrice") for p in positions
                  if p.get("curPrice") == 1.0 and p.get("avgPrice") is not None]
    if win_prices:
        avg_win_price = sum(win_prices) / len(win_prices)

    return {
        "total_positions": len(positions),
        "closed_positions": resolved,
        "wins": wins,
        "losses": losses,
        "total_pnl": total_pnl,
        "total_invested": total_invested,
        "avg_win_price": avg_win_price,
        "win_rate": win_rate,
    }


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
    data.setdefault("total_invested", None)
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
                    times_flagged, first_seen_at, current_streak, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
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
                    current_streak = EXCLUDED.current_streak,
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
                    wp.current_streak,
                ),
            )

        # Ingest price candles
        candles_count = 0
        for pc in payload.price_candles:
            cur.execute("""
                INSERT INTO price_candles (condition_id, token_id, outcome, t, p)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (token_id, t) DO UPDATE SET p = EXCLUDED.p
            """, (pc.condition_id, pc.token_id, pc.outcome, pc.t, pc.p))
            candles_count += 1

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

        # Cleanup old price candles (keep only 7 days)
        cur.execute("DELETE FROM price_candles WHERE created_at < NOW() - INTERVAL '7 days'")

    return {
        "status": "ok",
        "inserted_alerts": inserted_alerts,
        "updated_alerts": updated_alerts,
        "skipped_alerts": skipped_alerts,
        "wallet_profiles": len(payload.wallet_profiles),
        "price_candles": candles_count,
        "theses": theses_count,
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
        conditions.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t WHERE LOWER(t) = LOWER(%s))"
        )
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
            f"""SELECT a.*, wp.win_rate, wp.total_pnl, wp.total_invested
                FROM alerts a
                LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
                WHERE {where}
                ORDER BY a.created_at DESC, a.composite_score DESC
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
    resolves_within: str | None = Query(None, description="Filter by resolution window: 6h, 24h, 7d"),
):
    """List alerts grouped by market (condition_id)."""
    conditions = [
        "a.composite_score >= %s",
        "(a.end_date IS NULL OR a.end_date > NOW())",
    ]
    params: list = [min_score]

    resolve_hours = {"6h": 6, "24h": 24, "7d": 168}.get(resolves_within)
    if resolve_hours is not None:
        conditions.append("a.end_date IS NOT NULL AND a.end_date <= NOW() + make_interval(hours => %s)")
        params.append(resolve_hours)

    if wallet:
        conditions.append("a.wallet = %s")
        params.append(wallet.lower())
    if event_slug:
        conditions.append("a.event_slug = %s")
        params.append(event_slug)
    if tag:
        conditions.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t WHERE LOWER(t) = LOWER(%s))"
        )
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

        # Count distinct markets and total alerts
        cur.execute(
            f"""SELECT COUNT(DISTINCT a.condition_id) as cnt,
                       COUNT(*) as alert_cnt
                FROM alerts a WHERE {where} AND a.condition_id IS NOT NULL""",
            params,
        )
        counts = cur.fetchone()
        total = counts["cnt"]
        total_alerts = counts["alert_cnt"]

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
                           wp.total_invested,
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
        total_alerts=total_alerts,
        page=page,
        per_page=per_page,
    )


@app.get("/api/alerts/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: int):
    """Get a single alert with its trades and signals."""
    with db() as conn:
        cur = conn.cursor()

        cur.execute(
            """SELECT a.*, wp.win_rate, wp.total_pnl, wp.total_invested
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


@app.get("/api/wallets/{wallet_address}", response_model=WalletProfileDetailOut)
def get_wallet(wallet_address: str):
    """Get wallet profile computed live from Polymarket Data API."""
    wallet = wallet_address.lower()

    # Fetch most recent closed positions from live API (single call, max 50)
    positions = _fetch_closed_positions(wallet)
    if not positions:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # Compute stats on the fly
    stats = _compute_wallet_stats(positions)

    # Only times_flagged and recent_alerts come from our DB
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT times_flagged FROM wallet_profiles WHERE wallet = %s", (wallet,))
        wp_row = cur.fetchone()
        times_flagged = wp_row["times_flagged"] if wp_row else 0

        cur.execute("""
            SELECT a.id, a.market_title, a.composite_score, a.total_usd,
                   a.llm_headline, a.created_at, a.condition_id
            FROM alerts a
            WHERE a.wallet = %s
            ORDER BY a.created_at DESC
            LIMIT 5
        """, (wallet,))
        recent_alerts = [WalletRecentAlert(**arow) for arow in cur.fetchall()]

    # Build response — bet_history is the most recent 20 positions
    bet_history = _positions_to_bets(positions[:20])

    return WalletProfileDetailOut(
        wallet=wallet,
        total_positions=stats["total_positions"],
        closed_positions=stats["closed_positions"],
        wins=stats["wins"],
        losses=stats["losses"],
        total_pnl=stats["total_pnl"],
        total_invested=stats["total_invested"],
        avg_win_price=stats["avg_win_price"],
        win_rate=stats["win_rate"],
        times_flagged=times_flagged,
        recent_alerts=recent_alerts,
        bet_history=bet_history,
    )


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


@app.get("/api/spotlight")
def get_spotlight():
    """Top 7 unresolved alerts by composite score, enriched with wallet count and candles."""
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
            LIMIT 7
        """)
        rows = cur.fetchall()

        results = []
        for row in rows:
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


@app.get("/api/resolving-soon")
def get_resolving_soon():
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


def _thesis_from_row(row: dict) -> dict:
    """Build a thesis dict from a DB row, parsing JSON markets."""
    markets = row["markets"]
    if isinstance(markets, str):
        try:
            markets = json.loads(markets)
        except (json.JSONDecodeError, TypeError):
            markets = []
    return {
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
    }


@app.get("/api/theses")
def list_theses(page: int = Query(1, ge=1), per_page: int = Query(10, ge=1, le=50)):
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

        theses = [_thesis_from_row(row) for row in rows]

        return {"theses": theses, "total": total, "page": page, "per_page": per_page}


@app.get("/api/theses/{thesis_id}")
def get_thesis(thesis_id: int):
    """Get a single thesis by ID."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT wt.*, wp.win_rate, wp.total_pnl, wp.total_invested
            FROM wallet_theses wt
            LEFT JOIN wallet_profiles wp ON wt.wallet = wp.wallet
            WHERE wt.id = %s
        """, (thesis_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Thesis not found")
        return _thesis_from_row(row)


# ---------------------------------------------------------------------------
# Live market data (proxied from Polymarket APIs)
# ---------------------------------------------------------------------------

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Simple in-memory cache: key -> (expiry_ts, data)
_live_cache: dict[str, tuple[float, LiveMarketData]] = {}
_LIVE_CACHE_TTL = 30  # seconds

_price_history_cache: dict[str, tuple[float, "PriceHistoryData"]] = {}
_PRICE_HISTORY_CACHE_TTL = 60  # seconds

_holders_cache: dict[str, tuple[float, "MarketHoldersData"]] = {}
_HOLDERS_CACHE_TTL = 300  # 5 minutes


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

    # Fetch spread for the leading outcome
    spread = None
    if outcome_prices:
        leading_token = max(outcome_prices, key=lambda o: o.price).token_id
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

    return LiveMarketData(
        condition_id=condition_id,
        outcomes=outcome_prices,
        volume_24h=_safe_float(market.get("volume24hr")),
        liquidity=_safe_float(market.get("liquidity")),
        description=market.get("description"),
        spread=spread,
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

    raw.sort(key=lambda p: abs(float(p.get("size", 0))), reverse=True)
    raw = raw[:10]

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


@app.get("/api/market/{condition_id}/theses")
def get_market_theses(condition_id: str):
    """Get cross-market theses from wallets active in this market."""
    with db() as conn:
        cur = conn.cursor()
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


@app.get("/api/market/resolve/{partial_id}")
def resolve_condition_id(partial_id: str):
    """Resolve a partial condition_id prefix to the full condition_id."""
    partial = partial_id.lower()
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT condition_id FROM alerts WHERE condition_id LIKE %s LIMIT 1",
            (f"{partial}%",),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Market not found")
    return {"condition_id": row["condition_id"]}


@app.get("/api/health")
def health():
    """Health check."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM alerts")
        count = cur.fetchone()["cnt"]
    return {"status": "ok", "alert_count": count}
