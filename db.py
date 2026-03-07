"""
Centralized database module for all detection strategies.

Provides a single SQLite database with tables for:
- tracked_bets: win/loss tracking for flagged wallets (win_rate_tracking)
- wallet_funders: cached wallet -> funder mappings (wallet_clustering)
- flagged_wallets: repeat-flag counts per wallet (new_wallet_large_bet)
- wallet_event_history: cross-run wallet/event trade records (correlated_cross_market)
- market_volume_snapshots: periodic volume snapshots (pre_event_volume_spike)
- price_history: per-token price observations (price_impact)
- timing_flags: wallets flagged for betting near resolution (timing_relative_resolution)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "polybot.db")

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    """Return the shared database connection, creating tables on first call."""
    global _conn
    if _conn is not None:
        return _conn

    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("PRAGMA journal_mode=WAL")
    _init_tables(_conn)
    return _conn


def _init_tables(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""

    # -- win_rate_tracking -----------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            side TEXT NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            won INTEGER DEFAULT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_wallet ON tracked_bets(wallet)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_unresolved ON tracked_bets(resolved)")

    # -- wallet_clustering (funder cache) --------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_funders (
            wallet TEXT PRIMARY KEY,
            funder TEXT,
            discovered_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_funder ON wallet_funders(funder)")

    # -- new_wallet_large_bet (repeat flag tracking) ---------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flagged_wallets (
            wallet TEXT PRIMARY KEY,
            times_flagged INTEGER NOT NULL DEFAULT 1,
            total_usd_flagged REAL NOT NULL DEFAULT 0,
            first_flagged_at TEXT NOT NULL,
            last_flagged_at TEXT NOT NULL
        )
    """)

    # -- correlated_cross_market (cross-run event history) ---------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_event_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            event_slug TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            side TEXT NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_weh_wallet ON wallet_event_history(wallet)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_weh_event ON wallet_event_history(event_slug)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_weh_dedup
        ON wallet_event_history(wallet, condition_id, trade_timestamp)
    """)

    # -- pre_event_volume_spike (volume snapshots) -----------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_volume_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT NOT NULL,
            volume_24h REAL NOT NULL,
            snapshot_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mvs_cid ON market_volume_snapshots(condition_id)"
    )

    # -- price_impact (historical price observations) --------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            price REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ph_token ON price_history(condition_id, outcome)"
    )

    # -- timing_relative_resolution (repeat timing patterns) -------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timing_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            minutes_to_resolution REAL NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tf_wallet ON timing_flags(wallet)")

    # -- wallet_pnl (profit/loss from closed positions) -------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            asset TEXT,
            outcome TEXT,
            avg_price REAL,
            total_bought REAL,
            realized_pnl REAL,
            cur_price REAL,
            event_slug TEXT,
            end_date TEXT,
            position_type TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wpnl_wallet ON wallet_pnl(wallet)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wpnl_dedup
        ON wallet_pnl(wallet, condition_id, asset, position_type)
    """)

    # -- price_candles (CLOB historical price time-series) ----------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT NOT NULL,
            token_id TEXT NOT NULL,
            outcome TEXT,
            t REAL NOT NULL,
            p REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pc_token ON price_candles(condition_id, token_id)"
    )
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pc_dedup
        ON price_candles(token_id, t)
    """)

    # -- orderbook_snapshots (CLOB order book depth) ----------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT NOT NULL,
            token_id TEXT NOT NULL,
            outcome TEXT,
            best_bid REAL,
            best_ask REAL,
            spread REAL,
            bid_depth REAL,
            ask_depth REAL,
            mid_price REAL,
            snapshot_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_obs_cid ON orderbook_snapshots(condition_id)"
    )

    conn.commit()


# ===========================================================================
# tracked_bets operations (win_rate_tracking)
# ===========================================================================

def record_tracked_bet(trade: dict) -> None:
    """Insert a trade into tracked_bets for win/loss tracking."""
    wallet = trade.get("proxyWallet", "").lower()
    if not wallet:
        return
    conn = get_db()
    conn.execute(
        """INSERT INTO tracked_bets
           (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            wallet,
            trade.get("conditionId", ""),
            trade.get("outcome", ""),
            trade.get("side", ""),
            float(trade.get("_usd_value", 0)),
            trade.get("timestamp", 0),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_unresolved_condition_ids() -> list[str]:
    """Return distinct condition_ids with unresolved bets."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT condition_id FROM tracked_bets WHERE resolved = 0"
    ).fetchall()
    return [r[0] for r in rows]


def get_unresolved_bets_for_condition(condition_id: str) -> list[tuple[int, str, str]]:
    """Return (id, outcome, side) for unresolved bets on a condition."""
    conn = get_db()
    return conn.execute(
        "SELECT id, outcome, side FROM tracked_bets WHERE condition_id = ? AND resolved = 0",
        (condition_id,),
    ).fetchall()


def mark_bet_resolved(bet_id: int, won: int) -> None:
    """Mark a single bet as resolved with win/loss."""
    conn = get_db()
    conn.execute(
        "UPDATE tracked_bets SET resolved = 1, won = ? WHERE id = ?",
        (won, bet_id),
    )
    conn.commit()


def get_wallet_stats(wallet: str) -> dict:
    """Get win/loss statistics for a wallet."""
    conn = get_db()
    row = conn.execute(
        """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
               SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins,
               SUM(usd_value) as total_usd
           FROM tracked_bets WHERE wallet = ?""",
        (wallet.lower(),),
    ).fetchone()
    return {
        "total_bets": row[0] or 0,
        "resolved_bets": row[1] or 0,
        "wins": row[2] or 0,
        "total_usd": row[3] or 0.0,
    }


# ===========================================================================
# wallet_funders operations (wallet_clustering)
# ===========================================================================

def get_cached_funder(wallet: str) -> str | None:
    """Look up a cached funder for a wallet. Returns None if not cached."""
    conn = get_db()
    row = conn.execute(
        "SELECT funder FROM wallet_funders WHERE wallet = ?",
        (wallet.lower(),),
    ).fetchone()
    return row[0] if row else None


def save_funder(wallet: str, funder: str | None) -> None:
    """Cache a wallet -> funder mapping."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO wallet_funders (wallet, funder, discovered_at)
           VALUES (?, ?, ?)""",
        (wallet.lower(), funder, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_wallets_by_funder(funder: str) -> list[str]:
    """Return all known wallets funded by a given address."""
    conn = get_db()
    rows = conn.execute(
        "SELECT wallet FROM wallet_funders WHERE funder = ?",
        (funder.lower(),),
    ).fetchall()
    return [r[0] for r in rows]


def get_known_sybil_funders(min_wallets: int = 2) -> dict[str, list[str]]:
    """Return all funders that have funded >= min_wallets wallets."""
    conn = get_db()
    rows = conn.execute(
        """SELECT funder, GROUP_CONCAT(wallet)
           FROM wallet_funders
           WHERE funder IS NOT NULL
           GROUP BY funder
           HAVING COUNT(*) >= ?""",
        (min_wallets,),
    ).fetchall()
    return {r[0]: r[1].split(",") for r in rows}


# ===========================================================================
# flagged_wallets operations (new_wallet_large_bet)
# ===========================================================================

def record_flagged_wallet(wallet: str, usd_value: float) -> dict:
    """Record that a wallet was flagged. Returns updated stats.

    Returns dict with: times_flagged, total_usd_flagged, first_flagged_at, last_flagged_at
    """
    conn = get_db()
    wallet = wallet.lower()
    now = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT times_flagged, total_usd_flagged, first_flagged_at FROM flagged_wallets WHERE wallet = ?",
        (wallet,),
    ).fetchone()

    if existing:
        new_count = existing[0] + 1
        new_total = existing[1] + usd_value
        conn.execute(
            """UPDATE flagged_wallets
               SET times_flagged = ?, total_usd_flagged = ?, last_flagged_at = ?
               WHERE wallet = ?""",
            (new_count, new_total, now, wallet),
        )
        conn.commit()
        return {
            "times_flagged": new_count,
            "total_usd_flagged": new_total,
            "first_flagged_at": existing[2],
            "last_flagged_at": now,
        }
    else:
        conn.execute(
            """INSERT INTO flagged_wallets
               (wallet, times_flagged, total_usd_flagged, first_flagged_at, last_flagged_at)
               VALUES (?, 1, ?, ?, ?)""",
            (wallet, usd_value, now, now),
        )
        conn.commit()
        return {
            "times_flagged": 1,
            "total_usd_flagged": usd_value,
            "first_flagged_at": now,
            "last_flagged_at": now,
        }


def get_flagged_wallet_stats(wallet: str) -> dict | None:
    """Get flag history for a wallet. Returns None if never flagged."""
    conn = get_db()
    row = conn.execute(
        "SELECT times_flagged, total_usd_flagged, first_flagged_at, last_flagged_at FROM flagged_wallets WHERE wallet = ?",
        (wallet.lower(),),
    ).fetchone()
    if not row:
        return None
    return {
        "times_flagged": row[0],
        "total_usd_flagged": row[1],
        "first_flagged_at": row[2],
        "last_flagged_at": row[3],
    }


# ===========================================================================
# wallet_event_history operations (correlated_cross_market)
# ===========================================================================

def record_wallet_event_trade(trade: dict) -> None:
    """Record a trade for cross-run event correlation."""
    wallet = trade.get("proxyWallet", "").lower()
    event_slug = trade.get("eventSlug", "")
    if not wallet or not event_slug:
        return
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO wallet_event_history
           (wallet, event_slug, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            wallet,
            event_slug,
            trade.get("conditionId", ""),
            trade.get("outcome", ""),
            trade.get("side", ""),
            float(trade.get("_usd_value", 0)),
            trade.get("timestamp", 0),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_wallet_event_history(wallet: str, event_slug: str) -> list[dict]:
    """Get all historical trades for a wallet on a specific event."""
    conn = get_db()
    rows = conn.execute(
        """SELECT condition_id, outcome, side, usd_value, trade_timestamp
           FROM wallet_event_history
           WHERE wallet = ? AND event_slug = ?
           ORDER BY trade_timestamp""",
        (wallet.lower(), event_slug),
    ).fetchall()
    return [
        {
            "condition_id": r[0],
            "outcome": r[1],
            "side": r[2],
            "usd_value": r[3],
            "trade_timestamp": r[4],
        }
        for r in rows
    ]


def get_wallet_cross_event_stats(wallet: str) -> dict:
    """Get stats on how many events/markets a wallet has traded across historically."""
    conn = get_db()
    row = conn.execute(
        """SELECT
               COUNT(DISTINCT event_slug) as events,
               COUNT(DISTINCT condition_id) as markets,
               SUM(usd_value) as total_usd,
               COUNT(*) as total_trades
           FROM wallet_event_history
           WHERE wallet = ?""",
        (wallet.lower(),),
    ).fetchone()
    return {
        "distinct_events": row[0] or 0,
        "distinct_markets": row[1] or 0,
        "total_usd": row[2] or 0.0,
        "total_trades": row[3] or 0,
    }


# ===========================================================================
# market_volume_snapshots operations (pre_event_volume_spike)
# ===========================================================================

def record_volume_snapshot(condition_id: str, volume_24h: float) -> None:
    """Record a volume observation for a market."""
    conn = get_db()
    conn.execute(
        """INSERT INTO market_volume_snapshots (condition_id, volume_24h, snapshot_at)
           VALUES (?, ?, ?)""",
        (condition_id, volume_24h, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_volume_history(condition_id: str, limit: int = 100) -> list[tuple[float, str]]:
    """Return recent volume snapshots for a market as (volume_24h, snapshot_at) pairs."""
    conn = get_db()
    rows = conn.execute(
        """SELECT volume_24h, snapshot_at FROM market_volume_snapshots
           WHERE condition_id = ?
           ORDER BY snapshot_at DESC
           LIMIT ?""",
        (condition_id, limit),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_average_volume(condition_id: str) -> float | None:
    """Return the average historical 24h volume for a market, or None if no history."""
    conn = get_db()
    row = conn.execute(
        "SELECT AVG(volume_24h), COUNT(*) FROM market_volume_snapshots WHERE condition_id = ?",
        (condition_id,),
    ).fetchone()
    if not row or row[1] == 0:
        return None
    return row[0]


# ===========================================================================
# price_history operations (price_impact)
# ===========================================================================

def record_price_observation(condition_id: str, outcome: str, price: float,
                             trade_timestamp: float) -> None:
    """Record a price observation for a token."""
    conn = get_db()
    conn.execute(
        """INSERT INTO price_history
           (condition_id, outcome, price, trade_timestamp, recorded_at)
           VALUES (?, ?, ?, ?, ?)""",
        (condition_id, outcome, price, trade_timestamp,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_price_history(condition_id: str, outcome: str,
                      limit: int = 100) -> list[tuple[float, float]]:
    """Return recent price observations as (price, trade_timestamp) pairs,
    ordered oldest first."""
    conn = get_db()
    rows = conn.execute(
        """SELECT price, trade_timestamp FROM price_history
           WHERE condition_id = ? AND outcome = ?
           ORDER BY trade_timestamp DESC
           LIMIT ?""",
        (condition_id, outcome, limit),
    ).fetchall()
    return [(r[0], r[1]) for r in reversed(rows)]


def get_historical_price_range(condition_id: str, outcome: str) -> tuple[float, float] | None:
    """Return (min_price, max_price) from all historical observations, or None."""
    conn = get_db()
    row = conn.execute(
        """SELECT MIN(price), MAX(price) FROM price_history
           WHERE condition_id = ? AND outcome = ?""",
        (condition_id, outcome),
    ).fetchone()
    if not row or row[0] is None:
        return None
    return (row[0], row[1])


# ===========================================================================
# timing_flags operations (timing_relative_resolution)
# ===========================================================================

def record_timing_flag(wallet: str, condition_id: str, minutes_to_resolution: float,
                       usd_value: float, trade_timestamp: float) -> None:
    """Record that a wallet bet close to market resolution."""
    conn = get_db()
    conn.execute(
        """INSERT INTO timing_flags
           (wallet, condition_id, minutes_to_resolution, usd_value, trade_timestamp, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            wallet.lower(), condition_id, minutes_to_resolution,
            usd_value, trade_timestamp,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_wallet_timing_stats(wallet: str) -> dict:
    """Get stats on how often a wallet bets near resolution."""
    conn = get_db()
    row = conn.execute(
        """SELECT
               COUNT(*) as total_flags,
               COUNT(DISTINCT condition_id) as distinct_markets,
               AVG(minutes_to_resolution) as avg_minutes,
               MIN(minutes_to_resolution) as min_minutes,
               SUM(usd_value) as total_usd
           FROM timing_flags
           WHERE wallet = ?""",
        (wallet.lower(),),
    ).fetchone()
    return {
        "total_flags": row[0] or 0,
        "distinct_markets": row[1] or 0,
        "avg_minutes": row[2] or 0.0,
        "min_minutes": row[3] or 0.0,
        "total_usd": row[4] or 0.0,
    }


# ===========================================================================
# wallet_pnl operations (enriched win_rate_tracking / position analysis)
# ===========================================================================

def record_wallet_pnl(wallet: str, position: dict, position_type: str) -> None:
    """Record a wallet's position P&L data (open or closed)."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO wallet_pnl
           (wallet, condition_id, asset, outcome, avg_price, total_bought,
            realized_pnl, cur_price, event_slug, end_date, position_type, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            wallet.lower(),
            position.get("conditionId", ""),
            position.get("asset", ""),
            position.get("outcome", ""),
            float(position.get("avgPrice", 0) or 0),
            float(position.get("totalBought", 0) or 0),
            float(position.get("realizedPnl", 0) or 0),
            float(position.get("curPrice", 0) or 0),
            position.get("eventSlug", ""),
            position.get("endDate", ""),
            position_type,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_wallet_pnl_summary(wallet: str) -> dict:
    """Get aggregate P&L summary for a wallet."""
    conn = get_db()
    row = conn.execute(
        """SELECT
               COUNT(*) as total_positions,
               SUM(CASE WHEN position_type='closed' THEN 1 ELSE 0 END) as closed,
               SUM(CASE WHEN position_type='closed' AND realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN position_type='closed' AND realized_pnl <= 0 THEN 1 ELSE 0 END) as losses,
               SUM(realized_pnl) as total_pnl,
               SUM(total_bought) as total_invested
           FROM wallet_pnl WHERE wallet = ?""",
        (wallet.lower(),),
    ).fetchone()
    return {
        "total_positions": row[0] or 0,
        "closed_positions": row[1] or 0,
        "wins": row[2] or 0,
        "losses": row[3] or 0,
        "total_pnl": row[4] or 0.0,
        "total_invested": row[5] or 0.0,
    }


# ===========================================================================
# price_candles operations (CLOB price history)
# ===========================================================================

def record_price_candle(condition_id: str, token_id: str, outcome: str,
                        t: float, p: float) -> None:
    """Record a single price candle point."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO price_candles
           (condition_id, token_id, outcome, t, p, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (condition_id, token_id, outcome, t, p,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def record_price_candles_batch(condition_id: str, token_id: str, outcome: str,
                               candles: list[dict]) -> int:
    """Batch-insert price candle data. Returns count inserted."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for c in candles:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO price_candles
                   (condition_id, token_id, outcome, t, p, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (condition_id, token_id, outcome, c["t"], c["p"], now),
            )
            inserted += 1
        except (KeyError, sqlite3.IntegrityError):
            pass
    conn.commit()
    return inserted


def get_price_candles(condition_id: str, token_id: str,
                      limit: int = 500) -> list[tuple[float, float]]:
    """Return recent price candles as (timestamp, price) pairs, oldest first."""
    conn = get_db()
    rows = conn.execute(
        """SELECT t, p FROM price_candles
           WHERE condition_id = ? AND token_id = ?
           ORDER BY t DESC LIMIT ?""",
        (condition_id, token_id, limit),
    ).fetchall()
    return [(r[0], r[1]) for r in reversed(rows)]


# ===========================================================================
# orderbook_snapshots operations (CLOB order book depth)
# ===========================================================================

def record_orderbook_snapshot(condition_id: str, token_id: str, outcome: str,
                              bids: list[dict], asks: list[dict]) -> None:
    """Record an order book snapshot with computed depth metrics."""
    best_bid = max((float(b["price"]) for b in bids), default=0)
    best_ask = min((float(a["price"]) for a in asks), default=0)
    spread = (best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0
    mid_price = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0

    bid_depth = sum(float(b["size"]) * float(b["price"]) for b in bids)
    ask_depth = sum(float(a["size"]) * float(a["price"]) for a in asks)

    conn = get_db()
    conn.execute(
        """INSERT INTO orderbook_snapshots
           (condition_id, token_id, outcome, best_bid, best_ask, spread,
            bid_depth, ask_depth, mid_price, snapshot_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (condition_id, token_id, outcome, best_bid, best_ask, spread,
         bid_depth, ask_depth, mid_price,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_orderbook_stats(condition_id: str) -> dict | None:
    """Get the latest order book snapshot for a condition."""
    conn = get_db()
    row = conn.execute(
        """SELECT best_bid, best_ask, spread, bid_depth, ask_depth, mid_price, snapshot_at
           FROM orderbook_snapshots
           WHERE condition_id = ?
           ORDER BY snapshot_at DESC LIMIT 1""",
        (condition_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "best_bid": row[0],
        "best_ask": row[1],
        "spread": row[2],
        "bid_depth": row[3],
        "ask_depth": row[4],
        "mid_price": row[5],
        "snapshot_at": row[6],
    }
