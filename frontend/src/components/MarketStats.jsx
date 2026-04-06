const fmtUsd = (v) => {
  if (v == null) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

export default function MarketStats({ volume24h, liquidity, spread, alerts }) {
  const flow = {};
  for (const a of alerts || []) {
    const side = a.llm_copy_action?.outcome || "Unknown";
    flow[side] = (flow[side] || 0) + (a.total_usd || 0);
  }
  const flowEntries = Object.entries(flow).sort((a, b) => b[1] - a[1]);
  const totalFlow = flowEntries.reduce((s, [, v]) => s + v, 0);
  const topFlow = flowEntries[0];
  const flowPct = topFlow && totalFlow > 0 ? Math.round((topFlow[1] / totalFlow) * 100) : null;

  const tiles = [
    volume24h != null && { label: "24h Volume", value: fmtUsd(volume24h) },
    liquidity != null && { label: "Liquidity", value: fmtUsd(liquidity) },
    spread != null && { label: "Spread", value: `${spread.toFixed(1)}¢` },
    flowPct != null && {
      label: "Smart Flow",
      value: `${flowPct}% ${topFlow[0]}`,
      accent: true,
    },
  ].filter(Boolean);

  if (tiles.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded-xl border p-3 text-center"
          style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
        >
          <div
            className="mb-1 text-xs uppercase tracking-wider"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-muted)",
              fontSize: "0.55rem",
              letterSpacing: "0.08em",
            }}
          >
            {t.label}
          </div>
          <div
            className="text-base font-bold tabular-nums"
            style={{
              fontFamily: "var(--font-display)",
              color: t.accent ? "var(--accent)" : "var(--text-primary)",
            }}
          >
            {t.value}
          </div>
        </div>
      ))}
    </div>
  );
}
