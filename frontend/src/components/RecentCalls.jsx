import Link from "next/link";

const MIN_RECEIPTS = 3;

function asSignedPct(fraction) {
  const v = Math.round(fraction * 100);
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function Chip({ call }) {
  const color = call.won ? "var(--bullish)" : "var(--bearish)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <span style={{ color }}>{call.won ? "✓" : "✗"}</span>
      <span style={{ color: "var(--text-primary)" }}>{call.outcome}</span>
      <span style={{ color }} className="tabular-nums">
        {asSignedPct(call.return_pct)}
      </span>
    </span>
  );
}

export default function RecentCalls({ recent }) {
  if (!recent || recent.length < MIN_RECEIPTS) return null;

  return (
    <section aria-label="Recent graded calls" className="mb-6">
      <h2
        className="mb-2 text-[11px] font-bold uppercase tracking-wider"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
      >
        Recent calls — the receipts
      </h2>
      <div className="flex flex-wrap gap-2">
        {recent.map((call, i) =>
          call.event_slug ? (
            <Link
              key={`${call.event_slug}-${i}`}
              href={`/event/${encodeURIComponent(call.event_slug)}`}
              className="transition-opacity hover:opacity-80"
            >
              <Chip call={call} />
            </Link>
          ) : (
            <span key={i}>
              <Chip call={call} />
            </span>
          ),
        )}
      </div>
    </section>
  );
}
