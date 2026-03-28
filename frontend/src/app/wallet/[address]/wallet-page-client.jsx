"use client";

import WalletBadge from "../../../components/WalletBadge";
import Link from "next/link";

export default function WalletPageClient({ wallet, address }) {
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  const stats = [
    { label: "P&L", value: wallet.total_pnl != null ? usdFmt.format(wallet.total_pnl) : "—", color: wallet.total_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" },
    { label: "Win Rate", value: wallet.win_rate != null ? `${Math.round(wallet.win_rate * 100)}%` : "—" },
    { label: "Streak", value: wallet.current_streak ? `${wallet.current_streak}W` : "—", color: "var(--warning)" },
    { label: "Markets", value: wallet.total_positions || 0 },
    { label: "W/L", value: `${wallet.wins || 0}/${wallet.losses || 0}` },
    { label: "Flagged", value: `${wallet.times_flagged || 0}x` },
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <WalletBadge wallet={address} winRate={wallet.win_rate} totalPnl={wallet.total_pnl} totalInvested={wallet.total_invested} />
        <p className="text-xs mt-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
          {address}
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-8">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg p-3 text-center" style={{ background: "var(--surface-1)" }}>
            <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{s.label}</p>
            <p className="text-sm font-bold mt-0.5" style={{ color: s.color || "var(--text-primary)", fontFamily: "var(--font-display)" }}>
              {s.value}
            </p>
          </div>
        ))}
      </div>

      {/* Recent alerts */}
      {wallet.recent_alerts?.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Recent Alerts
          </h3>
          <div className="flex flex-col gap-2">
            {wallet.recent_alerts.map((a) => (
              <Link key={a.id} href={`/market/${a.condition_id?.slice(0, 7) || a.id}`}
                className="flex items-center justify-between rounded-lg px-4 py-3"
                style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{a.market_title}</p>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>{a.llm_headline}</p>
                </div>
                <span className="text-xs font-bold" style={{ color: "var(--accent)", fontFamily: "var(--font-display)" }}>
                  {usdFmt.format(a.total_usd)}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
