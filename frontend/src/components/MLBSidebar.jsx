"use client";

export default function MLBSidebar({ game }) {
  if (!game) return null;
  const { linescore, scoring_plays, home_box, away_box, head_to_head, home, away } = game;
  return (
    <aside className="space-y-4">
      {linescore && linescore.length > 0 && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Linescore</h3>
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr style={{ color: "var(--text-muted)" }}>
                <th className="text-left pr-2"></th>
                {linescore.map((i) => <th key={i.inning} className="px-1">{i.inning}</th>)}
                <th className="pl-2">R</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ color: "var(--text-primary)" }}>
                <td className="pr-2 font-semibold">{away.abbr}</td>
                {linescore.map((i) => <td key={i.inning} className="px-1 text-center">{i.away_runs}</td>)}
                <td className="pl-2 text-center font-bold">{away.runs}</td>
              </tr>
              <tr style={{ color: "var(--text-primary)" }}>
                <td className="pr-2 font-semibold">{home.abbr}</td>
                {linescore.map((i) => <td key={i.inning} className="px-1 text-center">{i.home_runs}</td>)}
                <td className="pl-2 text-center font-bold">{home.runs}</td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      {scoring_plays && scoring_plays.length > 0 && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Scoring plays</h3>
          <ol className="space-y-2">
            {scoring_plays.slice(0, 12).map((p, i) => (
              <li key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{p.half === "top" ? "▲" : "▼"} {p.inning}</span> · {p.text}
                <span className="ml-2 tabular-nums" style={{ color: "var(--text-muted)" }}>{p.away_score}-{p.home_score}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {head_to_head && head_to_head.total > 0 && (
        <section className="rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Season series</h3>
          <div style={{ color: "var(--text-primary)" }}>
            {away.abbr} {head_to_head.away_wins} — {head_to_head.home_wins} {home.abbr} ({head_to_head.total} games)
          </div>
        </section>
      )}
    </aside>
  );
}
