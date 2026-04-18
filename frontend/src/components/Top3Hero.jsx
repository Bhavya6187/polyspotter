"use client";
import Top3Card from "./Top3Card";

export default function Top3Hero({ signals = [] }) {
  if (!signals.length) return null;
  return (
    <section className="px-4 md:px-6 mt-4">
      <div className="flex items-end justify-between mb-3">
        <div>
          <h2 className="text-lg md:text-2xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Today&apos;s top 3
          </h2>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Curated by your network&apos;s sharpest wallets
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2" style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
          <span
            className="inline-block w-1.5 h-1.5 rounded-full animate-pulse-live"
            style={{ background: "var(--accent)", boxShadow: "0 0 4px var(--accent)" }}
          />
          LIVE
        </div>
      </div>

      <div className="flex md:grid md:grid-cols-3 gap-3 overflow-x-auto md:overflow-visible snap-x snap-mandatory no-scrollbar -mx-4 md:mx-0 px-4 md:px-0 pb-2">
        {signals.slice(0, 3).map((s, i) => (
          <div key={s.id} className="flex-shrink-0 w-[290px] md:w-auto snap-start">
            <Top3Card signal={s} rank={i + 1} />
          </div>
        ))}
      </div>
    </section>
  );
}
