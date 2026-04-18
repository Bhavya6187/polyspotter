// TODO(cleanup): unused after polyspotter redesign 2026-04-17.
// Kept in-tree temporarily — verify via grep across /app + /components,
// then delete in a follow-up PR. See spec §3.6.
import { Fragment, useState, useEffect } from "react";
import Link from "next/link";
import AlertRow from "./AlertRow";
import StrengthMeter from "./StrengthMeter";
import { fetchMarketLive } from "../lib/api";
import { marketSlug } from "../lib/slugify";

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const now = Date.now();
  const end = new Date(dateStr).getTime();
  const diffMs = end - now;
  if (diffMs <= 0) return null; // resolved markets filtered out by backend
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

function SortIcon({ column, sortBy, sortDir }) {
  if (sortBy !== column) {
    return (
      <svg className="ml-1 inline h-3 w-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
      </svg>
    );
  }
  return sortDir === "asc" ? (
    <svg className="ml-1 inline h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
    </svg>
  ) : (
    <svg className="ml-1 inline h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function getSortValue(market, key) {
  switch (key) {
    case "amount":
      return market.total_usd || 0;
    case "strength":
      return market.max_score || 0;
    case "resolution":
      return market.end_date ? new Date(market.end_date).getTime() : Infinity;
    case "detected":
      return market.scanned_at ? new Date(market.scanned_at).getTime() : 0;
    default:
      return 0;
  }
}

export default function AlertTable({
  markets,
  expandedMarketIds,
  onToggleMarket,
  onFilterChange,
  filters,
  loading,
}) {
  const [sortBy, setSortBy] = useState("amount");
  const [sortDir, setSortDir] = useState("desc");
  const [liveData, setLiveData] = useState({}); // condition_id -> LiveMarketData
  const [showAllAlerts, setShowAllAlerts] = useState(new Set()); // condition_ids showing all alerts

  // Fetch live market data when a market is expanded
  useEffect(() => {
    if (!expandedMarketIds || expandedMarketIds.size === 0) return;

    for (const cid of expandedMarketIds) {
      if (liveData[cid]) continue; // already fetched
      fetchMarketLive(cid)
        .then((data) => setLiveData((prev) => ({ ...prev, [cid]: data })))
        .catch(() => {}); // silently fail — live data is optional
    }
  }, [expandedMarketIds]);

  const handleSort = (column) => {
    if (sortBy === column) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortDir("desc");
    }
  };

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        Loading alerts...
      </div>
    );
  }

  if (!markets || markets.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        No alerts found.
      </div>
    );
  }

  // Client-side resolve window filter
  const resolvesInMs = {
    "6h": 21600000,
    "24h": 86400000,
    "7d": 604800000,
  }[filters.resolvesIn] || null;

  const filtered = resolvesInMs
    ? markets.filter((m) => {
        if (!m.end_date) return false;
        const ms = new Date(m.end_date).getTime() - Date.now();
        return ms > 0 && ms <= resolvesInMs;
      })
    : markets;

  const sorted = [...filtered].sort((a, b) => {
    const va = getSortValue(a, sortBy);
    const vb = getSortValue(b, sortBy);
    return sortDir === "asc" ? va - vb : vb - va;
  });

  const thClass =
    "cursor-pointer select-none px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors";

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 dark:bg-gray-900">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Market
            </th>
            <th className={thClass} onClick={() => handleSort("strength")}>
              Signal
              <SortIcon column="strength" sortBy={sortBy} sortDir={sortDir} />
            </th>
            <th className={thClass} onClick={() => handleSort("amount")}>
              Amount
              <SortIcon column="amount" sortBy={sortBy} sortDir={sortDir} />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Alerts
            </th>
            <th className={thClass} onClick={() => handleSort("resolution")}>
              Resolves in
              <SortIcon column="resolution" sortBy={sortBy} sortDir={sortDir} />
            </th>
            <th className={thClass} onClick={() => handleSort("detected")}>
              Detected
              <SortIcon column="detected" sortBy={sortBy} sortDir={sortDir} />
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Tags
            </th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {sorted.map((market) => {
            const isExpanded = expandedMarketIds.has(market.condition_id);
            const resolution = timeToResolution(market.end_date);
            const tags = market.tags || [];

            const resolutionMs = market.end_date
              ? new Date(market.end_date).getTime() - Date.now()
              : null;
            const resColor =
              resolutionMs != null && resolutionMs < 3600000
                ? "text-red-500 dark:text-red-400 font-medium"
                : resolutionMs != null && resolutionMs < 86400000
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-gray-600 dark:text-gray-300";

            return (
              <Fragment key={market.condition_id}>
                <tr
                  onClick={() => onToggleMarket(market.condition_id)}
                  className={`cursor-pointer transition-colors hover:bg-gray-50 dark:hover:bg-gray-900/50 ${
                    isExpanded
                      ? "bg-gray-50 dark:bg-gray-900/50"
                      : "bg-white dark:bg-gray-950"
                  }`}
                >
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100 max-w-xs">
                    <div className="flex items-center gap-2">
                      <svg
                        className={`h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500 transition-transform duration-200 ${
                          isExpanded ? "rotate-90" : ""
                        }`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                      <Link
                        href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
                        onClick={(e) => e.stopPropagation()}
                        className="truncate hover:underline"
                      >
                        {market.market_title ?? "\u2014"}
                      </Link>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <StrengthMeter maxScore={market.max_score} />
                  </td>
                  <td className="px-4 py-3 text-gray-700 dark:text-gray-200 whitespace-nowrap">
                    {usdFmt.format(market.total_usd)}
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                    {market.alert_count}
                  </td>
                  <td className={`px-4 py-3 whitespace-nowrap ${resColor}`}>
                    {resolution ?? "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap" suppressHydrationWarning>
                    {relativeTime(market.scanned_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {tags.slice(0, 3).map((t) => (
                        <Link
                          key={t}
                          href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}
                          onClick={(e) => e.stopPropagation()}
                          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                            filters.tag === t
                              ? "bg-blue-600 text-blue-50 dark:bg-blue-700 dark:text-blue-100"
                              : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
                          }`}
                        >
                          {t}
                        </Link>
                      ))}
                      {tags.length > 3 && (
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          +{tags.length - 3}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                      title={market.market_title}
                    >
                      View trades
                      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </Link>
                  </td>
                </tr>
                {isExpanded && market.alerts && market.alerts.length > 0 && (
                  <tr>
                    <td colSpan={8} className="bg-gray-50 px-4 pb-4 pt-2 dark:bg-gray-900/80">
                      <div className="flex flex-col gap-2">
                        {(showAllAlerts.has(market.condition_id)
                          ? market.alerts
                          : market.alerts.slice(0, 2)
                        ).map((alert) => (
                          <AlertRow
                            key={alert.id}
                            alert={alert}
                            autoExpand
                            activeTag={filters.tag}
                            onTagClick={(t) =>
                              onFilterChange({
                                ...filters,
                                tag: filters.tag === t ? "" : t,
                              })
                            }
                            compact
                            liveMarket={liveData[market.condition_id]}
                          />
                        ))}
                        {market.alerts.length > 2 && !showAllAlerts.has(market.condition_id) && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setShowAllAlerts((prev) => new Set(prev).add(market.condition_id));
                            }}
                            className="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
                          >
                            Show {market.alerts.length - 2} older alert{market.alerts.length - 2 === 1 ? "" : "s"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
