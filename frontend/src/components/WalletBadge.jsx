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

  const winPctNum = winRate != null ? Math.round(winRate * 100) : null;
  const winPct = winPctNum != null ? `${winPctNum}%` : null;
  const isElite = winPctNum != null && winPctNum >= 90;

  return (
    <Link href={`/wallet/${wallet}`} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
      {/* Avatar — win rate shown as text next to circle */}
      <div className="relative shrink-0">
        <div
          className="flex items-center justify-center rounded-full font-bold shrink-0"
          style={{
            width: compact ? 24 : 32,
            height: compact ? 24 : 32,
            background: `${tier.color}22`,
            border: `2px solid ${tier.color}`,
            color: tier.color,
            fontSize: compact ? 9 : 11,
          }}
        >
          {tier.prefix?.charAt(0) || "W"}
        </div>
        {isElite && (
          <div
            className="absolute -top-0.5 -right-0.5 rounded-full animate-pulse"
            style={{
              width: 10,
              height: 10,
              background: "var(--bullish)",
              border: "2px solid var(--surface-card)",
            }}
          />
        )}
      </div>

      <div className="flex flex-col min-w-0">
        {/* Name */}
        <span className="text-xs font-bold truncate" style={{ color: "var(--text-primary)" }}>
          {name}
        </span>

        {/* Win rate */}
        {winPct && (
          <span
            className="font-bold mt-0.5"
            style={{
              color: isElite ? "var(--bullish)" : "var(--text-secondary)",
              fontSize: isElite ? 13 : 11,
            }}
          >
            {winPct} win rate
            {isElite && " 🔥"}
          </span>
        )}
      </div>
    </Link>
  );
}
