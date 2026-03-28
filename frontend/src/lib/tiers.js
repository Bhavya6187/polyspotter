/**
 * Wallet tier computation from win_rate + total_invested.
 * Both thresholds must be met.
 */

const TIERS = [
  { name: "Diamond", minWinRate: 0.85, minInvested: 100_000, color: "#8b5cf6", prefix: "Whale" },
  { name: "Gold",    minWinRate: 0.75, minInvested: 50_000,  color: "#f59e0b", prefix: "Sharp" },
  { name: "Silver",  minWinRate: 0.65, minInvested: 10_000,  color: "#94a3b8", prefix: "Trader" },
  { name: "Bronze",  minWinRate: 0.50, minInvested: 0,       color: "#b45309", prefix: "Wallet" },
];

export function computeTier(winRate, totalInvested) {
  if (winRate == null || winRate < 0.5) return null;
  const invested = totalInvested || 0;
  for (const tier of TIERS) {
    if (winRate >= tier.minWinRate && invested >= tier.minInvested) {
      return tier;
    }
  }
  return null;
}

export function tierBgClass(tierName) {
  switch (tierName) {
    case "Diamond": return "bg-purple-500/15 text-purple-400";
    case "Gold":    return "bg-amber-500/15 text-amber-400";
    case "Silver":  return "bg-slate-400/15 text-slate-400";
    case "Bronze":  return "bg-amber-700/15 text-amber-700";
    default:        return "bg-gray-500/15 text-gray-400";
  }
}
