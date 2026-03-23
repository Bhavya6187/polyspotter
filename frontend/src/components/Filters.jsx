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
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-blue-600 text-white dark:bg-blue-500"
          : "bg-white text-gray-600 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
      }`}
    >
      {label}
    </button>
  );
}

function TagPill({ label, active, href }) {
  return (
    <Link
      href={href}
      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-blue-600 text-white dark:bg-blue-500"
          : "bg-white text-gray-600 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
      }`}
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
    <div className="flex flex-col gap-2">
      {/* Row 1: Resolves in */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-gray-400 dark:text-gray-500 mr-1">
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
        <span className="text-xs font-medium uppercase tracking-wider text-gray-400 dark:text-gray-500 mr-1">
          Tag
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
