"use client";

import Link from "next/link";
import { useRef, useEffect } from "react";
import CommandPalette from "../../../components/CommandPalette";
import BrandMark from "../../../components/BrandMark";
import ThemeToggle from "../../../components/ThemeToggle";
import HeaderActions from "../../../components/HeaderActions";

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
      {/* Top bar: brand + prominent search + actions in one row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4 mb-5">
        <div className="flex items-center justify-between sm:shrink-0">
          <Link href="/" aria-label="PolySpotter home" className="transition-opacity hover:opacity-80">
            <BrandMark />
          </Link>
          <div className="flex items-center gap-1 sm:hidden">
            <ThemeToggle />
            <HeaderActions variant="compact" />
          </div>
        </div>
        <div className="min-w-0 sm:flex-1 sm:max-w-xl sm:mx-auto">
          <CommandPalette tags={allTags} topWallets={topWallets} />
        </div>
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          <ThemeToggle />
          <span className="h-5 w-px" style={{ background: "var(--border)" }} aria-hidden="true" />
          <HeaderActions />
        </div>
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
