"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchMarketAlerts } from "../lib/api";
import Filters from "../components/Filters";
import AlertTable from "../components/AlertTable";
import Pagination from "../components/Pagination";
import Ticker from "../components/Ticker";
import ThemeToggle from "../components/ThemeToggle";

function formatRelativeTime(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export default function HomeClient({ initialMarkets, initialTotal, tags }) {
  const [markets, setMarkets] = useState(initialMarkets);
  const [total, setTotal] = useState(initialTotal);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [filters, setFilters] = useState({
    tag: "",
    resolvesIn: "",
  });
  const [expandedMarketIds, setExpandedMarketIds] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(() => new Date());
  const [, setTick] = useState(0);

  // Tick every 10s to keep relative time fresh
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 10_000);
    return () => clearInterval(id);
  }, []);

  // Stable refs for fetch params so the refresh callback doesn't go stale
  const pageRef = useRef(page);
  const filtersRef = useRef(filters);
  pageRef.current = page;
  filtersRef.current = filters;

  const refresh = useCallback(() => {
    setLoading(true);
    fetchMarketAlerts({
      page: pageRef.current,
      perPage,
      tag: filtersRef.current.tag,
    })
      .then((data) => {
        setMarkets(data.markets || []);
        setTotal(data.total || 0);
        setLastUpdated(new Date());
      })
      .catch(() => {
        setMarkets([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [perPage]);

  // Re-fetch when page or filters change (skip initial load — we have SSR data)
  const [hasInteracted, setHasInteracted] = useState(false);

  useEffect(() => {
    if (!hasInteracted) return;
    refresh();
  }, [page, filters, hasInteracted, refresh]);

  // Auto-refresh every 60s
  useEffect(() => {
    const id = setInterval(refresh, 300_000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleFilterChange = useCallback((newFilters) => {
    setHasInteracted(true);
    setFilters(newFilters);
    setPage(1);
    setExpandedMarketIds(new Set());
  }, []);

  const handlePageChange = useCallback((newPage) => {
    setHasInteracted(true);
    setPage(newPage);
  }, []);

  const handleToggleMarket = useCallback((conditionId) => {
    setExpandedMarketIds((prev) => {
      const next = new Set(prev);
      if (next.has(conditionId)) next.delete(conditionId);
      else next.add(conditionId);
      return next;
    });
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      {/* Header */}
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50">PolySpotter</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Large bets. Sharp wallets. Early signals.</p>
        </div>
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <div className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
            <span>Updated {formatRelativeTime(lastUpdated)}</span>
            <button
              onClick={refresh}
              disabled={loading}
              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              aria-label="Refresh data"
            >
              <svg
                className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4.5 15.5A8.5 8.5 0 0119.5 8.5M19.5 8.5A8.5 8.5 0 014.5 15.5" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Live ticker */}
      <div className="mb-4 -mx-4 sm:mx-0 sm:rounded-lg sm:overflow-hidden">
        <Ticker />
      </div>

      {/* Filters */}
      <div className="mb-4">
        <Filters
          tags={tags}
          filters={filters}
          onFilterChange={handleFilterChange}
        />
      </div>

      {/* Market Cards */}
      <AlertTable
        markets={markets}
        expandedMarketIds={expandedMarketIds}
        onToggleMarket={handleToggleMarket}
        onFilterChange={handleFilterChange}
        filters={filters}
        loading={loading}
      />

      {/* Pagination */}
      <Pagination
        page={page}
        totalPages={totalPages}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
