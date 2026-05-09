"use client";

export default function MLBSidebar({ payload }) {
  if (!payload) return null;
  const { linescore, scoring_plays, home_box, away_box, head_to_head, home, away } = payload;
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

      {(home_box || away_box) && (
        <section className="rounded-xl border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
          <h3 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Box score</h3>
          {[away_box, home_box].filter(Boolean).map((tb) => (
            <div key={tb.team} className="mb-3 last:mb-0">
              <div className="mb-1 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>{tb.team}</div>
              {tb.batters && tb.batters.length > 0 && (
                <table className="w-full text-[0.65rem] tabular-nums">
                  <thead>
                    <tr style={{ color: "var(--text-muted)" }}>
                      <th className="text-left">Batter</th>
                      <th className="px-1">AB</th>
                      <th className="px-1">R</th>
                      <th className="px-1">H</th>
                      <th className="px-1">RBI</th>
                      <th className="px-1">BB</th>
                      <th className="px-1">K</th>
                      <th className="px-1">AVG</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tb.batters.map((b, i) => (
                      <tr key={i} style={{ color: "var(--text-secondary)" }}>
                        <td className="text-left" style={{ color: "var(--text-primary)" }}>{b.name}{b.position && <span className="ml-1" style={{ color: "var(--text-muted)" }}>{b.position}</span>}</td>
                        <td className="px-1 text-center">{b.at_bats}</td>
                        <td className="px-1 text-center">{b.runs}</td>
                        <td className="px-1 text-center">{b.hits}</td>
                        <td className="px-1 text-center">{b.rbi}</td>
                        <td className="px-1 text-center">{b.walks}</td>
                        <td className="px-1 text-center">{b.strikeouts}</td>
                        <td className="px-1 text-center">{b.avg}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {tb.pitchers && tb.pitchers.length > 0 && (
                <table className="mt-2 w-full text-[0.65rem] tabular-nums">
                  <thead>
                    <tr style={{ color: "var(--text-muted)" }}>
                      <th className="text-left">Pitcher</th>
                      <th className="px-1">IP</th>
                      <th className="px-1">H</th>
                      <th className="px-1">R</th>
                      <th className="px-1">ER</th>
                      <th className="px-1">BB</th>
                      <th className="px-1">K</th>
                      <th className="px-1">ERA</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tb.pitchers.map((p, i) => (
                      <tr key={i} style={{ color: "var(--text-secondary)" }}>
                        <td className="text-left" style={{ color: "var(--text-primary)" }}>{p.name}</td>
                        <td className="px-1 text-center">{p.innings_pitched}</td>
                        <td className="px-1 text-center">{p.hits}</td>
                        <td className="px-1 text-center">{p.runs}</td>
                        <td className="px-1 text-center">{p.earned_runs}</td>
                        <td className="px-1 text-center">{p.walks}</td>
                        <td className="px-1 text-center">{p.strikeouts}</td>
                        <td className="px-1 text-center">{p.era}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
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
