"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { usdK } from "../../lib/signalAdapter";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function SharpestWallets() {
  const [wallets, setWallets] = useState([]);
  useEffect(() => {
    fetch(`${API}/api/wallets/top?limit=5`).then((r) => r.json()).then((d) => setWallets(d.wallets || d || [])).catch(() => {});
  }, []);
  if (!wallets.length) return null;
  return (
    <div className="rounded-xl p-4 mb-3" style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Sharpest this week
        </div>
        <Link href="/wallets" className="text-xs" style={{ color: "var(--text-muted)" }}>All →</Link>
      </div>
      <ul>
        {wallets.slice(0, 5).map((w, i) => (
          <li key={w.wallet} className="flex items-center gap-2 py-1.5">
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>#{i+1}</span>
            <div style={{ width: 24, height: 24, borderRadius: "50%", background: "linear-gradient(135deg, #8b5cf6, #3b82f6)", color: "#fff", fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 10, display: "grid", placeItems: "center" }}>
              {(w.alias || w.wallet).slice(0, 1).toUpperCase()}
            </div>
            <Link href={`/wallet/${w.wallet}`} className="text-sm font-semibold flex-1" style={{ color: "var(--text-primary)" }}>
              {w.alias || w.wallet.slice(0, 6)}
            </Link>
            <div className="text-right">
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: "var(--accent)" }}>
                {w.win_rate != null ? `${Math.round(w.win_rate * 100)}%` : "—"}
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {w.total_pnl != null ? `+${usdK(w.total_pnl)}` : ""}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
