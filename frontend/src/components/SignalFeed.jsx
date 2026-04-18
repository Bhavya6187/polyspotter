"use client";
import { useState } from "react";
import SignalCard from "./SignalCard";
import { useSignalFeed } from "../hooks/useSignalFeed";

const RATING_TABS = [
  { key: "all",            label: "All",           minRating: 1 },
  { key: "strong",         label: "Strong+",       minRating: 4 },
  { key: "resolving-soon", label: "Resolving soon",minRating: 1, resolvesWithin: "24h" },
];

export default function SignalFeed({ topic = "All", showTabs = true }) {
  const [tab, setTab] = useState(RATING_TABS[0]);
  const { signals, total, loading, loadMore } = useSignalFeed({
    topic,
    minRating: tab.minRating,
    resolvesWithin: tab.resolvesWithin,
  });

  return (
    <section className="px-4 md:px-6 mt-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base md:text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          All signals
        </h3>
        {showTabs && (
          <div className="flex items-center gap-1 p-0.5 rounded-lg" style={{ background: "var(--surface-2)" }}>
            {RATING_TABS.map((t) => {
              const on = tab.key === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t)}
                  className="px-3 py-1.5 rounded-md text-xs font-semibold"
                  style={{
                    background: on ? "var(--surface-card)" : "transparent",
                    color: on ? "var(--text-primary)" : "var(--text-secondary)",
                  }}
                >
                  {t.label}{on && ` (${total})`}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {signals.map((s) => <SignalCard key={s.id} signal={s} />)}

      {!loading && signals.length === 0 && (
        <div className="text-center py-10" style={{ color: "var(--text-muted)" }}>
          No signals{topic !== "All" ? ` in ${topic}` : ""} yet.
        </div>
      )}

      {signals.length < total && (
        <button onClick={loadMore} disabled={loading} className="block mx-auto mt-4 px-4 py-2 rounded-lg text-sm" style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
