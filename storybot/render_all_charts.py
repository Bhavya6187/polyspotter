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
    return 0


if __name__ == "__main__":
    sys.exit(main())
