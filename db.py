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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_cid_resolved ON tracked_bets(condition_id, resolved)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_dedup
        ON tracked_bets(wallet, condition_id, outcome, side, trade_timestamp)
    """)

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

    # -- new_wallet_large_bet (per-trade dedup for flag counting) -------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flagged_trade_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            trade_timestamp REAL NOT NULL,
            usd_value REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fte_dedup
        ON flagged_trade_events(wallet, condition_id, trade_timestamp)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mvs_cid ON market_volume_snapshots(condition_id)")

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ph_token ON price_history(condition_id, outcome)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ph_dedup
        ON price_history(condition_id, outcome, trade_timestamp)
    """)

    # -- timing_relative_resolution (repeat timing patterns) -------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timing_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            minutes_to_resolution REAL NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            market_duration_hours REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tf_wallet ON timing_flags(wallet)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tf_dedup
        ON timing_flags(wallet, condition_id, trade_timestamp)
    """)

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
            recorded_at TEXT NOT NULL,
            api_timestamp INTEGER
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_token ON price_candles(condition_id, token_id)")
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_cid ON orderbook_snapshots(condition_id)")

    # -- llm_evaluations (cache LLM verdicts by dedup_key) --------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_evaluations (
            dedup_key TEXT PRIMARY KEY,
            interesting INTEGER NOT NULL,
            summary TEXT,
            evaluated_at TEXT NOT NULL
        )
    """)

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
        """INSERT OR IGNORE INTO tracked_bets
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


def get_unresolved_condition_ids(wallet: str | None = None) -> list[str]:
    """Return distinct condition_ids with unresolved bets.

    If wallet is provided, only returns condition_ids for that wallet."""
    conn = get_db()
    if wallet:
        rows = conn.execute(
            "SELECT DISTINCT condition_id FROM tracked_bets WHERE resolved = 0 AND wallet = ?",
            (wallet.lower(),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT condition_id FROM tracked_bets WHERE resolved = 0").fetchall()
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


def mark_bets_resolved_bulk(updates: list[tuple[int, int]]) -> None:
    """Mark multiple bets as resolved in a single transaction.

    updates: list of (won, bet_id) tuples.
    """
    if not updates:
        return
    conn = get_db()
    conn.executemany(
        "UPDATE tracked_bets SET resolved = 1, won = ? WHERE id = ?",
        updates,
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


NULL_FUNDER_MAX_AGE_HOURS = 168  # retry NULL-funder lookups after 7 days


def get_cached_funder(wallet: str) -> tuple[bool, str | None]:
    """Look up a cached funder for a wallet.

    Returns (True, funder) if the wallet is in the cache (funder may be None
    meaning 'looked up but no funder found'), or (False, None) if not cached.

    NULL-funder entries older than NULL_FUNDER_MAX_AGE_HOURS are treated as
    uncached so transient API failures don't permanently poison the cache.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT funder, discovered_at FROM wallet_funders WHERE wallet = ?",
        (wallet.lower(),),
    ).fetchone()
    if row is None:
        return (False, None)
    funder, discovered_at = row[0], row[1]
    # If funder is NULL, check if the cache entry is stale
    if funder is None and discovered_at:
        try:
            disc_dt = datetime.fromisoformat(discovered_at)
            if disc_dt.tzinfo is None:
                disc_dt = disc_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - disc_dt).total_seconds() / 3600
            if age_hours > NULL_FUNDER_MAX_AGE_HOURS:
                return (False, None)  # stale — treat as uncached for retry
        except (ValueError, TypeError):
            pass
    return (True, funder)


def save_funder(wallet: str, funder: str | None) -> None:
    """Cache a wallet -> funder mapping."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO wallet_funders (wallet, funder, discovered_at)
           VALUES (?, ?, ?)""",
        (wallet.lower(), funder.lower() if funder else None, datetime.now(timezone.utc).isoformat()),
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
# flagged_trade_events operations (dedup for flagged_wallets counting)
# ===========================================================================


def record_flagged_trade_event(wallet: str, condition_id: str, trade_timestamp: float, usd_value: float) -> bool:
    """Record a specific trade flagging event. Returns True if this is a new
    event (not previously seen), False if it was already recorded."""
    conn = get_db()
    cursor = conn.execute(
        """INSERT OR IGNORE INTO flagged_trade_events
           (wallet, condition_id, trade_timestamp, usd_value, recorded_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            wallet.lower(),
            condition_id,
            trade_timestamp,
            usd_value,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


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

VOLUME_SNAPSHOT_MIN_INTERVAL_SEC = 1800  # 30 minutes between snapshots per market


def record_volume_snapshot(condition_id: str, volume_24h: float) -> None:
    """Record a volume observation for a market.
    Skips if a snapshot for this condition was recorded less than
    VOLUME_SNAPSHOT_MIN_INTERVAL_SEC ago to prevent baseline dilution."""
    conn = get_db()
    row = conn.execute(
        """SELECT snapshot_at FROM market_volume_snapshots
           WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT 1""",
        (condition_id,),
    ).fetchone()
    if row:
        last_at = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        if (now - last_at).total_seconds() < VOLUME_SNAPSHOT_MIN_INTERVAL_SEC:
            return
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


def get_average_volume(condition_id: str) -> tuple[float, int] | None:
    """Return (avg_volume, snapshot_count) for a market, or None if no history."""
    conn = get_db()
    row = conn.execute(
        "SELECT AVG(volume_24h), COUNT(*) FROM market_volume_snapshots WHERE condition_id = ?",
        (condition_id,),
    ).fetchone()
    if not row or row[1] == 0:
        return None
    return (row[0], row[1])


# ===========================================================================
# price_history operations (price_impact)
# ===========================================================================


def record_price_observation(condition_id: str, outcome: str, price: float, trade_timestamp: float) -> None:
    """Record a price observation for a token."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO price_history
           (condition_id, outcome, price, trade_timestamp, recorded_at)
           VALUES (?, ?, ?, ?, ?)""",
        (condition_id, outcome, price, trade_timestamp, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_price_history(condition_id: str, outcome: str, limit: int = 100) -> list[tuple[float, float]]:
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


def record_timing_flag(
    wallet: str, condition_id: str, minutes_to_resolution: float, usd_value: float, trade_timestamp: float,
    *, market_duration_hours: float | None = None,
) -> None:
    """Record that a wallet bet close to market resolution."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO timing_flags
           (wallet, condition_id, minutes_to_resolution, usd_value, trade_timestamp, recorded_at,
            market_duration_hours)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            wallet.lower(),
            condition_id,
            minutes_to_resolution,
            usd_value,
            trade_timestamp,
            datetime.now(timezone.utc).isoformat(),
            market_duration_hours,
        ),
    )
    conn.commit()


def get_wallet_timing_stats(
    wallet: str, *, min_market_duration_hours: float | None = None
) -> dict:
    """Get stats on how often a wallet bets near resolution.

    If *min_market_duration_hours* is set, only flags from markets with
    duration >= that value are counted.  This excludes short-duration
    markets (e.g. 5-min BTC binary options) whose near-resolution bets
    are expected and shouldn't inflate the serial-timer count.
    """
    conn = get_db()
    if min_market_duration_hours is not None:
        # Exclude short markets; also include rows where duration is NULL
        # (old data without the column populated) to avoid under-counting.
        row = conn.execute(
            """SELECT
                   COUNT(*) as total_flags,
                   COUNT(DISTINCT condition_id) as distinct_markets,
                   AVG(minutes_to_resolution) as avg_minutes,
                   MIN(minutes_to_resolution) as min_minutes,
                   SUM(usd_value) as total_usd
               FROM timing_flags
               WHERE wallet = ?
                 AND (market_duration_hours IS NULL
                      OR market_duration_hours >= ?)""",
            (wallet.lower(), min_market_duration_hours),
        ).fetchone()
    else:
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


def clear_wallet_pnl(wallet: str) -> None:
    """Delete all cached P&L records for a wallet so fresh data can replace them.
    Prevents stale 'open' records lingering after positions close."""
    conn = get_db()
    conn.execute("DELETE FROM wallet_pnl WHERE wallet = ?", (wallet.lower(),))
    conn.commit()


def record_wallet_pnl(wallet: str, position: dict, position_type: str) -> None:
    """Record a wallet's position P&L data (open or closed)."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO wallet_pnl
           (wallet, condition_id, asset, outcome, avg_price, total_bought,
            realized_pnl, cur_price, event_slug, end_date, position_type,
            recorded_at, api_timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            position.get("timestamp"),
        ),
    )
    conn.commit()


def get_wallet_pnl_latest_timestamp(wallet: str, position_type: str) -> int | None:
    """Get the most recent api_timestamp for a wallet's cached positions."""
    conn = get_db()
    row = conn.execute(
        "SELECT MAX(api_timestamp) FROM wallet_pnl WHERE wallet = ? AND position_type = ?",
        (wallet.lower(), position_type),
    ).fetchone()
    return row[0] if row and row[0] else None


def clear_wallet_pnl_by_type(wallet: str, position_type: str) -> None:
    """Delete cached P&L records for a wallet filtered by position type."""
    conn = get_db()
    conn.execute(
        "DELETE FROM wallet_pnl WHERE wallet = ? AND position_type = ?",
        (wallet.lower(), position_type),
    )
    conn.commit()


def get_wallet_pnl_summary(wallet: str) -> dict:
    """Get aggregate P&L summary for a wallet, including odds-adjusted stats.

    Returns avg_buy_price for closed positions so callers can compare actual
    win rate against the implied probability (avg price paid).  Winning 10/10
    bets bought at 0.90 is unremarkable; winning 10/10 at 0.40 is extraordinary.
    """
    conn = get_db()
    # Use cur_price to determine wins/losses based on market resolution
    # rather than realized_pnl, which reflects trading profit and is biased
    # toward winners (losing positions often expire without appearing as
    # "closed").  cur_price ~1.0 means the held outcome won; ~0.0 means it lost.
    # Positions with cur_price in between are unresolved or sold before resolution.
    row = conn.execute(
        """SELECT
               COUNT(*) as total_positions,
               SUM(CASE WHEN position_type='closed' THEN 1 ELSE 0 END) as closed,
               SUM(CASE WHEN position_type='closed' AND cur_price >= 0.99 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN position_type='closed' AND cur_price <= 0.01 THEN 1 ELSE 0 END) as losses,
               SUM(realized_pnl) as total_pnl,
               SUM(total_bought) as total_invested,
               AVG(CASE WHEN position_type='closed' AND (cur_price >= 0.99 OR cur_price <= 0.01)
                        THEN avg_price END) as avg_resolved_price,
               AVG(CASE WHEN position_type='closed' AND cur_price >= 0.99 THEN avg_price END) as avg_win_price,
               AVG(CASE WHEN position_type='closed' AND cur_price <= 0.01 THEN avg_price END) as avg_loss_price
           FROM wallet_pnl WHERE wallet = ?""",
        (wallet.lower(),),
    ).fetchone()
    wins = row[2] or 0
    losses = row[3] or 0
    total_pnl = row[4] or 0.0
    total_invested = row[5] or 0.0
    avg_resolved_price = row[6] or 0.0
    # Edge = actual win rate minus implied win rate (avg price paid).
    # This is our primary edge metric because:
    # - realizedPnl from the API is unreliable (can be positive on losing
    #   positions due to partial sells before resolution, and totalBought
    #   accumulates all buys including shares later sold)
    # - avg_resolved_price is averaged only over the same resolved positions
    #   used for win_rate (cur_price >= 0.99 or <= 0.01), so the denominators
    #   match and the edge calculation is mathematically correct:
    #   edge = (1/N) * Σ(outcome_i - price_i) = win_rate - avg_price
    closed = wins + losses
    win_rate = wins / closed if closed > 0 else 0.0
    implied_prob = avg_resolved_price if 0 < avg_resolved_price < 1 else 0.5
    edge = win_rate - implied_prob
    return {
        "total_positions": row[0] or 0,
        "closed_positions": closed,  # only resolved positions (cur_price ~0 or ~1)
        "wins": wins,
        "losses": losses,
        "total_pnl": total_pnl,
        "total_invested": total_invested,
        "edge": edge,
        "avg_closed_price": avg_resolved_price,
        "avg_win_price": row[7] or 0.0,
        "avg_loss_price": row[8] or 0.0,
    }


def get_wallet_market_positions(wallet: str, condition_id: str) -> list[dict]:
    """Get a wallet's positions on a specific market (both open and closed).

    Returns a list of dicts with outcome, avg_price, total_bought,
    realized_pnl, cur_price, and position_type for each position the
    wallet holds/held on this market.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT outcome, avg_price, total_bought, realized_pnl,
                  cur_price, position_type
           FROM wallet_pnl
           WHERE wallet = ? AND condition_id = ?""",
        (wallet.lower(), condition_id),
    ).fetchall()
    return [
        {
            "outcome": r[0],
            "avg_price": r[1],
            "total_bought": r[2],
            "realized_pnl": r[3],
            "cur_price": r[4],
            "position_type": r[5],
        }
        for r in rows
    ]


# ===========================================================================
# price_candles operations (CLOB price history)
# ===========================================================================


def record_price_candle(condition_id: str, token_id: str, outcome: str, t: float, p: float) -> None:
    """Record a single price candle point."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO price_candles
           (condition_id, token_id, outcome, t, p, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (condition_id, token_id, outcome, t, p, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def record_price_candles_batch(condition_id: str, token_id: str, outcome: str, candles: list[dict]) -> int:
    """Batch-insert price candle data. Returns count actually inserted."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for c in candles:
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO price_candles
                   (condition_id, token_id, outcome, t, p, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (condition_id, token_id, outcome, c["t"], c["p"], now),
            )
            inserted += cursor.rowcount
        except (KeyError, sqlite3.IntegrityError):
            pass
    conn.commit()
    return inserted


def get_price_candles(condition_id: str, token_id: str, limit: int = 500) -> list[tuple[float, float]]:
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

ORDERBOOK_SNAPSHOT_MIN_INTERVAL_SEC = 600  # 10 minutes between snapshots per condition


def record_orderbook_snapshot(
    condition_id: str, token_id: str, outcome: str, bids: list[dict], asks: list[dict],
    *, force: bool = False,
) -> None:
    """Record an order book snapshot with computed depth metrics.
    Skips if a snapshot for this condition was recorded less than
    ORDERBOOK_SNAPSHOT_MIN_INTERVAL_SEC ago to prevent table bloat.
    Set force=True (e.g. during backfill) to bypass the interval check."""
    conn = get_db()
    if not force:
        row = conn.execute(
            """SELECT snapshot_at FROM orderbook_snapshots
               WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT 1""",
            (condition_id,),
        ).fetchone()
        if row:
            last_at = datetime.fromisoformat(row[0])
            now = datetime.now(timezone.utc)
            if (now - last_at).total_seconds() < ORDERBOOK_SNAPSHOT_MIN_INTERVAL_SEC:
                return

    best_bid = max((float(b["price"]) for b in bids), default=0)
    best_ask = min((float(a["price"]) for a in asks), default=0)
    spread = (best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0
    mid_price = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0

    bid_depth = sum(float(b["size"]) * float(b["price"]) for b in bids)
    ask_depth = sum(float(a["size"]) * float(a["price"]) for a in asks)

    conn.execute(
        """INSERT INTO orderbook_snapshots
           (condition_id, token_id, outcome, best_bid, best_ask, spread,
            bid_depth, ask_depth, mid_price, snapshot_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            condition_id,
            token_id,
            outcome,
            best_bid,
            best_ask,
            spread,
            bid_depth,
            ask_depth,
            mid_price,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_orderbook_stats(token_id: str) -> dict | None:
    """Get the latest order book snapshot for a token."""
    conn = get_db()
    row = conn.execute(
        """SELECT best_bid, best_ask, spread, bid_depth, ask_depth, mid_price, snapshot_at
           FROM orderbook_snapshots
           WHERE token_id = ?
           ORDER BY snapshot_at DESC LIMIT 1""",
        (token_id,),
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


# ===========================================================================
# llm_evaluations operations (LLM verdict cache)
# ===========================================================================


def get_llm_evaluation(dedup_key: str) -> dict | None:
    """Look up a cached LLM evaluation by dedup_key.
    Returns dict with interesting (bool) and summary, or None if not cached."""
    conn = get_db()
    row = conn.execute(
        "SELECT interesting, summary FROM llm_evaluations WHERE dedup_key = ?",
        (dedup_key,),
    ).fetchone()
    if not row:
        return None
    return {"interesting": bool(row[0]), "summary": row[1]}


def save_llm_evaluation(dedup_key: str, interesting: bool, summary: str | None) -> None:
    """Cache an LLM evaluation result."""
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO llm_evaluations
           (dedup_key, interesting, summary, evaluated_at)
           VALUES (?, ?, ?, ?)""",
        (dedup_key, int(interesting), summary, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
