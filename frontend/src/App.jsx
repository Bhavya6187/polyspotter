import { useState, useEffect, useCallback } from "react";
import { fetchMarketAlerts, fetchTags, fetchHealth } from "./api";
import Filters from "./components/Filters";
import AlertTable from "./components/AlertTable";
import Pagination from "./components/Pagination";
import ThemeToggle from "./components/ThemeToggle";

export default function App() {
  const [markets, setMarkets] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [filters, setFilters] = useState({
    tag: "",
  });
  const [expandedMarketId, setExpandedMarketId] = useState(null);
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [healthy, setHealthy] = useState(null);

  // Fetch categories + health on mount
  useEffect(() => {
    fetchTags()
      .then((data) => setTags(data.tags || data || []))
      .catch(() => {});
    fetchHealth()
      .then(() => setHealthy(true))
      .catch(() => setHealthy(false));
  }, []);

  // Fetch markets when page or filters change
  useEffect(() => {
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
  }, [page, perPage, filters]);

  const handleFilterChange = useCallback((newFilters) => {
    setFilters(newFilters);
    setPage(1);
    setExpandedMarketId(null);
  }, []);

  const handleToggleMarket = useCallback((conditionId) => {
    setExpandedMarketId((prev) => (prev === conditionId ? null : conditionId));
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {/* Header */}
        <header className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50">Polybot</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">Smart Trade Alerts</p>
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
          expandedMarketId={expandedMarketId}
          onToggleMarket={handleToggleMarket}
          onFilterChange={handleFilterChange}
          filters={filters}
          loading={loading}
        />

        {/* Pagination */}
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
