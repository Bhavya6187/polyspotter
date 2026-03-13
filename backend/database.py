"""
Database connection and initialization for the Polybot backend.

Uses psycopg2 with a simple connection pool pattern.
Reads DATABASE_URL from environment.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:mxZEWMtgEmTHxIMPkyxCqqTIYVZaJMRX@localhost:5432/railway",
)


def get_conn():
    """Return a new database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Run schema.sql to create tables if they don't exist."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()
