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
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

function TickerItem({ alert }) {
  const headline = alert.market_title || "Notable trade";
  const amount = usdFmt.format(alert.total_usd);
  const time = relativeTime(alert.scanned_at);

  return (
    <Link
      href={`/market/${marketSlug(alert.market_title, alert.condition_id)}`}
      className="inline-flex items-center gap-2 whitespace-nowrap px-5 hover:opacity-80 transition-opacity"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-blue-500 dark:bg-blue-400 shrink-0" />
      <span className="font-medium text-gray-900 dark:text-gray-100">{amount}</span>
      <span className="text-gray-500 dark:text-gray-400 max-w-[280px] truncate">{headline}</span>
      <span className="text-gray-400 dark:text-gray-500 text-xs">{time}</span>
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
    <div className="overflow-hidden border-b border-gray-200 bg-gray-50/80 dark:border-gray-800 dark:bg-gray-900/50 py-2 text-sm">
      <div className="ticker-track flex">
        {[...alerts, ...alerts].map((alert, i) => (
          <TickerItem key={`${alert.condition_id}-${i}`} alert={alert} />
        ))}
      </div>
    </div>
  );
}
