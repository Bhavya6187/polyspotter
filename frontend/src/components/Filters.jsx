import Link from "next/link";

const RESOLVE_OPTIONS = [
  { label: "Any", value: "" },
  { label: "< 1h", value: "1h" },
  { label: "< 24h", value: "24h" },
  { label: "< 7d", value: "7d" },
];

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
  const sorted = [...tags]
    .sort((a, b) => {
      const ca = typeof a === "object" ? a.alert_count || 0 : 0;
      const cb = typeof b === "object" ? b.alert_count || 0 : 0;
      return cb - ca;
    })
    .slice(0, 10);

  return (
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
            onClick={() =>
              onFilterChange({ ...filters, resolvesIn: opt.value })
            }
          />
        ))}
      </div>

      {/* Row 2: Tags */}
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
          const count =
            typeof t === "object" && t.alert_count ? t.alert_count : null;
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
}
