"""
Database connection and initialization for the Polybot backend.

Uses psycopg2 with a simple connection pool pattern.
Reads DATABASE_URL from environment.
"""

import os
import threading

import psycopg2
from psycopg2 import pool as _pgpool
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


# libpq options applied to every connection: fail fast instead of hanging a
# request thread on an unreachable server, and let TCP keepalives notice a
# peer that vanished while a pooled connection sat idle.
_CONNECT_KWARGS = dict(
    connect_timeout=5,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=3,
)


def get_conn():
    """Return a new database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, **_CONNECT_KWARGS)


# ---------------------------------------------------------------------------
# Request-scoped connection pool
#
# The API used to open a brand-new Postgres connection for every request
# (~60k sessions/day). Each one is a TCP + TLS + auth handshake and a forked
# Postgres backend, which showed up as CPU and memory on the Railway Postgres
# service. The pool keeps a handful of connections warm; when it is exhausted
# we fall back to a one-off connection so request handling never blocks.
# ---------------------------------------------------------------------------

# psycopg2 pool semantics: `minconn` is the number of idle connections the
# pool KEEPS (anything returned beyond that is closed), `maxconn` the ceiling
# on simultaneous checkouts. So minconn is the real "warm" count.
POOL_MIN = int(os.environ.get("DB_POOL_MIN", "4"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "8"))

_POOL: _pgpool.ThreadedConnectionPool | None = None
_POOL_LOCK = threading.Lock()


def _pool() -> _pgpool.ThreadedConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = _pgpool.ThreadedConnectionPool(
                    POOL_MIN, POOL_MAX, DATABASE_URL,
                    cursor_factory=RealDictCursor, **_CONNECT_KWARGS,
                )
    return _POOL


def warm_pool() -> None:
    """Open the pool's warm connections at startup so the first requests don't
    pay for handshakes under the pool lock."""
    _pool()


def _is_alive(conn) -> bool:
    """Cheap liveness check for an idle pooled connection: poll() does a
    non-blocking read, which surfaces a socket the server closed while the
    connection sat in the pool (e.g. a Postgres restart) without a round trip."""
    if conn.closed:
        return False
    try:
        conn.poll()
    except Exception:
        return False
    return not conn.closed


def get_pooled_conn():
    """Return (conn, pooled). `pooled` is False when the pool was exhausted and
    a one-off connection was opened instead; pass it back to release_conn().
    Dead connections found in the pool are discarded, not handed out."""
    for _ in range(POOL_MAX + 1):
        try:
            conn = _pool().getconn()
        except _pgpool.PoolError:
            break
        if _is_alive(conn):
            return conn, True
        try:
            _pool().putconn(conn, close=True)
        except Exception:
            pass
    return get_conn(), False


def release_conn(conn, pooled: bool = True) -> None:
    """Hand a connection back. Pooled connections return to the pool (dead
    ones are discarded); one-off connections are closed."""
    if not pooled:
        conn.close()
        return
    try:
        _pool().putconn(conn, close=bool(conn.closed))
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def init_db():
    """Run schema.sql to create tables if they don't exist, then apply migrations."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            _migrate_category_to_tags(cur)
            _migrate_add_llm_fields(cur)
            _migrate_add_market_media(cur)
            _migrate_add_seo_fields(cur)
            _migrate_add_event_timing(cur)
            _migrate_add_tweeted_alerts(cur)
            _migrate_add_articles(cur)
            _migrate_add_events_table(cur)
            _migrate_add_graded_calls(cur)
            _migrate_add_subscribers(cur)
            _migrate_add_digests(cur)
            _migrate_add_seo_skip(cur)
        conn.commit()
    finally:
        conn.close()


def _migrate_category_to_tags(cur):
    """Migrate legacy 'category' column to 'tags' JSON array if needed."""
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'alerts' AND column_name = 'category'
    """)
    if not cur.fetchone():
        return  # already migrated

    # Ensure tags column exists
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'alerts' AND column_name = 'tags'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE alerts ADD COLUMN tags TEXT DEFAULT '[]'")

    # Copy category values into tags as single-element JSON arrays
    cur.execute("""
        UPDATE alerts
        SET tags = jsonb_build_array(category)::text
        WHERE category IS NOT NULL AND category != ''
          AND (tags IS NULL OR tags = '[]')
    """)

    cur.execute("ALTER TABLE alerts DROP COLUMN category")


def _migrate_add_llm_fields(cur):
    """Add llm_bullets and llm_copy_action columns if they don't exist."""
    for col, default in [("llm_bullets", "'[]'"), ("llm_copy_action", "'{}'"), ("llm_headline", "NULL")]:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name = %s
        """, (col,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT DEFAULT {default}")


def _migrate_add_market_media(cur):
    """Add market_image and market_description columns if they don't exist."""
    for col in ("market_image", "market_description"):
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name = %s
        """, (col,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT")


def _migrate_add_event_timing(cur):
    """Add game_start_time + event_end_estimate columns and backfill from end_date."""
    for col in ("game_start_time", "event_end_estimate"):
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name = %s
        """, (col,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} TIMESTAMPTZ")

    # Seed event_end_estimate from end_date for pre-existing rows so they still
    # appear in /api/resolving-soon until the scanner next re-seeds them with
    # game_start_time. COALESCE in the endpoint handles this too, but keeping
    # the column populated avoids NULLs skewing the sort.
    cur.execute("""
        UPDATE alerts
        SET event_end_estimate = end_date
        WHERE event_end_estimate IS NULL AND end_date IS NOT NULL
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_event_end
        ON alerts(event_end_estimate)
        WHERE event_end_estimate IS NOT NULL
    """)


def _migrate_add_tweeted_alerts(cur):
    """Create the tweeted_alerts table if it doesn't exist (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tweeted_alerts (
            alert_id       BIGINT PRIMARY KEY,
            wallet         TEXT NOT NULL,
            condition_id   TEXT NOT NULL,
            tweet_id       TEXT NOT NULL,
            tweet_text     TEXT NOT NULL,
            tweeted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_tweeted_alerts_wallet_market
            ON tweeted_alerts (wallet, condition_id, tweeted_at DESC)
    """)


def _migrate_add_seo_skip(cur):
    """Add seo_skip_reason to alerts + events: non-NULL marks rows the SEO
    worker must never retry (e.g. Azure content filter blocked the prompt)."""
    cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS seo_skip_reason TEXT")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS seo_skip_reason TEXT")


def _migrate_add_seo_fields(cur):
    """Add SEO content columns if they don't exist."""
    for col, default in [
        ("seo_title", "NULL"),
        ("seo_description", "NULL"),
        ("seo_summary", "NULL"),
        ("seo_faqs", "'[]'"),
        ("seo_generated_at", "NULL"),
    ]:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'alerts' AND column_name = %s
        """, (col,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT DEFAULT {default}")


def _migrate_add_articles(cur):
    """Create the articles table for articlebot drafts (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id              SERIAL PRIMARY KEY,
            run_id          TEXT NOT NULL UNIQUE,
            event_slug      TEXT NOT NULL,
            alert_ids       INTEGER[] NOT NULL,
            headline        TEXT NOT NULL,
            subhead         TEXT NOT NULL,
            body_markdown   TEXT NOT NULL,
            cover_alt_text  TEXT,
            cover_path      TEXT,
            md_path         TEXT NOT NULL,
            word_count      INTEGER NOT NULL,
            status          TEXT NOT NULL DEFAULT 'draft',
            posted_url      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            posted_at       TIMESTAMPTZ,
            cover_bytes     BYTEA,
            tweet_text      TEXT,
            tweet_id        TEXT,
            published_date  DATE
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_event_slug
            ON articles (event_slug, created_at DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_status
            ON articles (status, created_at DESC)
    """)
    # Backward-compat ALTERs for tables created before these columns existed
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS cover_bytes BYTEA")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_text TEXT")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS tweet_id TEXT")
    cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_date DATE")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_published_lookup
            ON articles (published_date, event_slug)
            WHERE status = 'published'
    """)


def _migrate_add_events_table(cur):
    """Create the events table for SEO event hub pages (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_slug          TEXT PRIMARY KEY,
            gamma_event_id      TEXT,
            title               TEXT,
            description         TEXT,
            image               TEXT,
            icon                TEXT,
            start_date          TIMESTAMPTZ,
            end_date            TIMESTAMPTZ,
            tags                TEXT DEFAULT '[]',
            seo_title           TEXT,
            seo_description     TEXT,
            seo_summary         TEXT,
            seo_faqs            TEXT DEFAULT '[]',
            seo_generated_at    TIMESTAMPTZ,
            fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_refreshed_at   TIMESTAMPTZ
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_end_date ON events(end_date)
    """)


def _migrate_add_graded_calls(cur):
    """Create the graded_calls table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS graded_calls (
            condition_id     TEXT PRIMARY KEY,
            alert_id         INTEGER NOT NULL,
            event_slug       TEXT,
            market_title     TEXT,
            outcome          TEXT NOT NULL,
            entry_price      DOUBLE PRECISION NOT NULL,
            resolved_outcome TEXT NOT NULL,
            won              BOOLEAN NOT NULL,
            return_pct       DOUBLE PRECISION NOT NULL,
            composite_score  DOUBLE PRECISION NOT NULL,
            resolved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            graded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_graded_calls_resolved
            ON graded_calls(resolved_at DESC)
    """)


def _migrate_add_subscribers(cur):
    """Create the subscribers table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id                SERIAL PRIMARY KEY,
            email             TEXT NOT NULL UNIQUE,
            source            TEXT,
            confirmed         BOOLEAN NOT NULL DEFAULT TRUE,
            unsubscribe_token UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            unsubscribed_at   TIMESTAMPTZ
        )
    """)


def _migrate_add_digests(cur):
    """Create the digests table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS digests (
            id            SERIAL PRIMARY KEY,
            digest_date   DATE NOT NULL UNIQUE,
            run_id        TEXT,
            subject       TEXT NOT NULL,
            intro         TEXT,
            content_json  JSONB NOT NULL,
            status        TEXT NOT NULL DEFAULT 'published',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_digests_date ON digests(digest_date DESC)"
    )
