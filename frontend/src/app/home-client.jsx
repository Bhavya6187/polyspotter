"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchMarketAlerts, fetchHealth } from "../lib/api";
import Filters from "../components/Filters";
import AlertTable from "../components/AlertTable";
import Pagination from "../components/Pagination";
import Ticker from "../components/Ticker";
import ThemeToggle from "../components/ThemeToggle";

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
  const [healthy, setHealthy] = useState(null);

  // Check health on mount
  useEffect(() => {
    fetchHealth()
      .then(() => setHealthy(true))
      .catch(() => setHealthy(false));
  }, []);

  // Re-fetch when page or filters change (skip initial load — we have SSR data)
  const [hasInteracted, setHasInteracted] = useState(false);

  useEffect(() => {
    if (!hasInteracted) return;
    setLoading(true);
    fetchMarketAlerts({
      page,
      perPage,
      tag: filters.tag,
    })
      .then((data) => {
        setMarkets(data.markets || []);
        setTotal(data.total || 0);
      })
      .catch(() => {
        setMarkets([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [page, perPage, filters, hasInteracted]);

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
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${
                healthy === true
                  ? "bg-green-500"
                  : healthy === false
                    ? "bg-red-500"
                    : "bg-gray-400 dark:bg-gray-600"
              }`}
              aria-label={
                healthy === true
                  ? "API healthy"
                  : healthy === false
                    ? "API unreachable"
                    : "Checking API..."
              }
            />
            {healthy === true
              ? "Connected"
              : healthy === false
                ? "Disconnected"
                : "Checking..."}
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
