"use client";

import Link from "next/link";
import { computeTier, tierBgClass } from "../lib/tiers";
import { walletPseudonym } from "../lib/pseudonym";

export default function WalletBadge({ wallet, winRate, totalPnl, totalInvested, compact = false }) {
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
        {tier.name === "Diamond" ? "\ud83d\udc8e" : tier.name === "Gold" ? "\ud83c\udfc6" : tier.name === "Silver" ? "\ud83e\udd48" : "\ud83e\udd49"}
      </div>

      <div className="flex flex-col min-w-0">
        {/* Name */}
        <span className="text-xs font-bold truncate" style={{ color: "var(--text-primary)" }}>
          {name}
        </span>

        {/* Badges row */}
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-bold ${tierBgClass(tier.name)}`}>
            {tier.name.toUpperCase()}
          </span>
          {winPct && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px]"
              style={{ background: "rgba(0,194,106,0.12)", color: "var(--bullish)" }}>
              {winPct} WR
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
