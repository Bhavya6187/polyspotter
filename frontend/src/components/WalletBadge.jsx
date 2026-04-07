"use client";

import Link from "next/link";
import { computeTier } from "../lib/tiers";
import { walletPseudonym } from "../lib/pseudonym";

export default function WalletBadge({ wallet, winRate, totalInvested, compact = false }) {
  const tier = computeTier(winRate, totalInvested);
  const name = walletPseudonym(wallet, tier);

  if (!tier) {
    return (
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        {wallet ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}` : "Unknown"}
      </span>
    );
  }

  const winPct = winRate != null ? `${Math.round(winRate * 100)}%` : null;

  return (
    <Link href={`/wallet/${wallet}`} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full text-xs font-bold shrink-0"
        style={{
          width: compact ? 24 : 32,
          height: compact ? 24 : 32,
          background: `${tier.color}22`,
          border: `2px solid ${tier.color}`,
          color: tier.color,
        }}
      >
        {winPct ? winPct : "—"}
      </div>

      <div className="flex flex-col min-w-0">
        {/* Name */}
        <span className="text-xs font-bold truncate" style={{ color: "var(--text-primary)" }}>
          {name}
        </span>

        {/* Win rate */}
        {winPct && (
          <span className="text-[11px] font-bold mt-0.5" style={{ color: "var(--bullish)" }}>
            {winPct} win rate
          </span>
        )}
      </div>
    </Link>
  );
}
