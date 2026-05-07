"use client";

import Link from "next/link";
import CommandPalette from "../../../components/CommandPalette";
import BrandMark from "../../../components/BrandMark";
import ThemeToggle from "../../../components/ThemeToggle";
import HeaderActions from "../../../components/HeaderActions";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function tagSlugify(name) {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

function formatEndDate(d) {
  if (!d) return null;
  const dt = new Date(d);
  return dt.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function EventPageHeader({
  allTags,
  topWallets,
  eventTitle,
  tags,
  totalAlerts,
  totalMarkets,
  totalUsd,
  endDate,
  image,
  summary,
}) {
  const endStr = formatEndDate(endDate);

  return (
    <>
      {/* Top bar — matches /tag and other primary pages */}
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

      {/* Tag pills — link to /tag/[slug] */}
      {tags.length > 0 && (
        <nav className="mb-4" aria-label="Event tags">
          <div
            className="flex items-center gap-1.5 overflow-x-auto no-scrollbar"
            style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
          >
            {tags.map((name) => (
              <Link
                key={name}
                href={`/tag/${tagSlugify(name)}`}
                className="rounded-lg border px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all"
                style={{
                  background: "var(--surface-card)",
                  borderColor: "var(--border)",
                  color: "var(--text-secondary)",
                }}
              >
                {name}
              </Link>
            ))}
          </div>
        </nav>
      )}

      {/* Hero */}
      <header className="mb-6 flex flex-col-reverse gap-4 sm:flex-row sm:items-start sm:gap-6">
        <div className="flex-1 min-w-0">
          <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
            Event
          </div>
          <h1
            className="mt-1 text-2xl font-bold leading-tight sm:text-3xl"
            style={{ color: "var(--text-primary)" }}
          >
            {eventTitle}
          </h1>
          <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
            {totalAlerts} signal{totalAlerts !== 1 ? "s" : ""} across{" "}
            {totalMarkets} market{totalMarkets !== 1 ? "s" : ""}
            {totalUsd > 0 && ` · ${usdFmt.format(totalUsd)} tracked`}
            {endStr && ` · resolves ${endStr}`}
          </p>
          {summary && (
            <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
              {summary}
            </p>
          )}
        </div>
        {image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={image}
            alt=""
            className="h-24 w-24 shrink-0 rounded-xl object-cover sm:h-32 sm:w-32"
            style={{ border: "1px solid var(--border)" }}
          />
        )}
      </header>
    </>
  );
}
