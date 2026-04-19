"use client";
import { useEffect, useState } from "react";

function fmt(ms) {
  if (ms <= 0) return { label: "resolved", urgent: false, soon: false };
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  let label = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { label, urgent: ms < 3600_000, soon: ms < 86400_000 };
}

export default function CountdownText({ endDate, className = "" }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  if (!endDate) return <span className={className}>—</span>;
  const end = new Date(endDate).getTime();
  const c = fmt(end - now);
  return (
    <span
      className={className}
      style={{
        fontFamily: "var(--font-mono)",
        color: c.urgent ? "var(--bearish)" : c.soon ? "var(--warning)" : "var(--text-secondary)",
        fontWeight: 600,
      }}
    >
      {c.label}
    </span>
  );
}
