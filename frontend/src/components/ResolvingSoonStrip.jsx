"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchResolvingSoon } from "../lib/api";
import { useCountdown } from "../hooks/useCountdown";
import { marketSlug } from "../lib/slugify";

function ResolvingCard({ alert }) {
  const countdown = useCountdown(alert.end_date);
  const urgent = countdown.total > 0 && countdown.total < 3600_000;
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const slug = marketSlug(alert.market_title, alert.condition_id);

  return (
    <Link href={`/market/${slug}`} className="shrink-0">
      <div
        className={`rounded-lg px-4 py-3 transition-all ${urgent ? "animate-urgency" : ""}`}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderLeftWidth: 3,
          borderLeftColor: urgent ? "var(--bearish)" : "var(--warning)",
          minWidth: 200,
          maxWidth: 260,
        }}
      >
        <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
          {alert.market_title}
        </p>
        <p
          className="text-lg font-bold mt-0.5"
          style={{ color: urgent ? "var(--bearish)" : "var(--warning)", fontFamily: "var(--font-display)" }}
        >
          {countdown.label}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {usdFmt.format(alert.total_usd)} smart money
          {alert.dominant_side ? ` on ${alert.dominant_side}` : ""}
        </p>
      </div>
    </Link>
  );
}

export default function ResolvingSoonStrip() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    fetchResolvingSoon().then(setAlerts).catch(() => {});
    const interval = setInterval(() => {
      fetchResolvingSoon().then(setAlerts).catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div className="mb-4">
      <p className="text-[11px] uppercase tracking-wider mb-2 px-1"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        Resolving Soon
      </p>
      <div className="flex gap-3 overflow-x-auto pb-2" style={{ scrollbarWidth: "thin" }}>
        {alerts.map((a) => (
          <ResolvingCard key={a.condition_id} alert={a} />
        ))}
      </div>
    </div>
  );
}
