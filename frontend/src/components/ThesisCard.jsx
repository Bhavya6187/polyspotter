"use client";

import WalletBadge from "./WalletBadge";
import ShareButton from "./ShareButton";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export default function ThesisCard({ thesis }) {
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div
      className="rounded-xl p-4 mb-3 animate-fade-up"
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
        borderLeftWidth: 4,
        borderLeftColor: "#8b5cf6",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider font-bold" style={{ color: "#8b5cf6" }}>
            Cross-Market Thesis
          </p>
          <h3 className="text-base font-bold mt-0.5" style={{ color: "var(--text-primary)" }}>
            &ldquo;{thesis.thesis_headline || "Multi-market position"}&rdquo;
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {thesis.markets?.length || 0} markets &middot; {usdFmt.format(thesis.total_usd)} total
          </p>
        </div>
        <WalletBadge
          wallet={thesis.wallet}
          winRate={thesis.win_rate}
          totalPnl={thesis.total_pnl}
          totalInvested={thesis.total_invested}
          compact
        />
      </div>

      {/* Market list */}
      <div className="flex flex-col gap-1.5 mb-3">
        {(thesis.markets || []).map((m, i) => (
          <div
            key={m.condition_id || i}
            className="flex items-center justify-between rounded-md px-3 py-2 text-xs"
            style={{ background: "var(--surface-1)" }}
          >
            <span className="truncate mr-2" style={{ color: "var(--text-primary)", maxWidth: "60%" }}>
              {m.market_title}
            </span>
            <span style={{ color: "var(--accent)", fontFamily: "var(--font-display)", whiteSpace: "nowrap" }}>
              {usdFmt.format(m.usd_value)} @ {Math.round(m.entry_price * 100)}\u00a2
            </span>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <ShareButton url={`${SITE_URL}/thesis/${thesis.id}`} />
      </div>
    </div>
  );
}
