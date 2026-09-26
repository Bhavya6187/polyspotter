#!/usr/bin/env python
"""One-off / manual retention pass for polybot.db.

The scanner now prunes daily (db.prune_old_rows, called from polybot.run),
but with a 60s time budget per pass it would take a long time to chew
through the historical backlog: at review time price_candles held 27.1M rows
of which 24M were older than 30 days, and wallet_pnl held 8.2M rows for
wallets idle for 90+ days (22 of the DB's 27 GB, indexes included).

    source venv/bin/activate
    python scripts/prune_sqlite.py --dry-run      # counts only
    python scripts/prune_sqlite.py                # delete in batches
    python scripts/prune_sqlite.py --vacuum       # ... then reclaim disk

VACUUM rewrites the whole database: it needs free disk roughly equal to the
live data, holds an exclusive lock for the duration, and fails with
"database is locked" if the scanner is writing -- stop the scanner first
(screen -r polybot, Ctrl-C) and restart it afterwards. Deleting without
--vacuum is safe while the scanner runs; the freed pages are reused by new
writes, the file just doesn't shrink.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


def _count(sql: str, *params) -> int:
    return db.get_db().execute(sql, params).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candle-days", type=int, default=db.CANDLE_RETENTION_DAYS)
    ap.add_argument("--pnl-days", type=int, default=db.WALLET_PNL_RETENTION_DAYS)
    ap.add_argument("--dry-run", action="store_true", help="report row counts, delete nothing")
    ap.add_argument("--vacuum", action="store_true", help="VACUUM afterwards to shrink the file (see docstring)")
    args = ap.parse_args()

    size_gb = os.path.getsize(db.DB_PATH) / 1e9
    print(f"[prune] {db.DB_PATH} is {size_gb:.1f} GB")

    candle_cutoff = time.time() - args.candle_days * 86400
    old_candles = _count("SELECT COUNT(*) FROM price_candles WHERE t < ?", candle_cutoff)
    total_candles = _count("SELECT COUNT(*) FROM price_candles")
    print(f"[prune] price_candles: {old_candles:,} of {total_candles:,} rows older than {args.candle_days}d")

    from datetime import datetime, timedelta, timezone
    pnl_cutoff = (datetime.now(timezone.utc) - timedelta(days=args.pnl_days)).isoformat()
    stale_wallets = _count(
        "SELECT COUNT(*) FROM (SELECT wallet FROM wallet_pnl GROUP BY wallet HAVING MAX(recorded_at) < ?)",
        pnl_cutoff,
    )
    total_wallets = _count("SELECT COUNT(DISTINCT wallet) FROM wallet_pnl")
    print(f"[prune] wallet_pnl: {stale_wallets:,} of {total_wallets:,} wallets idle for {args.pnl_days}d+")

    if args.dry_run:
        print("[prune] dry run — nothing deleted")
        return 0

    t0 = time.monotonic()
    n = db.prune_price_candles(max_age_days=args.candle_days)
    print(f"[prune] deleted {n:,} price_candles in {time.monotonic() - t0:.0f}s")
    t0 = time.monotonic()
    n = db.prune_stale_wallet_pnl(max_age_days=args.pnl_days)
    print(f"[prune] deleted {n:,} wallet_pnl rows in {time.monotonic() - t0:.0f}s")

    if args.vacuum:
        print("[prune] VACUUM (this can take a long time and needs ~1x free disk)...", flush=True)
        t0 = time.monotonic()
        db.get_db().execute("VACUUM")
        print(f"[prune] VACUUM done in {time.monotonic() - t0:.0f}s; "
              f"file is now {os.path.getsize(db.DB_PATH) / 1e9:.1f} GB")
    else:
        print("[prune] skipped VACUUM — freed pages will be reused; pass --vacuum to shrink the file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
