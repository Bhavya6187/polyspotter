"use client";
import { useDigest } from "../hooks/useDigest";

export default function DigestBanner() {
  const { digest } = useDigest();
  if (!digest || !digest.new_signals) return null;
  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
      style={{
        background: "linear-gradient(90deg, var(--accent-subtle), rgba(0,194,106,0.03))",
        border: "1px solid rgba(0,194,106,0.2)",
      }}
    >
      <span className="relative inline-block w-2 h-2">
        <span className="absolute inset-0 rounded-full opacity-75 animate-pulse-live" style={{ background: "var(--accent)" }} />
        <span className="absolute inset-0 rounded-full" style={{ background: "var(--accent)" }} />
      </span>
      <span className="text-sm flex-1" style={{ color: "var(--text-primary)" }}>
        <b>{digest.new_signals} new signals</b>
        <span style={{ color: "var(--text-secondary)" }}> since your last visit</span>
      </span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </div>
  );
}
