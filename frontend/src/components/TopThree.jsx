"use client";

import { useTopThree } from "../hooks/useTopThree";
import TopThreeCard from "./TopThreeCard";
import HowWePickPopover from "./HowWePickPopover";

function formatTimeOfDay(date) {
  if (!date) return "—";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Skeleton() {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl p-4"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)", minHeight: 280 }}
    >
      <div className="h-4 w-32 rounded" style={{ background: "var(--surface-2)" }} />
      <div className="h-5 w-3/4 rounded" style={{ background: "var(--surface-2)" }} />
      <div className="h-3 w-full rounded" style={{ background: "var(--surface-2)" }} />
      <div className="h-3 w-5/6 rounded" style={{ background: "var(--surface-2)" }} />
      <div className="mt-auto h-8 w-full rounded" style={{ background: "var(--surface-2)" }} />
    </div>
  );
}

export default function TopThree() {
  const { data, loading, lastUpdated } = useTopThree();

  if (!loading && data.length === 0) return null;

  return (
    <section aria-label="Today's sharpest calls" className="mb-6">
      {/* Section header */}
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
              Today&rsquo;s sharpest calls
            </h2>
            <span
              className="text-[11px] uppercase tracking-wider"
              style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
            >
              refreshed {formatTimeOfDay(lastUpdated)}
            </span>
          </div>
          <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
            The three most convincing setups right now — scored by edge, urgency, and wallet quality.
          </p>
        </div>
        <HowWePickPopover />
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {loading
          ? [0, 1, 2].map((i) => <Skeleton key={i} />)
          : data.map((alert) => <TopThreeCard key={alert.id} alert={alert} />)}
      </div>
    </section>
  );
}
