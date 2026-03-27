import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchMarketAlerts } from "../lib/api";
import { marketSlug } from "../lib/slugify";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function relativeTime(dateStr) {
  if (!dateStr) return "";
  const diffSec = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (diffSec < 60) return `${diffSec}s`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

function TickerItem({ alert }) {
  const headline = alert.market_title || "Notable trade";
  const bestAlert = alert.alerts?.[0];
  const amount = usdFmt.format(bestAlert?.total_usd || 0);
  const time = relativeTime(bestAlert?.scanned_at || bestAlert?.created_at);
  const side = bestAlert?.llm_copy_action?.side;
  const isBuy = side === "BUY" || !side;

  return (
    <Link
      href={`/market/${marketSlug(alert.market_title, alert.condition_id)}`}
      className="inline-flex items-center gap-2.5 whitespace-nowrap px-5 cursor-pointer rounded-md py-1 transition-all hover:bg-[var(--surface-2)]"
    >
      <span
        className="h-1.5 w-1.5 rounded-full shrink-0"
        style={{ background: isBuy ? 'var(--bullish)' : 'var(--bearish)' }}
      />
      <span className="font-semibold" style={{ fontFamily: 'var(--font-display)', fontSize: '0.8rem', color: isBuy ? 'var(--bullish)' : 'var(--bearish)' }}>
        {amount}
      </span>
      <span className="max-w-[260px] truncate text-sm" style={{ color: 'var(--text-secondary)' }}>
        {headline}
      </span>
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{time}</span>
    </Link>
  );
}

export default function Ticker() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    fetchMarketAlerts({ page: 1, perPage: 20 })
      .then((data) => setAlerts(data.markets || []))
      .catch(() => {});

    const interval = setInterval(() => {
      fetchMarketAlerts({ page: 1, perPage: 20 })
        .then((data) => setAlerts(data.markets || []))
        .catch(() => {});
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div
      className="overflow-hidden border-y py-2.5 text-sm"
      style={{ borderColor: 'var(--border-subtle)', background: 'var(--surface-1)' }}
    >
      <div className="ticker-track flex">
        {[...alerts, ...alerts].map((alert, i) => (
          <TickerItem key={`${alert.condition_id}-${i}`} alert={alert} />
        ))}
      </div>
    </div>
  );
}
