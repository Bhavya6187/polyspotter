"use client";

import Link from "next/link";
import { useRef, useEffect } from "react";
import CommandPalette from "../../../components/CommandPalette";

function tagSlugify(name) {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

export default function TagPageHeader({
  allTags,
  relatedTags,
  topWallets,
  currentTag,
  display,
  totalAlerts,
  totalMarkets,
  page,
  totalPages,
  tagDesc,
}) {
  const scrollRef = useRef(null);
  const activeRef = useRef(null);

  // The pills to show: current tag first (highlighted), then related tags
  const pills = [currentTag, ...relatedTags];

  // Scroll active tag into view on mount
  useEffect(() => {
    if (activeRef.current && scrollRef.current) {
      const container = scrollRef.current;
      const el = activeRef.current;
      const left = el.offsetLeft - container.offsetWidth / 2 + el.offsetWidth / 2;
      container.scrollTo({ left: Math.max(0, left), behavior: "instant" });
    }
  }, []);

  return (
    <>
      {/* Top bar: back + search */}
      <div className="flex items-center justify-between mb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors hover:opacity-70"
          style={{ color: "var(--text-muted)" }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <CommandPalette tags={allTags} topWallets={topWallets} />
      </div>

      {/* Related topic pills */}
      {pills.length > 1 && (
        <nav className="mb-5" aria-label="Related topics">
          <div
            ref={scrollRef}
            className="flex items-center gap-1.5 overflow-x-auto no-scrollbar"
            style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
          >
            {pills.map((name) => {
              const isActive = name.toLowerCase() === currentTag.toLowerCase();
              return (
                <Link
                  key={name}
                  ref={isActive ? activeRef : undefined}
                  href={`/tag/${tagSlugify(name)}`}
                  className="rounded-lg border px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all"
                  style={{
                    background: isActive ? "var(--accent)" : "var(--surface-card)",
                    borderColor: isActive ? "var(--accent)" : "var(--border)",
                    color: isActive ? "#fff" : "var(--text-secondary)",
                    boxShadow: isActive ? "var(--glow-medium)" : "none",
                  }}
                >
                  {name}
                </Link>
              );
            })}
          </div>
        </nav>
      )}

      {/* Page header */}
      <header className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          {display}
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          {totalAlerts} signal{totalAlerts !== 1 ? "s" : ""} across{" "}
          {totalMarkets} market{totalMarkets !== 1 ? "s" : ""}
          {page > 1 && ` — Page ${page} of ${totalPages}`}
        </p>
        {tagDesc && (
          <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
            {tagDesc}
          </p>
        )}
      </header>
    </>
  );
}
