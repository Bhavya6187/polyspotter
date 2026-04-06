"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

const RESOLVE_OPTIONS = [
  { label: "Any", value: "" },
  { label: "< 6h", value: "6h" },
  { label: "< 24h", value: "24h" },
  { label: "< 7d", value: "7d" },
];

const SEVERITY_OPTIONS = [
  { label: "All", value: "" },
  { label: "Medium+", value: "6" },
  { label: "Strong+", value: "10" },
  { label: "Very Strong", value: "15" },
];

const SEVERITY_LABELS = { "6": "Medium+", "10": "Strong+", "15": "Very Strong" };
const RESOLVE_LABELS = { "6h": "< 6h", "24h": "< 24h", "7d": "< 7d" };

function Pill({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
      style={{
        background: active ? 'var(--accent)' : 'var(--surface-card)',
        color: active ? '#fff' : 'var(--text-secondary)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        boxShadow: active ? 'var(--glow-medium)' : 'none',
      }}
    >
      {label}
    </button>
  );
}

function TagPill({ label, active, href }) {
  return (
    <Link
      href={href}
      className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
      style={{
        background: active ? 'var(--accent)' : 'var(--surface-card)',
        color: active ? '#fff' : 'var(--text-secondary)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        boxShadow: active ? 'var(--glow-medium)' : 'none',
      }}
    >
      {label}
    </Link>
  );
}

export default function Filters({ tags, filters, onFilterChange }) {
  const [collapsed, setCollapsed] = useState(true);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 640px)");
    setIsDesktop(mq.matches);
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const sorted = [...tags]
    .sort((a, b) => {
      const ca = typeof a === "object" ? a.alert_count || 0 : 0;
      const cb = typeof b === "object" ? b.alert_count || 0 : 0;
      return cb - ca;
    })
    .slice(0, 10);

  // Count active filters
  const activeCount = [filters.tag, filters.resolvesIn, filters.minScore].filter(Boolean).length;

  // Build summary pills for collapsed state
  const summaryParts = [];
  if (filters.resolvesIn && RESOLVE_LABELS[filters.resolvesIn]) {
    summaryParts.push(RESOLVE_LABELS[filters.resolvesIn]);
  }
  if (filters.minScore && SEVERITY_LABELS[filters.minScore]) {
    summaryParts.push(SEVERITY_LABELS[filters.minScore]);
  }
  if (filters.tag) {
    summaryParts.push(filters.tag);
  }

  const showExpanded = isDesktop || !collapsed;

  const filterRows = (
    <div className="flex flex-col gap-3">
      {/* Row 1: Resolution window */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Resolves
        </span>
        {RESOLVE_OPTIONS.map((opt) => (
          <Pill
            key={opt.value}
            label={opt.label}
            active={filters.resolvesIn === opt.value}
            onClick={() => onFilterChange({ ...filters, resolvesIn: opt.value })}
          />
        ))}
      </div>

      {/* Row 2: Severity */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Severity
        </span>
        {SEVERITY_OPTIONS.map((opt) => (
          <Pill
            key={opt.value}
            label={opt.label}
            active={(filters.minScore || "") === opt.value}
            onClick={() => onFilterChange({ ...filters, minScore: opt.value })}
          />
        ))}
      </div>

      {/* Row 3: Tags */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Topic
        </span>
        <Pill
          label="All"
          active={!filters.tag}
          onClick={() => onFilterChange({ ...filters, tag: "" })}
        />
        {sorted.map((t) => {
          const name = typeof t === "string" ? t : t.tag;
          const count = typeof t === "object" && t.alert_count ? t.alert_count : null;
          const slug = encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
          return (
            <TagPill
              key={name}
              label={count ? `${name} (${count})` : name}
              active={filters.tag === name}
              href={`/tag/${slug}`}
            />
          );
        })}
      </div>
    </div>
  );

  // Desktop: always show filter rows
  if (isDesktop) {
    return filterRows;
  }

  // Mobile: collapsible
  return (
    <div>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all"
        style={{
          background: activeCount > 0 ? 'var(--accent)' : 'var(--surface-card)',
          color: activeCount > 0 ? '#fff' : 'var(--text-secondary)',
          border: `1px solid ${activeCount > 0 ? 'var(--accent)' : 'var(--border)'}`,
        }}
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
        </svg>
        Filters{activeCount > 0 ? ` (${activeCount})` : ""}
        <svg
          className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-180"}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Active filter summary when collapsed */}
      {collapsed && summaryParts.length > 0 && (
        <button
          onClick={() => setCollapsed(false)}
          className="mt-1.5 flex flex-wrap gap-1.5"
        >
          {summaryParts.map((part) => (
            <span
              key={part}
              className="rounded-full px-2 py-0.5 text-xs font-medium"
              style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
            >
              {part}
            </span>
          ))}
        </button>
      )}

      {/* Expanded filter panel */}
      {showExpanded && (
        <div className="mt-3">
          {filterRows}
        </div>
      )}
    </div>
  );
}
