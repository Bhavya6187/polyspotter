"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchMarketAlerts } from "../lib/api";
import Filters from "../components/Filters";
import AlertList from "../components/AlertList";
import Pagination from "../components/Pagination";
import Ticker from "../components/Ticker";
import ThemeToggle from "../components/ThemeToggle";
import HeroSpotlight from "../components/HeroSpotlight";
import ResolvingSoonStrip from "../components/ResolvingSoonStrip";
import CommandPalette from "../components/CommandPalette";
import TopicNav from "../components/TopicNav";
import BrandMark from "../components/BrandMark";

function formatRelativeTime(date) {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export default function HomeClient({ initialMarkets, initialTotal, tags, initialTheses, topWallets }) {
  const [markets, setMarkets] = useState(initialMarkets);
  const [total, setTotal] = useState(initialTotal);
  const [theses] = useState(initialTheses || []);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [filters, setFilters] = useState({
    tag: "",
    resolvesIn: "",
    minScore: "",
  });
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(() => new Date());
  const [, setTick] = useState(0);

  // Tick every 10s to keep relative time fresh
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 10_000);
    return () => clearInterval(id);
  }, []);

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
      resolvesWithin: filtersRef.current.resolvesIn,
      minScore: filtersRef.current.minScore || undefined,
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

  const [hasInteracted, setHasInteracted] = useState(false);

  // Load saved filters from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem("polyspotter_filters");
      if (saved) {
        const parsed = JSON.parse(saved);
        setFilters((prev) => ({ ...prev, ...parsed }));
        setHasInteracted(true);
      }
    } catch {}
  }, []);

  // Persist filters to localStorage on change
  useEffect(() => {
    if (!hasInteracted) return;
    try {
      localStorage.setItem("polyspotter_filters", JSON.stringify(filters));
    } catch {}
  }, [filters, hasInteracted]);

  useEffect(() => {
    if (!hasInteracted) return;
    refresh();
  }, [page, filters, hasInteracted, refresh]);

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const id = setInterval(refresh, 300_000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleFilterChange = useCallback((newFilters) => {
    setHasInteracted(true);
    setFilters(newFilters);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage) => {
    setHasInteracted(true);
    setPage(newPage);
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / perPage));


  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <BrandMark />
          <div className="flex items-center gap-3">
            <CommandPalette tags={tags} topWallets={topWallets || []} />
            <ThemeToggle />
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
              <span className="flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="animate-pulse-live absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: 'var(--accent)' }} />
                  <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: 'var(--accent)' }} />
                </span>
                Live
              </span>
              <span className="mx-1" style={{ color: 'var(--border)' }}>|</span>
              <span>{formatRelativeTime(lastUpdated)}</span>
              <button
                onClick={refresh}
                disabled={loading}
                className="rounded-md p-1 transition-colors hover:opacity-70 disabled:opacity-40"
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
        </div>
      </header>

      {/* Topic navigation */}
      <TopicNav tags={tags} />

      {/* Hero Spotlight */}
      <section aria-label="Spotlight" className="mb-5">
        <HeroSpotlight />
      </section>

      {/* Live ticker — hidden on mobile, duplicates feed */}
      <section aria-label="Live ticker" className="hidden sm:block mb-5 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
        <Ticker />
      </section>

      {/* Resolving Soon */}
      <section aria-label="Resolving soon" className="mb-5">
        <ResolvingSoonStrip />
      </section>

      {/* Filters */}
      <section aria-label="Filters" className="mb-5">
        <Filters
          tags={tags}
          filters={filters}
          onFilterChange={handleFilterChange}
        />
      </section>

      {/* Alert List */}
      <section aria-label="Notable trades">
        <h2 className="sr-only" aria-hidden="true">Notable Trades</h2>
        <AlertList
          markets={markets}
          filters={filters}
          loading={loading}
          theses={theses}
        />
      </section>


      {/* Pagination */}
      <nav aria-label="Pagination">
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
        />
      </nav>
    </main>
  );
}
