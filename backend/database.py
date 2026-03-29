"""
Database connection and initialization for the Polybot backend.

Uses psycopg2 with a simple connection pool pattern.
Reads DATABASE_URL from environment.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


def get_conn():
    """Return a new database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


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
