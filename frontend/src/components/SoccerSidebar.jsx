"use client";

const cardClass = (color) => {
  if (color === "red") return "bg-red-500";
  if (color === "second yellow") return "bg-orange-500";
  return "bg-yellow-400";
};

export default function SoccerSidebar({ payload }) {
  if (!payload) return null;
  const { goals, cards, subs, match_stats, lineups, head_to_head, home, away } = payload;

  const events = [
    ...(goals || []).map((g) => ({ minute: g.minute, type: "goal", team: g.team, label: `⚽ ${g.scorer}${g.assist ? ` (${g.assist})` : ""}${g.type && g.type !== "regular" ? ` (${g.type})` : ""}` })),
    ...(cards || []).map((c) => ({ minute: c.minute, type: "card", team: c.team, label: `${c.color === "red" ? "🟥" : "🟨"} ${c.player}` })),
    ...(subs || []).map((s) => ({ minute: s.minute, type: "sub", team: s.team, label: `↔ ${s.on} for ${s.off}` })),
  ];

  return (
    <aside className="space-y-4">
      {events.length > 0 && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Match events</h3>
          <ol className="space-y-2 text-xs">
            {events.slice(0, 30).map((e, i) => (
              <li key={i} className="flex gap-2" style={{ color: "var(--text-secondary)" }}>
                <span className="w-12 tabular-nums font-semibold" style={{ color: "var(--text-primary)" }}>{e.minute}</span>
                <span className="w-10 font-semibold" style={{ color: "var(--text-primary)" }}>{e.team}</span>
                <span>{e.label}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {match_stats && match_stats.length === 2 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Match stats</h3>
          <table className="w-full">
            <tbody>
              {[
                ["Possession", "possession_pct", "%"],
                ["Shots", "shots", ""],
                ["On target", "shots_on_target", ""],
                ["Corners", "corners", ""],
                ["Fouls", "fouls", ""],
                ["Offsides", "offsides", ""],
              ].map(([label, key, suffix]) => (
                <tr key={key}>
                  <td className="text-right pr-2 tabular-nums" style={{ color: "var(--text-primary)" }}>{match_stats[0][key] ?? "—"}{suffix}</td>
                  <td className="text-center text-[0.65rem]" style={{ color: "var(--text-muted)" }}>{label}</td>
                  <td className="text-left pl-2 tabular-nums" style={{ color: "var(--text-primary)" }}>{match_stats[1][key] ?? "—"}{suffix}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {lineups && lineups.length > 0 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Starting XI</h3>
          {lineups.map((lu) => (
            <div key={lu.team} className="mb-2">
              <div className="font-semibold" style={{ color: "var(--text-primary)" }}>{lu.team} {lu.formation && `(${lu.formation})`}</div>
              <ul className="ml-2">
                {lu.starters.map((p, i) => (
                  <li key={i} style={{ color: "var(--text-secondary)" }}>
                    {p.number != null && <span className="tabular-nums mr-1" style={{ color: "var(--text-muted)" }}>{p.number}</span>}
                    {p.name}
                    {p.position && <span className="ml-1" style={{ color: "var(--text-muted)" }}>({p.position})</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}

      {head_to_head && head_to_head.total > 0 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Head-to-head</h3>
          <div style={{ color: "var(--text-primary)" }}>
            {away.abbr || away.name} {head_to_head.away_wins} — {head_to_head.draws} draws — {head_to_head.home_wins} {home.abbr || home.name} ({head_to_head.total} games)
          </div>
        </section>
      )}
    </aside>
  );
}
