"use client";

export default function NHLSidebar({ payload }) {
  if (!payload) return null;
  const { scoring_summary, penalties, team_stats_live, goalies, head_to_head, home, away } = payload;

  return (
    <aside className="space-y-4">
      {scoring_summary && scoring_summary.length > 0 && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Goals</h3>
          <ol className="space-y-2">
            {scoring_summary.map((g, i) => (
              <li key={i} className="text-xs flex justify-between gap-2" style={{ color: "var(--text-secondary)" }}>
                <span>
                  <span className="font-semibold" style={{ color: "var(--text-primary)" }}>P{g.period} {g.time}</span>
                  {" · "}
                  <span style={{ color: "var(--text-primary)" }}>{g.team}</span>
                  {" "}{g.scorer}
                  {g.assists.length > 0 && <span style={{ color: "var(--text-muted)" }}> ({g.assists.join(", ")})</span>}
                </span>
                {g.is_gwg && <span className="rounded bg-[var(--accent)] px-1 text-[0.55rem] font-bold uppercase text-white">GWG</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      {penalties && penalties.length > 0 && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Penalties</h3>
          <ol className="space-y-2 text-xs">
            {penalties.slice(0, 12).map((p, i) => (
              <li key={i} style={{ color: "var(--text-secondary)" }}>
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>P{p.period} {p.time}</span>
                {" · "}{p.team} {p.player} — {p.infraction} ({p.minutes} min)
              </li>
            ))}
          </ol>
        </section>
      )}

      {team_stats_live && team_stats_live.length === 2 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Team stats</h3>
          <table className="w-full">
            <tbody>
              {[
                ["Shots", "shots"],
                ["Hits", "hits"],
                ["FO%", "faceoff_pct"],
                ["PP", "pp_summary"],
                ["PK", "pk_summary"],
              ].map(([label, key]) => (
                <tr key={key}>
                  <td className="text-right pr-2 tabular-nums" style={{ color: "var(--text-primary)" }}>{team_stats_live[0][key] ?? "—"}</td>
                  <td className="text-center text-[0.65rem]" style={{ color: "var(--text-muted)" }}>{label}</td>
                  <td className="text-left pl-2 tabular-nums" style={{ color: "var(--text-primary)" }}>{team_stats_live[1][key] ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {goalies && goalies.length > 0 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Goalies</h3>
          {goalies.map((g, i) => (
            <div key={i} className="flex justify-between" style={{ color: "var(--text-secondary)" }}>
              <span><span className="font-semibold" style={{ color: "var(--text-primary)" }}>{g.team}</span> {g.name}</span>
              <span className="tabular-nums">{g.saves}/{g.shots_against}</span>
            </div>
          ))}
        </section>
      )}

      {head_to_head && head_to_head.total > 0 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Season series</h3>
          <div style={{ color: "var(--text-primary)" }}>{away.abbr} {head_to_head.away_wins} — {head_to_head.home_wins} {home.abbr} ({head_to_head.total} games)</div>
        </section>
      )}
    </aside>
  );
}
