"use client";
import { useDigest } from "../../hooks/useDigest";

export default function DigestBlock() {
  const { digest } = useDigest();
  if (!digest) return null;
  return (
    <div
      className="rounded-xl p-4 mb-3"
      style={{
        background: "linear-gradient(135deg, rgba(0,194,106,0.08), rgba(0,194,106,0.02))",
        border: "1px solid rgba(0,194,106,0.2)",
      }}
    >
      <div className="text-xs mb-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
        Since your last visit
      </div>
      <div className="text-xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>
        {digest.new_signals} new signals
      </div>
      <div className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
        {digest.strong_signals} rated <b style={{ color: "var(--accent)" }}>Strong+</b>.
      </div>
      <ul className="text-xs space-y-1.5 mb-3">
        {(digest.top_signals || []).slice(0, 3).map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2">
            <span className="truncate" style={{ color: "var(--text-secondary)" }}>• {s.market.title}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent)" }}>
              ▲ {s.market.price_change_24h >= 0 ? "+" : ""}{Math.round((s.market.price_change_24h || 0) * 100)}¢
            </span>
          </li>
        ))}
      </ul>
      <button className="w-full py-2 rounded-lg text-xs font-semibold" style={{ background: "var(--surface-2)", color: "var(--text-primary)" }}>
        View digest →
      </button>
    </div>
  );
}
