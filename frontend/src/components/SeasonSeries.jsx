export default function SeasonSeries({ series, homeTricode, awayTricode }) {
  if (!series || series.total_games === 0) return null;

  const leader =
    series.away_wins > series.home_wins
      ? awayTricode
      : series.home_wins > series.away_wins
        ? homeTricode
        : null;

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
      >
        Season Series
      </h3>
      <div
        className="rounded-xl border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        <div className="flex items-center justify-between">
          <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {leader
              ? <><span className="font-bold" style={{ color: "var(--text-primary)" }}>{leader}</span> leads {Math.max(series.away_wins, series.home_wins)}-{Math.min(series.away_wins, series.home_wins)}</>
              : <>Tied {series.home_wins}-{series.away_wins}</>
            }
          </div>
          <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
            {series.total_games} game{series.total_games !== 1 ? "s" : ""} played
          </div>
        </div>
      </div>
    </div>
  );
}
