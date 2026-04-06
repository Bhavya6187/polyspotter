"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { fetchMarketAlerts } from "../lib/api";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);
  const router = useRouter();

  // Debounced search
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }

    setLoading(true);
    const id = setTimeout(() => {
      fetchMarketAlerts({ page: 1, perPage: 8, q: query.trim() })
        .then((data) => {
          setResults(data.markets || []);
          setOpen(true);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);

    return () => clearTimeout(id);
  }, [query]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Cmd+K shortcut to focus
  useEffect(() => {
    function handleGlobalKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleGlobalKey);
    return () => document.removeEventListener("keydown", handleGlobalKey);
  }, []);

  const handleKeyDown = useCallback(
    (e) => {
      if (!open) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && activeIndex >= 0 && results[activeIndex]) {
        e.preventDefault();
        navigateTo(results[activeIndex].condition_id);
      } else if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    },
    [open, activeIndex, results]
  );

  function navigateTo(conditionId) {
    setOpen(false);
    setQuery("");
    router.push(`/market/${conditionId}`);
  }

  function highlightMatch(text) {
    if (!query.trim() || !text) return text;
    const idx = text.toLowerCase().indexOf(query.trim().toLowerCase());
    if (idx === -1) return text;
    const before = text.slice(0, idx);
    const match = text.slice(idx, idx + query.trim().length);
    const after = text.slice(idx + query.trim().length);
    return (
      <>
        {before}
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>{match}</span>
        {after}
      </>
    );
  }

  const showDropdown = open && (loading || results.length > 0 || query.trim().length > 0);

  return (
    <>
      {/* Backdrop scrim when dropdown is open */}
      {showDropdown && (
        <div
          className="fixed inset-0 z-40"
          style={{ background: "rgba(0,0,0,0.2)", backdropFilter: "blur(2px)" }}
          onClick={() => setOpen(false)}
        />
      )}

      <div ref={wrapperRef} className="relative z-50">
        {/* Search input */}
        <div className="relative">
          <svg
            className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 pointer-events-none"
            style={{ color: "var(--text-muted)" }}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
            />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(-1);
            }}
            onFocus={() => results.length > 0 && setOpen(true)}
            onKeyDown={handleKeyDown}
            placeholder="Search markets..."
            className="w-44 sm:w-56 rounded-lg border py-1.5 pl-8 pr-14 text-xs transition-colors focus:outline-none focus:ring-1"
            style={{
              background: "var(--bg-secondary, var(--surface-1))",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
              "--tw-ring-color": "var(--accent)",
            }}
          />
          {/* Keyboard shortcut hint */}
          {!query && (
            <kbd
              className="absolute right-2 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium border"
              style={{
                color: "var(--text-muted)",
                borderColor: "var(--border)",
                background: "var(--surface-0, var(--bg-primary))",
              }}
            >
              &#8984;K
            </kbd>
          )}
          {/* Clear button */}
          {query && (
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-0.5 transition-colors hover:opacity-70"
              onClick={() => {
                setQuery("");
                setResults([]);
                setOpen(false);
                inputRef.current?.focus();
              }}
              aria-label="Clear search"
            >
              <svg className="h-3.5 w-3.5" style={{ color: "var(--text-muted)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Dropdown overlay */}
        {showDropdown && (
          <div
            className="absolute right-0 top-full mt-2 rounded-xl border overflow-hidden"
            style={{
              background: "var(--surface-card, var(--bg-primary))",
              borderColor: "var(--border)",
              boxShadow: "0 16px 48px rgba(0,0,0,0.15), 0 4px 12px rgba(0,0,0,0.08)",
              width: "min(420px, calc(100vw - 32px))",
            }}
          >
            {/* Results header */}
            <div
              className="flex items-center justify-between px-4 py-2.5 border-b"
              style={{ borderColor: "var(--border-subtle, var(--border))" }}
            >
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Markets
              </span>
              {loading && (
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
                  <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>Searching</span>
                </div>
              )}
              {!loading && results.length > 0 && (
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                  {results.length} result{results.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>

            {/* Results list */}
            {results.length === 0 && !loading ? (
              <div className="px-4 py-8 text-center">
                <svg className="mx-auto h-8 w-8 mb-2" style={{ color: "var(--text-muted)", opacity: 0.4 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                </svg>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  No markets found for &ldquo;{query}&rdquo;
                </p>
              </div>
            ) : results.length === 0 && loading ? (
              /* Skeleton loading state */
              <div className="p-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-3 animate-pulse">
                    <div className="h-10 w-10 rounded-lg shrink-0" style={{ background: "var(--surface-2, var(--border))" }} />
                    <div className="flex-1 space-y-2">
                      <div className="h-3 rounded-full w-3/4" style={{ background: "var(--surface-2, var(--border))" }} />
                      <div className="h-2 rounded-full w-1/2" style={{ background: "var(--surface-2, var(--border))" }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <ul className="py-1.5 max-h-[400px] overflow-y-auto">
                {results.map((market, i) => (
                  <li key={market.condition_id}>
                    <button
                      className="w-full flex items-start gap-3 px-3 py-3 text-left transition-colors cursor-pointer"
                      style={{
                        background: i === activeIndex ? "var(--surface-card-hover, var(--surface-1))" : "transparent",
                      }}
                      onMouseEnter={() => setActiveIndex(i)}
                      onMouseLeave={() => setActiveIndex(-1)}
                      onClick={() => navigateTo(market.condition_id)}
                    >
                      {/* Market image */}
                      {market.market_image ? (
                        <img
                          src={market.market_image}
                          alt=""
                          className="h-10 w-10 rounded-lg object-cover shrink-0"
                          style={{ border: "1px solid var(--border-subtle, var(--border))" }}
                        />
                      ) : (
                        <div
                          className="h-10 w-10 rounded-lg shrink-0 flex items-center justify-center"
                          style={{ background: "var(--surface-2, var(--border))" }}
                        >
                          <svg className="h-4 w-4" style={{ color: "var(--text-muted)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M2 12l5-5 4 4 4-6 7 7" />
                          </svg>
                        </div>
                      )}

                      {/* Market info */}
                      <div className="min-w-0 flex-1">
                        <p
                          className="text-[13px] font-medium leading-snug"
                          style={{
                            color: "var(--text-primary)",
                            display: "-webkit-box",
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                          }}
                        >
                          {highlightMatch(market.market_title)}
                        </p>

                        {/* Metadata row */}
                        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                          <span
                            className="inline-flex items-center gap-1 text-[11px] font-medium"
                            style={{ color: "var(--text-muted)" }}
                          >
                            <svg className="h-3 w-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            ${Math.round(market.total_usd).toLocaleString()}
                          </span>
                          <span style={{ color: "var(--border)" }}>·</span>
                          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                            {market.alert_count} alert{market.alert_count !== 1 ? "s" : ""}
                          </span>
                          {market.max_score >= 7 && (
                            <>
                              <span style={{ color: "var(--border)" }}>·</span>
                              <span
                                className="inline-flex items-center text-[11px] font-semibold"
                                style={{ color: "var(--accent)" }}
                              >
                                {market.max_score.toFixed(1)}
                              </span>
                            </>
                          )}
                          {market.tags && market.tags.length > 0 && (
                            <>
                              <span style={{ color: "var(--border)" }}>·</span>
                              <span
                                className="text-[10px] rounded-full px-1.5 py-0.5"
                                style={{
                                  color: "var(--text-muted)",
                                  background: "var(--surface-2, var(--border))",
                                }}
                              >
                                {market.tags[0]}
                              </span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Arrow indicator on hover */}
                      <svg
                        className="h-4 w-4 shrink-0 mt-1 transition-opacity"
                        style={{
                          color: "var(--text-muted)",
                          opacity: i === activeIndex ? 0.6 : 0,
                        }}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {/* Footer hint */}
            {results.length > 0 && (
              <div
                className="flex items-center justify-between px-4 py-2 border-t"
                style={{ borderColor: "var(--border-subtle, var(--border))" }}
              >
                <div className="flex items-center gap-3 text-[10px]" style={{ color: "var(--text-muted)" }}>
                  <span className="flex items-center gap-1">
                    <kbd className="rounded border px-1 py-px text-[9px]" style={{ borderColor: "var(--border)", background: "var(--surface-0, var(--bg-primary))" }}>↑</kbd>
                    <kbd className="rounded border px-1 py-px text-[9px]" style={{ borderColor: "var(--border)", background: "var(--surface-0, var(--bg-primary))" }}>↓</kbd>
                    navigate
                  </span>
                  <span className="flex items-center gap-1">
                    <kbd className="rounded border px-1 py-px text-[9px]" style={{ borderColor: "var(--border)", background: "var(--surface-0, var(--bg-primary))" }}>↵</kbd>
                    open
                  </span>
                  <span className="flex items-center gap-1">
                    <kbd className="rounded border px-1 py-px text-[9px]" style={{ borderColor: "var(--border)", background: "var(--surface-0, var(--bg-primary))" }}>esc</kbd>
                    close
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
