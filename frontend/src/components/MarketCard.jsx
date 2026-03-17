import AlertRow from "./AlertRow";
import AlertDetail from "./AlertDetail";
import { useState } from "react";

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const now = Date.now();
  const end = new Date(dateStr).getTime();
  const diffMs = end - now;
  if (diffMs <= 0) return "Resolved";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d`;
}

function relativeTime(dateStr) {
  if (!dateStr) return "\u2014";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export default function MarketCard({ market, isExpanded, onToggle, activeTag, onTagClick }) {
  const [expandedAlertId, setExpandedAlertId] = useState(null);
  const resolution = timeToResolution(market.end_date);
  const tags = market.tags || [];

  return (
    <div
      className={`rounded-lg border transition-all ${
        isExpanded
          ? "border-blue-300 shadow-md dark:border-blue-700"
          : "border-gray-200 dark:border-gray-800"
      }`}
    >
      {/* Market header — always visible */}
      <div
        onClick={onToggle}
        className="cursor-pointer rounded-lg bg-white p-4 dark:bg-gray-900"
      >
        {/* Row 1: Market title + resolution */}
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug">
            {market.market_title ?? "\u2014"}
          </h3>
          <div className="flex shrink-0 items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
            {resolution && (
              <span
                className={
                  resolution === "Resolved"
                    ? "text-gray-400 dark:text-gray-600"
                    : new Date(market.end_date).getTime() - Date.now() < 3600000
                      ? "font-medium text-red-500 dark:text-red-400"
                      : new Date(market.end_date).getTime() - Date.now() < 86400000
                        ? "text-amber-600 dark:text-amber-400"
                        : ""
                }
              >
                {resolution}
              </span>
            )}
            <span>{relativeTime(market.scanned_at)}</span>
          </div>
        </div>

        {/* Row 2: Aggregate stats */}
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
          {usdFmt.format(market.total_usd)} across {market.alert_count} alert{market.alert_count !== 1 ? "s" : ""}
        </p>

        {/* Row 3: Tags */}
        {tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {tags.map((t) => (
              <span
                key={t}
                role="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onTagClick(t);
                }}
                className={`inline-block cursor-pointer rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                  activeTag === t
                    ? "bg-blue-600 text-blue-50 dark:bg-blue-700 dark:text-blue-100"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
                }`}
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expanded: individual alerts */}
      {isExpanded && market.alerts && market.alerts.length > 0 && (
        <div className="border-t border-gray-100 bg-gray-50 px-3 pb-3 pt-2 dark:border-gray-800 dark:bg-gray-950">
          <div className="flex flex-col gap-2">
            {market.alerts.map((alert) => (
              <div key={alert.id}>
                <AlertRow
                  alert={alert}
                  isExpanded={expandedAlertId === alert.id}
                  onToggle={() =>
                    setExpandedAlertId((prev) =>
                      prev === alert.id ? null : alert.id
                    )
                  }
                  activeTag={activeTag}
                  onTagClick={onTagClick}
                  compact
                />
                {expandedAlertId === alert.id && <AlertDetail alertId={alert.id} />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
