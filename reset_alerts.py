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

    cur.execute("DROP TABLE IF EXISTS alert_signals")
    cur.execute("DROP TABLE IF EXISTS alert_trades")
    cur.execute("DROP TABLE IF EXISTS wallet_profiles")
    cur.execute("DROP TABLE IF EXISTS alerts")
    cur.execute("DROP TABLE IF EXISTS scan_runs")

    conn.commit()
    cur.close()
    conn.close()

    print("[Postgres] Dropped alerts, alert_trades, alert_signals, wallet_profiles, scan_runs tables.")


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

    # Clear scan_runs table
    scan_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_runs'"
    ).fetchone()

    if scan_table:
        conn.execute("DELETE FROM scan_runs")
        count = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        print(f"[SQLite]   Deleted {count} scan run(s).")
    else:
        print("[SQLite]   No scan_runs table found — nothing to clear.")

    conn.close()


if __name__ == "__main__":
    print("Clearing alerts so they can be re-ingested with LLM summaries...\n")
    clear_postgres()
    clear_local_cache()
    print("\nDone. Run polybot.py to re-scan and ingest with LLM filtering.")
