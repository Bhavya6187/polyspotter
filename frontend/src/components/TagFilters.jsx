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

function buildHref(slug, params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) qs.set(k, v);
  }
  const q = qs.toString();
  return q ? `/tag/${slug}?${q}` : `/tag/${slug}`;
}

function Pill({ label, active, href }) {
  return (
    <Link
      href={href}
      className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
      style={{
        background: active ? "var(--accent)" : "var(--surface-card)",
        color: active ? "#fff" : "var(--text-secondary)",
        border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
        boxShadow: active ? "var(--glow-medium)" : "none",
      }}
    >
      {label}
    </Link>
  );
}

function Label({ children }) {
  return (
    <span
      className="text-xs font-semibold uppercase tracking-widest mr-1"
      style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
    >
      {children}
    </span>
  );
}

export default function TagFilters({ slug, resolves = "", severity = "" }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Label>Resolves</Label>
        {RESOLVE_OPTIONS.map((opt) => (
          <Pill
            key={opt.value || "any"}
            label={opt.label}
            active={resolves === opt.value}
            href={buildHref(slug, { resolves: opt.value, severity })}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Label>Severity</Label>
        {SEVERITY_OPTIONS.map((opt) => (
          <Pill
            key={opt.value || "all"}
            label={opt.label}
            active={severity === opt.value}
            href={buildHref(slug, { resolves, severity: opt.value })}
          />
        ))}
      </div>
    </div>
  );
}
