"""Dev smoke tool: render all four chart types for a recent alert.

Run via:
    source venv/bin/activate
    python storybot/render_all_charts.py [alert_id]

If no alert_id is given, pulls the most recent alert with at least one signal.
Outputs go to storybot/dry_runs/<chart_type>_<alert_id>.png.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chart_grid  # noqa: E402
import charts  # noqa: E402
import tweet_utils  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "dry_runs"


def fetch_alert(alert_id: int | None) -> dict | None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if alert_id is not None:
            cur.execute("SELECT * FROM alerts WHERE id = %s", (alert_id,))
        else:
            cur.execute("""
                SELECT * FROM alerts
                ORDER BY created_at DESC
                LIMIT 1
            """)
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return dict(row) if row else None


def main() -> int:
    alert_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    alert = fetch_alert(alert_id)
    if alert is None:
        print(f"No alert found (id={alert_id})", file=sys.stderr)
        return 1
    print(f"Using alert id={alert['id']} market='{alert.get('market_title')}'")

    tweet_utils.enrich_alert_for_charts(alert)
    print(f"  enriched: trades={len(alert.get('trades') or [])}, "
          f"token_id={'set' if alert.get('token_id') else 'unset'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for chart_type in ("wallet_record_card", "volume_bar", "cluster_card", "price_sparkline"):
        png = charts.render_chart_for_alert(chart_type, alert)
        out = OUTPUT_DIR / f"{chart_type}_{alert['id']}.png"
        if png is None:
            print(f"  {chart_type}: SKIPPED (data unavailable / fallback returned None)")
            continue
        out.write_bytes(png)
        print(f"  {chart_type}: wrote {out} ({len(png)} bytes)")

    # Grid renders — preview hero + 3 stat tiles for each hero type. Uses
    # a synthetic facts_bundle so tiles exercise their renderers regardless
    # of which signals fired on this specific alert.
    fb = {
        "minutes_to_resolution": 214,
        "total_usd": 220_000,
        "cluster_size": 7,
        "has_volume_spike": True,
        "volume_multiplier_x": 12.0,
        "biggest_price_move": {"from": 0.60, "to": 0.62},
        "has_sharp_wallet": {"record": "24-1", "win_pct": 0.96,
                             "wallet": alert.get("wallet") or "0xabc",
                             "alert_id": alert["id"], "bet_usd": 7_000},
        "has_fresh_wallet": None,
        "distinct_wallets": 15,
        "trade_count": 30, "time_span_minutes": 129,
        "peak_hour_volume_usd": 140_000,
    }
    for hero_type in ("wallet_record_card", "fresh_wallet_card", "volume_bar",
                      "cluster_card", "price_sparkline"):
        png = chart_grid.compose_chart(
            hero_type=hero_type, alert=alert, facts_bundle=fb,
        )
        out = OUTPUT_DIR / f"grid_{hero_type}_{alert['id']}.png"
        if png is None:
            print(f"  grid_{hero_type}: SKIPPED (fetcher returned None)")
            continue
        out.write_bytes(png)
        print(f"  grid_{hero_type}: wrote {out} ({len(png)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
