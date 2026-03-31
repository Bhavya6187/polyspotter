export default function InjuryReport({ injuries, homeTricode, awayTricode }) {
  if (!injuries || injuries.length === 0) return null;

  const statusColors = {
    Out: "var(--bearish)",
    Doubtful: "#f59e0b",
    Questionable: "#eab308",
    Probable: "var(--accent)",
  };

  const byTeam = {};
  for (const inj of injuries) {
    if (!byTeam[inj.team]) byTeam[inj.team] = [];
    byTeam[inj.team].push(inj);
  }

  const teamOrder = [awayTricode, homeTricode].filter((t) => byTeam[t]);
  for (const t of Object.keys(byTeam)) {
    if (!teamOrder.includes(t)) teamOrder.push(t);
  }

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
      >
        Injuries
      </h3>
      <div
        className="overflow-hidden rounded-xl border"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        {teamOrder.map((team) => (
          <div key={team}>
            <div
              className="px-3 py-1.5 text-[0.55rem] uppercase tracking-wider font-semibold"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}
            >
              {team}
            </div>
            {byTeam[team].map((inj) => (
              <div
                key={`${inj.team}-${inj.player}`}
                className="flex items-center justify-between px-3 py-2"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <div>
                  <span className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{inj.player}</span>
                  {inj.detail && (
                    <span className="ml-1.5 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>{inj.detail}</span>
                  )}
                </div>
                <span
                  className="rounded px-1.5 py-0.5 text-[0.55rem] font-bold uppercase shrink-0"
                  style={{
                    background: `color-mix(in srgb, ${statusColors[inj.status] || "var(--text-muted)"} 12%, transparent)`,
                    color: statusColors[inj.status] || "var(--text-muted)",
                  }}
                >
                  {inj.status}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
