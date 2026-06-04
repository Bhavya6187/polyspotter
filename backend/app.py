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
import os
import time as _time
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from dotenv import load_dotenv
import requests as _requests
from cachetools import LRUCache

# Load .env from project root (one level up from backend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from database import get_conn, init_db
from events import get_event_or_fetch
import sports
from sports.base import OverlayResponse
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
    ArticleOut,
    ArticleListItem,
    EventOut,
    EventTag,
    EventDetail,
    EventMarketSummary,
    EventStats,
    EventTopWallet,
    EventRelatedArticle,
    EventListItem,
    PaginatedEvents,
    ThesisOut,
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
        avg_price = pos.get("avgPrice")
        cur_price = pos.get("curPrice")
        realized_pnl = pos.get("realizedPnl")
        total_bought = pos.get("totalBought")

        # Three-state, aligned with wallet stats: only mark won True/False when
        # the market actually resolved (curPrice ∈ {0, 1}); None means the
        # wallet exited mid-market — pnl_usd communicates the trade outcome.
        if cur_price == 1.0:
            won = True
        elif cur_price == 0.0:
            won = False
        else:
            won = None

        # For resolved positions the second-leg price is the resolution price;
        # for exited positions it's the effective sell price implied by the
        # realized P&L (curPrice is the live mid, not the wallet's exit).
        if cur_price in (0.0, 1.0):
            exit_price = cur_price
        elif (avg_price is not None and realized_pnl is not None
              and total_bought is not None and total_bought > 0):
            exit_price = avg_price * (1 + realized_pnl / total_bought)
        else:
            exit_price = None

        bets.append(WalletBet(
            market_title=pos.get("title"),
            condition_id=pos.get("conditionId"),
            won=won,
            outcome=pos.get("outcome"),
            entry_price=avg_price,
            resolution_price=exit_price,
            pnl_usd=realized_pnl,
            total_usd=total_bought,
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
                        event_slug, market_url, market_image, market_description,
                        wallet, total_usd, trade_count,
                        cluster_headline, end_date, game_start_time, event_end_estimate,
                        llm_headline, llm_summary,
                        llm_bullets, llm_copy_action, scanned_at, dedup_key)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (dedup_key) DO UPDATE SET
                        composite_score = EXCLUDED.composite_score,
                        tags = EXCLUDED.tags,
                        total_usd = EXCLUDED.total_usd,
                        trade_count = EXCLUDED.trade_count,
                        cluster_headline = EXCLUDED.cluster_headline,
                        end_date = EXCLUDED.end_date,
                        game_start_time = EXCLUDED.game_start_time,
                        event_end_estimate = EXCLUDED.event_end_estimate,
                        llm_headline = EXCLUDED.llm_headline,
                        llm_summary = EXCLUDED.llm_summary,
                        llm_bullets = EXCLUDED.llm_bullets,
                        llm_copy_action = EXCLUDED.llm_copy_action,
                        market_image = COALESCE(EXCLUDED.market_image, alerts.market_image),
                        market_description = COALESCE(EXCLUDED.market_description, alerts.market_description),
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
                        alert.market_image,
                        alert.market_description,
                        alert.wallet,
                        alert.total_usd,
                        alert.trade_count,
                        alert.cluster_headline,
                        alert.end_date,
                        alert.game_start_time,
                        alert.event_end_estimate,
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

        # Touch placeholder rows for every event_slug seen in this batch.
        # Hydration (Gamma) and SEO generation (LLM, both market & event)
        # run out-of-process in backend/seo_worker.py — they were removed
        # from the request path because external calls inside the DB
        # transaction caused idle-in-transaction orphans on Postgres.
        distinct_event_slugs = sorted({
            a.event_slug for a in payload.alerts if a.event_slug
        })
        events_touched = 0
        if distinct_event_slugs:
            cur.executemany(
                "INSERT INTO events (event_slug) VALUES (%s) ON CONFLICT DO NOTHING",
                [(s,) for s in distinct_event_slugs],
            )
            events_touched = cur.rowcount

    return {
        "status": "ok",
        "inserted_alerts": inserted_alerts,
        "updated_alerts": updated_alerts,
        "skipped_alerts": skipped_alerts,
        "wallet_profiles": len(payload.wallet_profiles),
        "price_candles": candles_count,
        "theses": theses_count,
        "events_touched": events_touched,
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
    include_resolved: bool = Query(False, description="Include resolved/expired markets"),
    q: str | None = Query(None, description="Search market titles (fuzzy match)"),
    group_events: bool = Query(
        False,
        description="When true, collapse alerts that share an event_slug with 2+ "
        "child markets into a single event-level row. Standalone markets and "
        "single-market events render as before. Used by home + tag pages so the "
        "Bayern–PSG match shows as one card instead of three.",
    ),
):
    """List alerts grouped by market (condition_id), or smart-grouped by event when group_events=true."""
    conditions = [
        "a.composite_score >= %s",
    ]
    if not include_resolved:
        conditions.append("(a.end_date IS NULL OR a.end_date > NOW())")
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
    q_clean = q.strip() if q else None
    q_like = f"%{q_clean}%" if q_clean else None
    if q_clean:
        conditions.append(
            "(word_similarity(%s, a.market_title) > 0.2 "
            "OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t WHERE t ILIKE %s))"
        )
        params.append(q_clean)
        params.append(q_like)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    # When group_events=true we wrap the SELECT in a CTE that identifies
    # event_slugs covering 2+ child markets in this filter, then groups by
    # COALESCE(event_slug-when-multi-market, condition_id). Single-market
    # events and standalone markets fall through to the per-market path
    # unchanged. Cap event-card alerts at this many to keep cards compact.
    EVENT_ALERTS_LIMIT = 5

    with db() as conn:
        cur = conn.cursor()

        # Relevance / freshness ordering — same logic for both grouping modes.
        if q_clean:
            order_clause = (
                "MAX(word_similarity(%s, a.market_title) "
                "+ CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t WHERE t ILIKE %s) THEN 0.3 ELSE 0 END) DESC, "
            )
            order_params = [q_clean, q_like]
        elif include_resolved:
            order_clause = "CASE WHEN MAX(a.end_date) IS NULL OR MAX(a.end_date) > NOW() THEN 0 ELSE 1 END, "
            order_params = []
        else:
            order_clause = ""
            order_params = []

        if not group_events:
            # ------------ Legacy market-only grouping ------------
            cur.execute(
                f"""SELECT COUNT(DISTINCT a.condition_id) as cnt,
                           COUNT(*) as alert_cnt
                    FROM alerts a WHERE {where} AND a.condition_id IS NOT NULL""",
                params,
            )
            counts = cur.fetchone()
            total = counts["cnt"]
            total_alerts = counts["alert_cnt"]

            cur.execute(
                f"""SELECT a.condition_id,
                           MAX(a.market_title) as market_title,
                           MAX(a.market_url) as market_url,
                           MAX(a.market_image) as market_image,
                           MAX(a.event_slug) as event_slug,
                           MAX(a.end_date) as end_date,
                           SUM(a.total_usd) as total_usd,
                           COUNT(*) as alert_count,
                           MAX(a.composite_score) as max_score,
                           MAX(a.scanned_at) as scanned_at,
                           MAX(a.seo_title) as seo_title,
                           MAX(a.seo_description) as seo_description,
                           MAX(a.seo_summary) as seo_summary,
                           MAX(a.seo_faqs) as seo_faqs
                    FROM alerts a
                    WHERE {where} AND a.condition_id IS NOT NULL
                    GROUP BY a.condition_id
                    ORDER BY {order_clause}scanned_at DESC, max_score DESC
                    LIMIT %s OFFSET %s""",
                params + order_params + [per_page, offset],
            )
            market_rows = [
                {**dict(r), "is_event": False, "event_title": None, "event_image": None, "market_count": 1}
                for r in cur.fetchall()
            ]
        else:
            # ------------ Smart event-aware grouping ------------
            # Step 1: find slugs whose alerts (in this filter) cover 2+ markets.
            mm_sql = f"""
                SELECT a.event_slug
                FROM alerts a
                WHERE {where}
                  AND a.condition_id IS NOT NULL
                  AND a.event_slug IS NOT NULL
                GROUP BY a.event_slug
                HAVING COUNT(DISTINCT a.condition_id) >= 2
            """

            # Step 2: count distinct groups (events + standalone markets) for pagination.
            cur.execute(
                f"""WITH multi_markets AS ({mm_sql})
                    SELECT COUNT(*) AS cnt FROM (
                        SELECT DISTINCT
                          CASE WHEN mm.event_slug IS NOT NULL
                               THEN a.event_slug ELSE a.condition_id END AS group_key
                        FROM alerts a
                        LEFT JOIN multi_markets mm ON mm.event_slug = a.event_slug
                        WHERE {where} AND a.condition_id IS NOT NULL
                    ) sub""",
                params + params,  # `where` appears twice in this query
            )
            total = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                f"""SELECT COUNT(*) AS alert_cnt FROM alerts a
                    WHERE {where} AND a.condition_id IS NOT NULL""",
                params,
            )
            total_alerts = int((cur.fetchone() or {}).get("alert_cnt") or 0)

            # Step 3: paginated group rows.
            cur.execute(
                f"""WITH multi_markets AS ({mm_sql})
                    SELECT
                      (mm.event_slug IS NOT NULL) AS is_event,
                      COALESCE(mm.event_slug, a.condition_id) AS group_key,
                      MAX(a.condition_id) AS condition_id,
                      MAX(a.event_slug)   AS event_slug,
                      MAX(e.title)        AS event_title,
                      MAX(e.image)        AS event_image,
                      MAX(a.market_title) AS market_title,
                      MAX(a.market_url)   AS market_url,
                      MAX(a.market_image) AS market_image,
                      MAX(a.end_date)     AS end_date,
                      SUM(a.total_usd)    AS total_usd,
                      COUNT(*)            AS alert_count,
                      COUNT(DISTINCT a.condition_id) AS market_count,
                      MAX(a.composite_score) AS max_score,
                      MAX(a.scanned_at)   AS scanned_at,
                      MAX(a.seo_title)    AS seo_title,
                      MAX(a.seo_description) AS seo_description,
                      MAX(a.seo_summary)  AS seo_summary,
                      MAX(a.seo_faqs)     AS seo_faqs
                    FROM alerts a
                    LEFT JOIN multi_markets mm ON mm.event_slug = a.event_slug
                    LEFT JOIN events e ON e.event_slug = a.event_slug
                    WHERE {where} AND a.condition_id IS NOT NULL
                    GROUP BY group_key, is_event
                    ORDER BY {order_clause}scanned_at DESC, max_score DESC
                    LIMIT %s OFFSET %s""",
                params + params + order_params + [per_page, offset],
            )
            market_rows = [dict(r) for r in cur.fetchall()]

        # Fetch alerts for each group. Event rows query by event_slug + LIMIT;
        # market rows keep their existing per-condition_id query (full set).
        markets = []
        for mrow in market_rows:
            is_event = bool(mrow.get("is_event"))
            if is_event:
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
                        WHERE a.event_slug = %s AND {where}
                        ORDER BY a.composite_score DESC, latest_trade_at DESC
                        LIMIT %s""",
                    [mrow["event_slug"]] + params + [EVENT_ALERTS_LIMIT],
                )
            else:
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
                    [mrow["condition_id"]] + params,
                )
            alert_rows = cur.fetchall()

            all_tags: list[str] = []
            parsed_alerts = []
            for r in alert_rows:
                alert_out = _alert_from_row(r)
                parsed_alerts.append(alert_out)
                for t in alert_out.tags:
                    if t not in all_tags:
                        all_tags.append(t)

            raw_seo_faqs = mrow.get("seo_faqs") or "[]"
            try:
                seo_faqs = json.loads(raw_seo_faqs) if isinstance(raw_seo_faqs, str) else raw_seo_faqs
            except (json.JSONDecodeError, TypeError):
                seo_faqs = []

            markets.append(
                MarketGroup(
                    condition_id=mrow["condition_id"],
                    market_title=mrow["market_title"],
                    market_url=mrow["market_url"],
                    market_image=mrow["market_image"],
                    event_slug=mrow["event_slug"],
                    end_date=mrow["end_date"],
                    total_usd=mrow["total_usd"],
                    alert_count=mrow["alert_count"],
                    max_score=mrow["max_score"],
                    tags=all_tags,
                    scanned_at=mrow["scanned_at"],
                    seo_title=mrow.get("seo_title"),
                    seo_description=mrow.get("seo_description"),
                    seo_summary=mrow.get("seo_summary"),
                    seo_faqs=seo_faqs,
                    alerts=parsed_alerts,
                    is_event=is_event,
                    event_title=mrow.get("event_title"),
                    event_image=mrow.get("event_image"),
                    market_count=int(mrow.get("market_count") or 1),
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


@app.get("/api/wallets/top")
def top_wallets(limit: int = Query(50, ge=1, le=200)):
    """Return top wallet addresses by alert count (for sitemap)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT wallet, COUNT(*) as alert_count
            FROM alerts
            WHERE wallet IS NOT NULL
            GROUP BY wallet
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    return {"wallets": [{"wallet": r["wallet"], "alert_count": r["alert_count"]} for r in rows]}


@app.get("/api/wallets/sitemap")
def wallets_sitemap(
    page: int = Query(1, ge=1),
    per_page: int = Query(1000, ge=1, le=5000),
):
    """Return paginated wallet addresses for sitemap generation.

    Includes every wallet that appears in at least one alert — i.e. has
    confirmed Polymarket activity, so its profile page won't 404. Ordered by
    alert_count DESC so the first pages contain the highest-value wallets and
    can be ranked first by Google even if later pages time out.
    """
    offset = (page - 1) * per_page
    with db() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(DISTINCT wallet) AS total
            FROM alerts
            WHERE wallet IS NOT NULL
        """)
        total = cur.fetchone()["total"]

        cur.execute("""
            SELECT wallet,
                   COUNT(*)        AS alert_count,
                   MAX(scanned_at) AS last_seen
            FROM alerts
            WHERE wallet IS NOT NULL
            GROUP BY wallet
            ORDER BY COUNT(*) DESC, wallet ASC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        rows = cur.fetchall()

    return {
        "wallets": [
            {
                "wallet": r["wallet"],
                "alert_count": r["alert_count"],
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@app.get("/api/wallets/{wallet_address}", response_model=WalletProfileDetailOut)
def get_wallet(wallet_address: str):
    """Get wallet profile with stats from DB (accumulated by seeder) and
    bet_history from live Polymarket Data API."""
    wallet = wallet_address.lower()

    # Fetch recent closed positions for bet_history display
    positions = _fetch_closed_positions(wallet)
    if not positions:
        raise HTTPException(status_code=404, detail="Wallet not found")

    with db() as conn:
        cur = conn.cursor()

        # Use wallet_profiles from DB — seeder accumulates positions over
        # multiple runs, giving more accurate stats than the Data API's
        # limited retention window (which may only return the last 50).
        cur.execute(
            """SELECT total_positions, closed_positions, wins, losses,
                      total_pnl, total_invested, avg_win_price, win_rate,
                      times_flagged
               FROM wallet_profiles WHERE wallet = %s""",
            (wallet,),
        )
        wp_row = cur.fetchone()

        if wp_row:
            stats = {
                "total_positions": wp_row["total_positions"],
                "closed_positions": wp_row["closed_positions"],
                "wins": wp_row["wins"],
                "losses": wp_row["losses"],
                "total_pnl": wp_row["total_pnl"],
                "total_invested": wp_row["total_invested"],
                "avg_win_price": wp_row["avg_win_price"],
                "win_rate": wp_row["win_rate"],
            }
            times_flagged = wp_row["times_flagged"] or 0
        else:
            # Wallet not in our DB yet — fall back to live computation
            stats = _compute_wallet_stats(positions)
            times_flagged = 0

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


TAG_DESCRIPTIONS = {
    "Sports": "Track smart money flowing into sports prediction markets on Polymarket. PolySpotter surfaces large bets from sharp bettors across NFL, NBA, MLB, soccer, tennis, and more — highlighting coordinated flow, whale positions, and high-conviction wagers.",
    "Politics": "Monitor sharp bettor activity in political prediction markets. From elections to policy decisions, see where informed money is positioning on Polymarket's political events.",
    "Geopolitics": "Follow whale trades in geopolitical prediction markets on Polymarket. Track sharp bettors wagering on international diplomacy, conflicts, treaties, and global power shifts.",
    "Crypto": "Follow whale trades in crypto prediction markets on Polymarket. Track sharp bettors wagering on Bitcoin price targets, Ethereum milestones, DeFi outcomes, and regulatory decisions.",
    "Culture": "Track smart money in culture and entertainment prediction markets on Polymarket — from awards shows to viral moments and media events.",
    "Finance": "Monitor sharp bettor activity in finance prediction markets on Polymarket. Track whale trades on interest rates, economic indicators, and market events.",
    "Weather": "Follow smart money signals in weather prediction markets on Polymarket — hurricane paths, temperature records, and climate events.",
    "Soccer": "Track whale trades in soccer prediction markets on Polymarket. Sharp bettors positioning on Premier League, Champions League, La Liga, and international matches.",
}


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
    selected_tags = []
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
        desc = TAG_DESCRIPTIONS.get(best_tag) or (
            f"Notable trades and smart money alerts for {best_tag} markets on Polymarket. "
            f"Track large bets, sharp bettors, and coordinated flow."
        )
        selected_tags.append({
            "tag": best_tag,
            "alert_count": len(new_covered),
            "description": desc,
        })

    return selected_tags


@app.get("/api/spotlight")
def get_spotlight():
    """Top 7 unresolved alerts by composite score, enriched with wallet count and candles.
    Excludes markets whose latest price is near 0 or 1 (effectively settled)."""
    with db() as conn:
        cur = conn.cursor()
        # Fetch more candidates than needed so we can filter out settled markets
        # Event still pending = event_end_estimate (or end_date fallback) > NOW().
        # For sports, event_end_estimate = gameStartTime, so a game that's
        # already underway correctly drops out even though Polymarket's
        # end_date is 7 days out awaiting UMA resolution.
        cur.execute("""
            SELECT a.id, a.market_title, a.condition_id, a.event_slug,
                   a.composite_score, a.total_usd, a.end_date,
                   a.game_start_time, a.event_end_estimate,
                   a.llm_headline, a.llm_summary, a.llm_copy_action, a.market_image,
                   (SELECT COUNT(DISTINCT at2.wallet) FROM alert_trades at2 WHERE at2.alert_id = a.id) AS wallet_count,
                   wp.win_rate AS best_win_rate, wp.total_pnl AS best_total_pnl,
                   latest_candle.p AS latest_price
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON a.wallet = wp.wallet
            LEFT JOIN LATERAL (
                SELECT p FROM price_candles pc
                WHERE pc.condition_id = a.condition_id
                ORDER BY pc.t DESC
                LIMIT 1
            ) latest_candle ON TRUE
            WHERE COALESCE(a.event_end_estimate, a.end_date) IS NOT NULL
              AND COALESCE(a.event_end_estimate, a.end_date) > NOW()
              AND a.created_at > NOW() - INTERVAL '1 day'
              AND (latest_candle.p IS NULL OR (latest_candle.p > 0.03 AND latest_candle.p < 0.97))
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

            # Surface event_end_estimate as `end_date` so the frontend
            # countdown targets the actual event time; expose the true
            # resolution deadline separately for UIs that want it.
            effective = row["event_end_estimate"] or row["end_date"]
            results.append({
                "id": row["id"],
                "market_title": row["market_title"],
                "condition_id": row["condition_id"],
                "event_slug": row["event_slug"],
                "composite_score": row["composite_score"],
                "total_usd": row["total_usd"],
                "end_date": effective.isoformat() if effective else None,
                "resolution_deadline": row["end_date"].isoformat() if row["end_date"] else None,
                "game_start_time": row["game_start_time"].isoformat() if row["game_start_time"] else None,
                "llm_headline": row["llm_headline"],
                "llm_summary": row["llm_summary"],
                "llm_copy_action": copy_action,
                "wallet_count": row["wallet_count"] or 0,
                "best_win_rate": row["best_win_rate"],
                "best_total_pnl": row["best_total_pnl"],
                "candles": candles,
                "market_image": row["market_image"],
            })
        return results


_resolving_soon_cache: tuple[float, list] | None = None
_RESOLVING_SOON_TTL = 60  # seconds

# Per-condition_id Gamma status cache (gameStartTime/umaResolutionStatus/closed/
# outcomePrices). The /api/resolving-soon response is already 60s-cached, but
# this inner cache is shared with any other endpoint that wants a fresh
# "is this market actually still live?" check and outlives single-request work.
_gamma_status_cache: LRUCache = LRUCache(maxsize=2000)
_GAMMA_STATUS_TTL = 60  # seconds


def _fetch_gamma_status(condition_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch Gamma market status for the given condition_ids.

    Returns {condition_id: {closed, uma_status, prices, game_start_time}}.
    Uses an in-memory TTL cache so repeat lookups within 60s avoid Gamma calls."""
    if not condition_ids:
        return {}
    now = _time.time()
    out: dict[str, dict] = {}
    to_fetch: list[str] = []
    for cid in condition_ids:
        cached = _gamma_status_cache.get(cid)
        if cached and cached[0] > now:
            out[cid] = cached[1]
        else:
            to_fetch.append(cid)

    # Gamma's /markets hides closed markets by default, so any cid missing from
    # the first response may actually be a settled market. Retry the gap with
    # closed=true (mirroring gamma_cache.get_market_by_condition) so settled
    # games can be flagged and dropped from /top3 — otherwise zombie alerts
    # for already-resolved events leak through.
    def _ingest(markets):
        for m in markets:
            cid = m.get("conditionId") or m.get("condition_id")
            if not cid:
                continue
            try:
                prices = _parse_json_field(m, "outcomePrices")
                prices = [float(p) for p in prices] if prices else []
            except (ValueError, TypeError):
                prices = []
            info = {
                "closed": bool(m.get("closed")),
                "uma_status": (m.get("umaResolutionStatus") or "").strip(),
                "prices": prices,
                "game_start_time": m.get("gameStartTime"),
            }
            out[cid] = info
            _gamma_status_cache[cid] = (now + _GAMMA_STATUS_TTL, info)

    for attempt_params in ({}, {"closed": "true"}):
        if not to_fetch:
            break
        params = [("condition_ids", cid) for cid in to_fetch]
        params.extend(attempt_params.items())
        try:
            resp = _requests.get(f"{GAMMA_API}/markets", params=params, timeout=10)
            resp.raise_for_status()
            _ingest(resp.json())
        except Exception:
            # On Gamma failure we return whatever we already had cached and let
            # callers decide how to degrade — better than breaking the endpoint.
            pass
        to_fetch = [cid for cid in to_fetch if cid not in out]

    return out


def _is_market_settled(status: dict) -> bool:
    """True if a market is already decided per Gamma status.

    A market is "settled" when any of:
      - closed=true (trading halted),
      - umaResolutionStatus is non-empty (proposed/disputed/resolved),
      - one outcome price >= 0.98 (effectively resolved by the market)."""
    if not status:
        return False
    if status.get("closed"):
        return True
    if status.get("uma_status"):
        return True
    prices = status.get("prices") or []
    if prices and max(prices) >= 0.98:
        return True
    return False


@app.get("/api/resolving-soon")
def get_resolving_soon():
    """Next 7 resolving markets, excluding settled ones. Cached for 60s."""
    global _resolving_soon_cache
    now = _time.time()
    if _resolving_soon_cache and _resolving_soon_cache[0] > now:
        return _resolving_soon_cache[1]

    results = _fetch_resolving_soon()
    _resolving_soon_cache = (now + _RESOLVING_SOON_TTL, results)
    return results


def _fetch_resolving_soon() -> list[dict]:
    # Sort by event_end_estimate (actual event time — game start for sports,
    # endDate for everything else) so a sports game starting in 3h ranks above
    # a political market whose UMA resolution deadline is tomorrow. Fall back
    # to end_date for pre-migration rows that don't yet have event_end_estimate.
    # Pull 40 so we still have 7+ after dropping already-settled markets.
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM (
                SELECT DISTINCT ON (COALESCE(a.event_slug, a.condition_id))
                    a.id, a.condition_id, a.market_title, a.end_date,
                    a.game_start_time, a.event_end_estimate,
                    a.total_usd, a.composite_score, a.llm_copy_action, a.market_image,
                    COALESCE(a.event_end_estimate, a.end_date) AS sort_key
                FROM alerts a
                WHERE COALESCE(a.event_end_estimate, a.end_date) IS NOT NULL
                  AND COALESCE(a.event_end_estimate, a.end_date) > NOW()
                ORDER BY COALESCE(a.event_slug, a.condition_id), a.composite_score DESC
            ) sub
            ORDER BY sort_key ASC
            LIMIT 40
        """)
        rows = cur.fetchall()
    if not rows:
        return []

    # Build results
    results = []
    for row in rows:
        copy_action = row["llm_copy_action"]
        if isinstance(copy_action, str):
            try:
                copy_action = json.loads(copy_action)
            except (json.JSONDecodeError, TypeError):
                copy_action = {}
        # Countdown target: prefer event_end_estimate (event time), fall back
        # to end_date. The frontend reads `end_date` as the countdown source,
        # so surface the effective value there for backwards compatibility.
        effective = row["event_end_estimate"] or row["end_date"]
        results.append({
            "id": row["id"],
            "condition_id": row["condition_id"],
            "market_title": row["market_title"],
            "end_date": effective.isoformat() if effective else None,
            "resolution_deadline": row["end_date"].isoformat() if row["end_date"] else None,
            "game_start_time": row["game_start_time"].isoformat() if row["game_start_time"] else None,
            "total_usd": row["total_usd"],
            "composite_score": row["composite_score"],
            "dominant_side": copy_action.get("outcome") if copy_action else None,
            "market_image": row["market_image"],
        })

    # Drop markets Gamma reports as already-settled (closed / UMA proposed /
    # one outcome >= 98%). Uses the shared _gamma_status_cache.
    condition_ids = [r["condition_id"] for r in results if r["condition_id"]]
    status_by_cid = _fetch_gamma_status(condition_ids)
    if status_by_cid:
        results = [
            r for r in results
            if not _is_market_settled(status_by_cid.get(r["condition_id"], {}))
        ]

    return results[:7]


@app.get("/api/top3")
def get_top3():
    """Today's top 3 — one alert per category (HIGHEST_CONVICTION, COORDINATED_FLOW,
    TIMING_EDGE). Empty buckets are filled from remaining top scorers, keeping
    their slot's category label."""
    CATEGORY_ORDER = ["HIGHEST_CONVICTION", "COORDINATED_FLOW", "TIMING_EDGE"]

    # Conservative game-duration buffer. Most sports finish well within 3h
    # (soccer ~2h, basketball ~2.5h, esports BO3 ~3h). MLB occasionally runs
    # over but isn't typically a timing-edge candidate. This buffer keeps
    # in-progress games visible after kickoff — without it, soccer markets
    # whose `endDate == gameStartTime` vanish at the first whistle.
    LIVE_BUFFER_HOURS = 3

    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.market_title, a.condition_id, a.event_slug,
                   a.composite_score, a.total_usd, a.end_date, a.event_end_estimate,
                   a.game_start_time, a.tags,
                   a.llm_summary, a.llm_copy_action, a.market_image, a.wallet,
                   (SELECT COUNT(DISTINCT at2.wallet)
                      FROM alert_trades at2 WHERE at2.alert_id = a.id) AS wallet_count,
                   (SELECT ARRAY_AGG(DISTINCT strategy)
                      FROM alert_signals WHERE alert_id = a.id) AS strategies,
                   wp.win_rate, wp.total_pnl, wp.total_invested,
                   latest_candle.p AS latest_price,
                   market_totals.market_total_usd
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON a.wallet = wp.wallet
            LEFT JOIN LATERAL (
                SELECT p FROM price_candles pc
                WHERE pc.condition_id = a.condition_id
                ORDER BY pc.t DESC
                LIMIT 1
            ) latest_candle ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(a2.total_usd) AS market_total_usd
                FROM alerts a2
                WHERE a2.condition_id = a.condition_id
            ) market_totals ON TRUE
            WHERE (
                  -- Game-level markets stay visible during play (kickoff + 3h)
                  (a.game_start_time IS NOT NULL
                   AND a.game_start_time + INTERVAL '3 hours' > NOW())
                  -- Non-game markets fall back to the resolution deadline
                  OR (a.game_start_time IS NULL
                      AND COALESCE(a.event_end_estimate, a.end_date) > NOW())
              )
              AND a.created_at > NOW() - INTERVAL '1 day'
              AND (latest_candle.p IS NULL OR (latest_candle.p > 0.03 AND latest_candle.p < 0.97))
            ORDER BY a.composite_score DESC
        """)
        rows = cur.fetchall()

    if not rows:
        return []

    now = datetime.now(timezone.utc)
    six_hours = timedelta(hours=6)
    live_buffer = timedelta(hours=LIVE_BUFFER_HOURS)

    # Bulk-fetch Gamma resolution status for the top candidates and reject any
    # that are already settled (closed, UMA proposed/disputed/resolved, or
    # price >= 0.98). The price filter in the SQL above catches obvious cases,
    # but it's reactive — UMA can move ahead of the order book on quiet
    # markets. Cap at the top 15 by score so cold cache stays cheap (max ~15
    # Gamma calls; subsequent requests within 60s hit the TTL cache).
    candidate_cids = list({row["condition_id"] for row in rows[:15] if row["condition_id"]})
    gamma_status = _fetch_gamma_status(candidate_cids)

    def is_decided(row):
        return _is_market_settled(gamma_status.get(row["condition_id"], {}))

    def is_live(row):
        gs = row["game_start_time"]
        return gs is not None and gs <= now <= gs + live_buffer

    def qualifies_timing(row):
        strategies = row["strategies"] or []
        if "timing_relative_resolution" in strategies:
            return True
        if is_live(row):
            return True  # in-progress games are timing-edge by definition
        effective = row["event_end_estimate"] or row["end_date"]
        return effective is not None and now < effective <= now + six_hours

    def qualifies_coordinated(row):
        strategies = row["strategies"] or []
        return (
            "wallet_clustering" in strategies
            or "concentrated_one_sided" in strategies
            or (row["wallet_count"] or 0) >= 2
        )

    def qualifies_conviction(row):
        wr = row["win_rate"]
        pnl = row["total_pnl"]
        return wr is not None and wr >= 0.7 and pnl is not None and pnl >= 50000

    # Selection order: TIMING → COORDINATED → CONVICTION. Rows already sorted by score desc.
    # Dedupe by condition_id so the three cards always cover three distinct markets.
    picked_ids: set = set()
    picked_markets: set = set()
    picks: dict[str, dict] = {}

    for key, predicate in (
        ("TIMING_EDGE", qualifies_timing),
        ("COORDINATED_FLOW", qualifies_coordinated),
        ("HIGHEST_CONVICTION", qualifies_conviction),
    ):
        for row in rows:
            if row["id"] in picked_ids or row["condition_id"] in picked_markets:
                continue
            if is_decided(row):
                continue
            if predicate(row):
                picks[key] = row
                picked_ids.add(row["id"])
                picked_markets.add(row["condition_id"])
                break

    # Fill empty buckets from remaining rows in score order, still respecting dedupe
    for key in CATEGORY_ORDER:
        if key in picks:
            continue
        for row in rows:
            if row["id"] in picked_ids or row["condition_id"] in picked_markets:
                continue
            if is_decided(row):
                continue
            picks[key] = row
            picked_ids.add(row["id"])
            picked_markets.add(row["condition_id"])
            break

    results = []
    for rank_idx, key in enumerate(CATEGORY_ORDER, start=1):
        if key not in picks:
            continue
        row = picks[key]

        copy_action = row["llm_copy_action"]
        if isinstance(copy_action, str):
            try:
                copy_action = json.loads(copy_action)
            except (json.JSONDecodeError, TypeError):
                copy_action = {}

        tags_raw = row["tags"] or "[]"
        primary_tag = None
        try:
            parsed = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            if isinstance(parsed, list) and parsed:
                primary_tag = parsed[0]
        except (json.JSONDecodeError, TypeError):
            primary_tag = None

        score = row["composite_score"] or 0
        strength = min(4, int(score // 25) + 1)

        # Surface event_end_estimate as `end_date` so the frontend countdown
        # targets the actual event time, matching /api/spotlight behavior.
        effective_end = row["event_end_estimate"] or row["end_date"]

        gs = row["game_start_time"]
        results.append({
            "category": key,
            "rank": rank_idx,
            "strength": strength,
            "id": row["id"],
            "market_title": row["market_title"],
            "condition_id": row["condition_id"],
            "event_slug": row["event_slug"],
            "market_image": row["market_image"],
            "primary_tag": primary_tag,
            "end_date": effective_end.isoformat() if effective_end else None,
            "game_start_time": gs.isoformat() if gs else None,
            "live": is_live(row),
            "llm_summary": row["llm_summary"],
            "llm_copy_action": copy_action,
            "total_usd": row["total_usd"],
            "market_total_usd": row["market_total_usd"],
            "latest_price": row["latest_price"],
            "wallet_count": row["wallet_count"] or 0,
            "wallet": {
                "address": row["wallet"],
                "win_rate": row["win_rate"],
                "total_pnl": row["total_pnl"],
                "total_invested": row["total_invested"],
            },
        })
    return results


def _parse_json_field(obj: dict, key: str) -> list:
    val = obj.get(key, "[]")
    return json.loads(val) if isinstance(val, str) else val


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

# Simple in-memory cache: key -> (expiry_ts, data). Bounded LRU so unbounded
# crawler traffic over many condition_ids can't blow up RSS.
_live_cache: LRUCache = LRUCache(maxsize=5000)
_LIVE_CACHE_TTL = 30  # seconds

_price_history_cache: LRUCache = LRUCache(maxsize=5000)
_PRICE_HISTORY_CACHE_TTL = 60  # seconds

_holders_cache: LRUCache = LRUCache(maxsize=5000)
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
            image=market.get("image"),
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
        image=market.get("image"),
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


@app.get("/api/market/{condition_id}/overlay", response_model=OverlayResponse)
def get_market_overlay(
    condition_id: str,
    title: str = Query(default="", description="Market title for parsing"),
    tag: list[str] = Query(default=[], description="Market tags; pass repeated"),
    event_slug: str = Query(default=""),
):
    """Dispatch endpoint for sport overlays.

    Resolves a sport plugin from the market's tags and returns the plugin's
    OverlayResponse. Returns 404 when no plugin matches, when the plugin
    declines to handle the title, or when the plugin can't find a matching
    game on today's schedule.
    """
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    plugin = sports.resolve_for_tags(tag)
    if plugin is None or not plugin.can_handle(title, tag, event_slug):
        raise HTTPException(status_code=404, detail="no overlay plugin matches")

    result = plugin.fetch(condition_id, title, tag, event_slug)
    if result is None:
        raise HTTPException(status_code=404, detail="no matching game found")
    return result


_RANGE_PARAMS = {
    "24h": (100, "1d"),
    "7d": (150, "1w"),
    "30d": (200, "max"),
    "all": (300, "max"),
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

    # Get outcome names from live market data
    live = get_market_live(condition_id)
    outcome_names = {o.token_id: o.name for o in live.outcomes} if live.outcomes else {}

    try:
        resp = _requests.get(
            f"{DATA_API}/holders",
            params={"market": condition_id},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except _requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Data API error: {e}")

    if not isinstance(raw, list):
        raw = []

    # Flatten: response is [{token, holders: [...]}, ...] per outcome
    flat = []
    for outcome_group in raw:
        token = outcome_group.get("token", "")
        outcome_name = outcome_names.get(token, f"Outcome {outcome_group.get('token', '?')[:8]}")
        for h in outcome_group.get("holders", []):
            h["_outcome"] = outcome_name
            flat.append(h)

    flat.sort(key=lambda p: abs(float(p.get("amount", 0))), reverse=True)
    flat = flat[:10]

    wallets = [p.get("proxyWallet", "").lower() for p in flat if p.get("proxyWallet")]

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
    for p in flat:
        w = (p.get("proxyWallet") or "").lower()
        stats = wallet_stats.get(w, {})
        amount = abs(float(p.get("amount", 0)))
        holders.append(HolderEntry(
            wallet=w,
            position_size=amount,
            outcome=p.get("_outcome", ""),
            side="long",
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


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health(response: Response):
    """Health check. Returns 503 when no alerts produced in the last hour so
    HEAD-only uptime monitors can detect scanner staleness via status code."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS cnt,
                MAX(scanned_at) AS latest_scanned_at,
                EXTRACT(EPOCH FROM (NOW() - MAX(scanned_at)))::BIGINT AS seconds_since_latest
            FROM alerts
            """,
        )
        row = cur.fetchone()
    seconds_since = row["seconds_since_latest"]
    is_fresh = seconds_since is not None and seconds_since <= 3600
    if not is_fresh:
        response.status_code = 503
    return {
        "status": "ok" if is_fresh else "stale",
        "alert_count": row["cnt"],
        "latest_scanned_at": row["latest_scanned_at"].isoformat() if row["latest_scanned_at"] else None,
        "seconds_since_latest_alert": seconds_since,
    }


@app.get("/api/articles", response_model=list[ArticleListItem])
def list_articles():
    """List all published articles for sitemap consumption."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, event_slug, published_date, headline
            FROM articles
            WHERE status = 'published'
            ORDER BY published_date DESC, created_at DESC
            """,
        )
        rows = cur.fetchall()
    return [
        ArticleListItem(
            run_id=r["run_id"],
            event_slug=r["event_slug"],
            published_date=r["published_date"].isoformat(),
            headline=r["headline"],
        )
        for r in rows
    ]


@app.get("/api/articles/by-slug/{date}/{event_slug}", response_model=ArticleOut)
def get_article_by_slug(date: str, event_slug: str):
    """Look up a published article by (published_date, event_slug)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, event_slug, published_date, headline, subhead,
                   body_markdown, cover_alt_text, alert_ids, posted_url,
                   (cover_bytes IS NOT NULL) AS has_cover
            FROM articles
            WHERE published_date = %s::date
              AND event_slug = %s
              AND status = 'published'
            LIMIT 1
            """,
            (date, event_slug),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="article not found")
    return ArticleOut(
        run_id=row["run_id"],
        event_slug=row["event_slug"],
        published_date=row["published_date"].isoformat(),
        headline=row["headline"],
        subhead=row["subhead"],
        body_markdown=row["body_markdown"],
        cover_alt_text=row["cover_alt_text"],
        alert_ids=list(row["alert_ids"] or []),
        posted_url=row["posted_url"],
        has_cover=bool(row["has_cover"]),
    )


@app.get("/api/articles/{run_id}/cover.png")
def get_article_cover(run_id: str):
    """Stream the cover_bytes for a published article."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT cover_bytes
            FROM articles
            WHERE run_id = %s AND status = 'published'
            LIMIT 1
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if not row or row["cover_bytes"] is None:
        raise HTTPException(status_code=404, detail="cover not found")
    png_bytes = bytes(row["cover_bytes"])  # psycopg2 BYTEA → memoryview, normalize to bytes
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------------------------------------------------------------------------
# Events (SEO event hub pages)
# ---------------------------------------------------------------------------

@app.get("/api/event/{slug}", response_model=EventDetail)
def get_event(slug: str):
    """Event hub: metadata, child markets, aggregate stats, top alerts/wallets.

    The event row is lazy-fetched from Gamma /events?slug= on first hit and
    cached in the events table. Past-resolved events are kept indefinitely;
    active events refresh after 7 days. 404 only when both Gamma and our DB
    have nothing for the slug.
    """
    event_row = get_event_or_fetch(slug)

    with db() as conn:
        cur = conn.cursor()

        # Per-market aggregates for every market we have alerts on in this event
        cur.execute(
            """
            SELECT a.condition_id,
                   MAX(a.market_title)    AS market_title,
                   MAX(a.market_image)    AS market_image,
                   MAX(a.end_date)        AS end_date,
                   COUNT(*)               AS alert_count,
                   SUM(a.total_usd)       AS total_usd,
                   MAX(a.composite_score) AS max_score
            FROM alerts a
            WHERE a.event_slug = %s AND a.condition_id IS NOT NULL
            GROUP BY a.condition_id
            ORDER BY total_usd DESC
            """,
            (slug,),
        )
        market_rows = cur.fetchall()

        if event_row is None and not market_rows:
            raise HTTPException(status_code=404, detail=f"Event not found: {slug}")

        markets = [
            EventMarketSummary(
                condition_id=m["condition_id"],
                market_title=m["market_title"],
                market_image=m["market_image"],
                end_date=m["end_date"],
                alert_count=int(m["alert_count"] or 0),
                total_usd=float(m["total_usd"] or 0),
                max_score=float(m["max_score"] or 0),
            )
            for m in market_rows
        ]

        # Aggregate stats across all alerts in the event
        cur.execute(
            """
            SELECT COUNT(*)                          AS total_alerts,
                   COALESCE(SUM(total_usd), 0)       AS total_usd,
                   COALESCE(MAX(composite_score), 0) AS max_score,
                   MAX(scanned_at)                   AS latest_alert_at
            FROM alerts WHERE event_slug = %s
            """,
            (slug,),
        )
        stats_row = cur.fetchone() or {}
        stats = EventStats(
            total_markets=len(markets),
            total_alerts=int(stats_row.get("total_alerts") or 0),
            total_usd=float(stats_row.get("total_usd") or 0),
            max_composite_score=float(stats_row.get("max_score") or 0),
            latest_alert_at=stats_row.get("latest_alert_at"),
        )

        # Top alerts across all markets in the event
        cur.execute(
            """
            SELECT a.*,
                   wp.win_rate, wp.total_pnl, wp.total_invested
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
            WHERE a.event_slug = %s
            ORDER BY a.composite_score DESC
            LIMIT 10
            """,
            (slug,),
        )
        top_alerts = [_alert_from_row(r) for r in cur.fetchall()]

        # Top wallets by combined position size in the event
        cur.execute(
            """
            SELECT a.wallet,
                   SUM(a.total_usd)               AS total_usd_in_event,
                   COUNT(DISTINCT a.condition_id) AS n_markets,
                   COUNT(*)                       AS n_alerts,
                   MAX(wp.win_rate)               AS win_rate,
                   MAX(wp.total_pnl)              AS total_pnl
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
            WHERE a.event_slug = %s AND a.wallet IS NOT NULL
            GROUP BY a.wallet
            ORDER BY total_usd_in_event DESC
            LIMIT 10
            """,
            (slug,),
        )
        top_wallets = [
            EventTopWallet(
                wallet=r["wallet"],
                total_usd_in_event=float(r["total_usd_in_event"] or 0),
                n_markets=int(r["n_markets"] or 0),
                n_alerts=int(r["n_alerts"] or 0),
                win_rate=float(r["win_rate"]) if r["win_rate"] is not None else None,
                total_pnl=float(r["total_pnl"]) if r["total_pnl"] is not None else None,
            )
            for r in cur.fetchall()
        ]

        # Highest-conviction thesis tied to this event, if any
        cur.execute(
            """
            SELECT wt.*, wp.win_rate, wp.total_pnl, wp.total_invested
            FROM wallet_theses wt
            LEFT JOIN wallet_profiles wp ON wp.wallet = wt.wallet
            WHERE wt.event_slug = %s
            ORDER BY wt.composite_score DESC
            LIMIT 1
            """,
            (slug,),
        )
        thesis_row = cur.fetchone()
        related_thesis = None
        if thesis_row:
            markets_raw = thesis_row.get("markets") or []
            if isinstance(markets_raw, str):
                try:
                    t_markets = json.loads(markets_raw)
                except (json.JSONDecodeError, TypeError):
                    t_markets = []
            else:
                t_markets = markets_raw
            related_thesis = ThesisOut(
                id=thesis_row["id"],
                wallet=thesis_row["wallet"],
                event_slug=thesis_row["event_slug"],
                thesis_headline=thesis_row.get("thesis_headline"),
                markets=t_markets,
                total_usd=float(thesis_row.get("total_usd") or 0),
                composite_score=float(thesis_row.get("composite_score") or 0),
                win_rate=float(thesis_row["win_rate"]) if thesis_row.get("win_rate") is not None else None,
                total_pnl=float(thesis_row["total_pnl"]) if thesis_row.get("total_pnl") is not None else None,
                total_invested=float(thesis_row["total_invested"]) if thesis_row.get("total_invested") is not None else None,
                created_at=thesis_row.get("created_at"),
                updated_at=thesis_row.get("updated_at"),
            )

        # Most recent published article for this event, if any
        cur.execute(
            """
            SELECT run_id, published_date, headline
            FROM articles
            WHERE event_slug = %s AND status = 'published'
            ORDER BY published_date DESC NULLS LAST
            LIMIT 1
            """,
            (slug,),
        )
        article_row = cur.fetchone()
        related_article = None
        if article_row:
            pd = article_row.get("published_date")
            related_article = EventRelatedArticle(
                run_id=article_row["run_id"],
                published_date=pd.isoformat() if pd else "",
                headline=article_row["headline"],
            )

    if event_row:
        try:
            tags_list = json.loads(event_row.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            tags_list = []
        try:
            faqs_raw = event_row.get("seo_faqs") or "[]"
            faqs_list = json.loads(faqs_raw) if isinstance(faqs_raw, str) else faqs_raw
        except (json.JSONDecodeError, TypeError):
            faqs_list = []
        event_out = EventOut(
            slug=slug,
            gamma_event_id=event_row.get("gamma_event_id"),
            title=event_row.get("title"),
            description=event_row.get("description"),
            image=event_row.get("image"),
            icon=event_row.get("icon"),
            start_date=event_row.get("start_date"),
            end_date=event_row.get("end_date"),
            tags=[EventTag(**t) for t in tags_list if isinstance(t, dict)],
            seo_title=event_row.get("seo_title"),
            seo_description=event_row.get("seo_description"),
            seo_summary=event_row.get("seo_summary"),
            seo_faqs=faqs_list,
        )
    else:
        # Slug isn't on Gamma but we have alerts for it — serve a stub the
        # frontend can fall back to (humanized slug, no description).
        event_out = EventOut(slug=slug)

    return EventDetail(
        event=event_out,
        markets=markets,
        stats=stats,
        top_alerts=top_alerts,
        top_wallets=top_wallets,
        related_thesis=related_thesis,
        related_article=related_article,
    )


@app.get("/api/events", response_model=PaginatedEvents)
def list_events(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    min_markets: int = Query(1, ge=1, description="Filter to events with >= this many child markets"),
    min_alerts: int = Query(1, ge=0),
    include_resolved: bool = Query(True, description="Include resolved/expired events"),
    tag: str | None = Query(None, description="Filter by event tag label, e.g. 'Sports'"),
):
    """List events for sitemap + index pages.

    Source of truth is the alerts table (we only care about events we have
    alerts on). Joined with the events cache to surface titles/tags/image
    when available — null-safe for placeholder rows that haven't been
    hydrated from Gamma yet.
    """
    conditions = ["a.event_slug IS NOT NULL"]
    params: list = []
    if not include_resolved:
        conditions.append("(a.end_date IS NULL OR a.end_date > NOW())")
    if tag:
        # Filter against alerts.tags (per-alert labels) rather than
        # events.tags (Gamma-hydrated). This matches how /tag/[slug] pages
        # already work and ensures the filter still finds events whose
        # `events` row hasn't been hydrated yet — common right after the
        # touch-only backfill, before /api/ingest grinds through Gamma.
        conditions.append("""
            EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t
                WHERE LOWER(t) = LOWER(%s)
            )
        """)
        params.append(tag)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    # Aggregate per event_slug, then filter on min_markets / min_alerts.
    # The HAVING clause runs post-aggregate so the COUNT/SUM is correct.
    agg_sql = f"""
        SELECT a.event_slug,
               MAX(e.title)         AS title,
               MAX(e.image)         AS image,
               MAX(e.tags)          AS tags,
               MAX(a.end_date)      AS end_date,
               MAX(a.scanned_at)    AS last_alert_at,
               COUNT(DISTINCT a.condition_id) AS n_markets,
               COUNT(*)             AS n_alerts,
               COALESCE(SUM(a.total_usd), 0) AS total_usd
        FROM alerts a
        LEFT JOIN events e ON e.event_slug = a.event_slug
        WHERE {where}
        GROUP BY a.event_slug
        HAVING COUNT(DISTINCT a.condition_id) >= %s
           AND COUNT(*) >= %s
    """

    with db() as conn:
        cur = conn.cursor()

        # Total count: wrap the agg query as a subselect.
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM ({agg_sql}) sub",
            params + [min_markets, min_alerts],
        )
        total = int((cur.fetchone() or {}).get("cnt") or 0)

        cur.execute(
            f"""{agg_sql}
                ORDER BY MAX(a.scanned_at) DESC NULLS LAST
                LIMIT %s OFFSET %s""",
            params + [min_markets, min_alerts, per_page, offset],
        )
        rows = cur.fetchall()

    events: list[EventListItem] = []
    for r in rows:
        tag_labels: list[str] = []
        raw_tags = r.get("tags") or "[]"
        try:
            parsed = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
            tag_labels = [
                t.get("label") for t in parsed
                if isinstance(t, dict) and t.get("label")
            ]
        except (json.JSONDecodeError, TypeError):
            pass

        events.append(EventListItem(
            slug=r["event_slug"],
            title=r.get("title"),
            image=r.get("image"),
            end_date=r.get("end_date"),
            n_markets=int(r.get("n_markets") or 0),
            n_alerts=int(r.get("n_alerts") or 0),
            total_usd=float(r.get("total_usd") or 0),
            tags=tag_labels,
            last_alert_at=r.get("last_alert_at"),
        ))

    return PaginatedEvents(events=events, total=total, page=page, per_page=per_page)
