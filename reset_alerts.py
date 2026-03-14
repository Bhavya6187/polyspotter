"""
One-time script to clear all alerts from both Railway Postgres and local SQLite
so they can be re-ingested with LLM summaries.
"""

import os
import sqlite3

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
LOCAL_DB = os.path.join(os.path.dirname(__file__), "polybot.db")


def clear_postgres():
    if not DATABASE_URL:
        print("[!] DATABASE_URL not set — skipping Postgres cleanup.")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Add llm_summary column if it doesn't exist yet
    cur.execute("""
        ALTER TABLE alerts ADD COLUMN IF NOT EXISTS llm_summary TEXT
    """)

    cur.execute("DELETE FROM alert_signals")
    sig_count = cur.rowcount
    cur.execute("DELETE FROM alert_trades")
    trade_count = cur.rowcount
    cur.execute("DELETE FROM alerts")
    alert_count = cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    print(f"[Postgres] Deleted {alert_count} alerts, {trade_count} trades, {sig_count} signals.")


def clear_local_cache():
    if not os.path.exists(LOCAL_DB):
        print("[!] No local polybot.db found — skipping.")
        return

    conn = sqlite3.connect(LOCAL_DB)

    # Check if llm_evaluations table exists
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_evaluations'"
    ).fetchone()

    if table:
        conn.execute("DELETE FROM llm_evaluations")
        count = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        print(f"[SQLite]   Deleted {count} cached LLM evaluations.")
    else:
        print("[SQLite]   No llm_evaluations table found — nothing to clear.")

    conn.close()


if __name__ == "__main__":
    print("Clearing alerts so they can be re-ingested with LLM summaries...\n")
    clear_postgres()
    clear_local_cache()
    print("\nDone. Run polybot.py to re-scan and ingest with LLM filtering.")
