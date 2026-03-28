const fmtUsd = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

export default function MarketPulse({ alerts, volume24h }) {
  const flow = {};
  for (const a of alerts || []) {
    const side = a.llm_copy_action?.outcome || "Unknown";
    flow[side] = (flow[side] || 0) + (a.total_usd || 0);
  }
  const entries = Object.entries(flow).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);

  if (total === 0 && !volume24h) return null;

  const volumeSpike = volume24h && volume24h > 50000 ? (volume24h / 15000).toFixed(1) : null;

  return (
    <div
      className="mt-3.5 rounded-xl border p-3.5"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <h3
        className="mb-2.5 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Market Pulse
      </h3>
      {total > 0 && (
        <div className="mb-2.5">
          <div
            className="mb-1 flex justify-between text-[11px]"
            style={{ color: "var(--text-muted)" }}
          >
            {entries.map(([name]) => (
              <span key={name}>{name} flow</span>
            ))}
          </div>
          <div className="flex h-2 overflow-hidden rounded-full">
            {entries.map(([name, val], i) => {
              const pct = (val / total) * 100;
              const colors = ["var(--accent)", "var(--bearish)", "var(--warning)", "var(--info)"];
              return (
                <div
                  key={name}
                  style={{ width: `${pct}%`, background: colors[i] || colors[0] }}
                />
              );
            })}
          </div>
          <div
            className="mt-1 flex justify-between text-[11px]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {entries.map(([name, val], i) => {
              const colors = ["var(--accent)", "var(--bearish)", "var(--warning)", "var(--info)"];
              return (
                <span key={name} style={{ color: colors[i] || colors[0] }}>
                  {fmtUsd(val)}
                </span>
              );
            })}
          </div>
        </div>
      )}
      {volumeSpike && (
        <div
          className="flex items-center gap-1.5 text-[11px]"
          style={{ color: "var(--text-muted)" }}
        >
          <span style={{ color: "var(--warning)" }}>&#x26A1;</span>
          <span>
            Volume{" "}
            <span style={{ color: "var(--warning)", fontWeight: 600 }}>
              {volumeSpike}x above
            </span>{" "}
            average
          </span>
        </div>
      )}
    </div>
  );
}
