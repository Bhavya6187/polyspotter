"use client";
import { useLiveTicker } from "../../hooks/useLiveTicker";
import { usdK } from "../../lib/signalAdapter";

export default function LiveTicker() {
  const trades = useLiveTicker({ interval: 5000, limit: 20 });
  return (
    <div className="rounded-xl p-4" style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Live ticker
        </div>
        <span className="inline-flex items-center gap-1.5 text-[10px]" style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>
          <span className="w-1.5 h-1.5 rounded-full animate-pulse-live" style={{ background: "var(--accent)", boxShadow: "0 0 4px var(--accent)" }} />
          LIVE
        </span>
      </div>
      <ul aria-live="polite" className="space-y-2 max-h-[360px] overflow-y-auto no-scrollbar">
        {trades.map((t) => (
          <li key={t.id} className="flex items-center gap-2 text-xs animate-fade-up">
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-bold"
              style={{
                background: t.side === "BUY" ? "rgba(0,194,106,0.12)" : "rgba(239,68,68,0.12)",
                color: t.side === "BUY" ? "var(--accent)" : "var(--bearish)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {t.side}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--text-primary)" }}>
              {usdK(t.amount)}
            </span>
            <span className="flex-1 truncate" style={{ color: "var(--text-secondary)" }}>{t.market}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: t.wallet_color }}>
              {t.wallet_alias}
            </span>
          </li>
        ))}
        {trades.length === 0 && (
          <li className="text-center text-[11px] py-4" style={{ color: "var(--text-muted)" }}>Waiting for trades…</li>
        )}
      </ul>
    </div>
  );
}
