export default function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-9 w-9 items-center justify-center rounded-lg"
        style={{ background: "var(--accent)", boxShadow: "var(--glow-medium)" }}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          className="h-5 w-5 text-white"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M2 12l5-5 4 4 4-6 7 7" />
          <circle cx="20" cy="12" r="2" fill="currentColor" stroke="none" />
        </svg>
      </div>
      <div>
        <span
          className="text-xl font-bold tracking-tight"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
        >
          PolySpotter
        </span>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Follow the smart money
        </p>
      </div>
    </div>
  );
}
