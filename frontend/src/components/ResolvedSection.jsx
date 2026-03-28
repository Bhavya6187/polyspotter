"use client";

import { useState, useEffect } from "react";
import { fetchResolved } from "../lib/api";

export default function ResolvedSection() {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetchResolved(24).then(setData).catch(() => {});
  }, []);

  if (!data || !data.outcomes || data.outcomes.length === 0) return null;

  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div className="mt-6 mb-4">
      {/* Header with aggregate stats */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs mb-3 w-full"
        style={{ color: "var(--text-muted)" }}
      >
        <span className="uppercase tracking-wider" style={{ fontFamily: "var(--font-display)" }}>
          Recently Resolved ({data.outcomes.length})
        </span>
        {data.win_rate_7d != null && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold"
            style={{ background: "rgba(0,194,106,0.12)", color: "var(--accent)" }}>
            {Math.round(data.win_rate_7d * 100)}% win rate this week ({data.wins_7d}/{data.total_7d})
          </span>
        )}
        <span className="ml-auto">{expanded ? "\u25BC" : "\u25B6"}</span>
      </button>

      {expanded && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {data.outcomes.map((o) => (
            <div
              key={o.id}
              className="rounded-lg px-4 py-3"
              style={{
                background: "var(--surface-1)",
                borderLeft: `3px solid ${o.won ? "var(--bullish)" : "var(--bearish)"}`,
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium truncate" style={{ color: "var(--text-primary)", maxWidth: "70%" }}>
                  {o.market_title}
                </span>
                <span className="text-xs font-bold" style={{ color: o.won ? "var(--bullish)" : "var(--bearish)" }}>
                  {o.won ? "\u2705 WIN" : "\u274C LOSS"}
                </span>
              </div>
              <p className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
                {o.entry_price != null && `Entry ${Math.round(o.entry_price * 100)}\u00a2`}
                {o.resolution_price != null && ` \u2192 ${Math.round(o.resolution_price * 100)}\u00a2`}
                {o.pnl_usd != null && ` (${o.pnl_usd >= 0 ? "+" : ""}${usdFmt.format(o.pnl_usd)})`}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
