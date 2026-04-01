export default function PreGameStats({
  home,
  away,
  homePregame,
  awayPregame,
  predictor,
  gameTime,
  venue,
  broadcast,
}) {
  if (!homePregame && !awayPregame && !predictor) return null;

  const homeStats = homePregame?.stats;
  const awayStats = awayPregame?.stats;
  const homeLeaders = homePregame?.leaders || [];
  const awayLeaders = awayPregame?.leaders || [];
  const homeLast5 = homePregame?.last_five || [];
  const awayLast5 = awayPregame?.last_five || [];

  const statRows = [
    { label: "PPG", home: homeStats?.avg_points, away: awayStats?.avg_points },
    { label: "Opp PPG", home: homeStats?.avg_points_against, away: awayStats?.avg_points_against, lowerBetter: true },
    { label: "FG%", home: homeStats?.field_goal_pct, away: awayStats?.field_goal_pct },
    { label: "3PT%", home: homeStats?.three_point_pct, away: awayStats?.three_point_pct },
    { label: "RPG", home: homeStats?.avg_rebounds, away: awayStats?.avg_rebounds },
    { label: "APG", home: homeStats?.avg_assists, away: awayStats?.avg_assists },
    { label: "BPG", home: homeStats?.avg_blocks, away: awayStats?.avg_blocks },
    { label: "SPG", home: homeStats?.avg_steals, away: awayStats?.avg_steals },
  ].filter((r) => r.home != null || r.away != null);

  const gameDate = gameTime ? new Date(gameTime) : null;
  const formattedDate = gameDate
    ? gameDate.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })
    : null;
  const formattedTime = gameDate
    ? gameDate.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
    : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Game info bar */}
      <div
        className="flex items-center justify-between rounded-xl border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
      >
        <div className="flex flex-col items-center gap-1 flex-1">
          <span className="text-lg font-bold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
            {away.tricode}
          </span>
          <span className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
            {away.record || ""}
            {awayPregame?.record_away ? ` (${awayPregame.record_away} away)` : ""}
          </span>
          {awayStats?.streak && (
            <span
              className="rounded px-1.5 py-0.5 text-[0.55rem] font-bold"
              style={{
                background: awayStats.streak.startsWith("W")
                  ? "rgba(0,194,106,0.1)" : "rgba(239,68,68,0.1)",
                color: awayStats.streak.startsWith("W")
                  ? "var(--accent)" : "var(--bearish)",
              }}
            >
              {awayStats.streak}
            </span>
          )}
        </div>

        <div className="flex flex-col items-center gap-0.5 px-4">
          {formattedDate && (
            <span className="text-[0.6rem] uppercase tracking-wider font-semibold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
              {formattedDate}
            </span>
          )}
          {formattedTime && (
            <span className="text-sm font-bold" style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
              {formattedTime}
            </span>
          )}
          {venue && (
            <span className="text-[0.55rem] text-center" style={{ color: "var(--text-muted)" }}>
              {venue}
            </span>
          )}
          {broadcast && (
            <span className="text-[0.55rem] font-medium" style={{ color: "var(--text-secondary)" }}>
              {broadcast}
            </span>
          )}
        </div>

        <div className="flex flex-col items-center gap-1 flex-1">
          <span className="text-lg font-bold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
            {home.tricode}
          </span>
          <span className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
            {home.record || ""}
            {homePregame?.record_home ? ` (${homePregame.record_home} home)` : ""}
          </span>
          {homeStats?.streak && (
            <span
              className="rounded px-1.5 py-0.5 text-[0.55rem] font-bold"
              style={{
                background: homeStats.streak.startsWith("W")
                  ? "rgba(0,194,106,0.1)" : "rgba(239,68,68,0.1)",
                color: homeStats.streak.startsWith("W")
                  ? "var(--accent)" : "var(--bearish)",
              }}
            >
              {homeStats.streak}
            </span>
          )}
        </div>
      </div>

      {/* Predictor */}
      {predictor && (
        <div>
          <h3
            className="mb-3 text-xs font-semibold uppercase tracking-widest"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
          >
            Matchup Predictor
          </h3>
          <div
            className="overflow-hidden rounded-xl border"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            <div className="flex items-center gap-2 px-3 py-3">
              <span className="text-xs font-bold shrink-0 w-10 text-right" style={{
                fontFamily: "var(--font-display)",
                color: predictor.away_pct > predictor.home_pct ? "var(--accent)" : "var(--text-secondary)",
              }}>
                {predictor.away_pct.toFixed(1)}%
              </span>
              <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: "var(--surface-2)" }}>
                <div className="flex h-full">
                  <div
                    className="h-full rounded-l-full"
                    style={{
                      width: `${predictor.away_pct}%`,
                      background: predictor.away_pct > predictor.home_pct
                        ? "var(--accent)" : "var(--text-muted)",
                      opacity: predictor.away_pct > predictor.home_pct ? 1 : 0.5,
                    }}
                  />
                  <div
                    className="h-full rounded-r-full"
                    style={{
                      width: `${predictor.home_pct}%`,
                      background: predictor.home_pct > predictor.away_pct
                        ? "var(--accent)" : "var(--text-muted)",
                      opacity: predictor.home_pct > predictor.away_pct ? 1 : 0.5,
                    }}
                  />
                </div>
              </div>
              <span className="text-xs font-bold shrink-0 w-10" style={{
                fontFamily: "var(--font-display)",
                color: predictor.home_pct > predictor.away_pct ? "var(--accent)" : "var(--text-secondary)",
              }}>
                {predictor.home_pct.toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between px-3 pb-2 text-[0.55rem]" style={{ color: "var(--text-muted)" }}>
              <span>{away.tricode}</span>
              <span>{home.tricode}</span>
            </div>
          </div>
        </div>
      )}

      {/* Team Stats Comparison */}
      {statRows.length > 0 && (
        <div>
          <h3
            className="mb-3 text-xs font-semibold uppercase tracking-widest"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
          >
            Season Averages
          </h3>
          <div
            className="overflow-hidden rounded-xl border"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            {/* Header */}
            <div
              className="flex items-center px-3 py-1.5 text-[0.55rem] uppercase tracking-wider font-semibold"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}
            >
              <span className="w-14 text-right">{away.tricode}</span>
              <span className="flex-1 text-center">Stat</span>
              <span className="w-14">{home.tricode}</span>
            </div>
            {statRows.map((row) => {
              const homeWins = row.lowerBetter
                ? (row.home != null && row.away != null && row.home < row.away)
                : (row.home != null && row.away != null && row.home > row.away);
              const awayWins = row.lowerBetter
                ? (row.home != null && row.away != null && row.away < row.home)
                : (row.home != null && row.away != null && row.away > row.home);
              return (
                <div
                  key={row.label}
                  className="flex items-center px-3 py-2"
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  <span
                    className="w-14 text-right text-xs tabular-nums font-medium"
                    style={{
                      fontFamily: "var(--font-display)",
                      color: awayWins ? "var(--accent)" : "var(--text-primary)",
                    }}
                  >
                    {row.away != null ? row.away : "-"}
                  </span>
                  <span
                    className="flex-1 text-center text-[0.6rem] uppercase tracking-wider"
                    style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
                  >
                    {row.label}
                  </span>
                  <span
                    className="w-14 text-xs tabular-nums font-medium"
                    style={{
                      fontFamily: "var(--font-display)",
                      color: homeWins ? "var(--accent)" : "var(--text-primary)",
                    }}
                  >
                    {row.home != null ? row.home : "-"}
                  </span>
                </div>
              );
            })}
            {/* Last 10 */}
            {(homeStats?.last_ten || awayStats?.last_ten) && (
              <div
                className="flex items-center px-3 py-2"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <span className="w-14 text-right text-xs font-medium" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {awayStats?.last_ten || "-"}
                </span>
                <span className="flex-1 text-center text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
                  Last 10
                </span>
                <span className="w-14 text-xs font-medium" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {homeStats?.last_ten || "-"}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Team Leaders */}
      {(homeLeaders.length > 0 || awayLeaders.length > 0) && (
        <div>
          <h3
            className="mb-3 text-xs font-semibold uppercase tracking-widest"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
          >
            Team Leaders
          </h3>
          <div
            className="overflow-hidden rounded-xl border"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            {/* Pair leaders by category */}
            {["pointsPerGame", "assistsPerGame", "reboundsPerGame"].map((cat) => {
              const awayL = awayLeaders.find((l) => l.category === cat);
              const homeL = homeLeaders.find((l) => l.category === cat);
              if (!awayL && !homeL) return null;
              const displayCat = awayL?.display_category || homeL?.display_category || cat;
              return (
                <div
                  key={cat}
                  className="flex items-center px-3 py-2.5"
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  {/* Away leader */}
                  <div className="flex-1 flex items-center gap-2">
                    {awayL?.headshot && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={awayL.headshot} alt="" className="w-8 h-8 rounded-full object-cover" style={{ background: "var(--surface-2)" }} />
                    )}
                    <div className="min-w-0">
                      <div className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
                        {awayL?.player || "-"}
                      </div>
                      <div className="text-sm font-bold tabular-nums" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                        {awayL?.value || "-"}
                      </div>
                    </div>
                  </div>

                  {/* Category label */}
                  <div className="px-2 text-center">
                    <span className="text-[0.6rem] uppercase tracking-wider font-semibold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
                      {displayCat}
                    </span>
                  </div>

                  {/* Home leader */}
                  <div className="flex-1 flex items-center gap-2 justify-end">
                    <div className="min-w-0 text-right">
                      <div className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
                        {homeL?.player || "-"}
                      </div>
                      <div className="text-sm font-bold tabular-nums" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                        {homeL?.value || "-"}
                      </div>
                    </div>
                    {homeL?.headshot && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={homeL.headshot} alt="" className="w-8 h-8 rounded-full object-cover" style={{ background: "var(--surface-2)" }} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Last 5 Games */}
      {(homeLast5.length > 0 || awayLast5.length > 0) && (
        <div>
          <h3
            className="mb-3 text-xs font-semibold uppercase tracking-widest"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
          >
            Recent Form
          </h3>
          <div className="grid grid-cols-2 gap-3">
            {[
              { tri: away.tricode, games: awayLast5 },
              { tri: home.tricode, games: homeLast5 },
            ].map(({ tri, games }) => (
              <div
                key={tri}
                className="overflow-hidden rounded-xl border"
                style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
              >
                <div
                  className="px-3 py-1.5 text-[0.55rem] uppercase tracking-wider font-semibold"
                  style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", background: "var(--surface-2)", borderBottom: "1px solid var(--border)" }}
                >
                  {tri}
                </div>
                {games.map((g, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between px-3 py-1.5"
                    style={{ borderBottom: i < games.length - 1 ? "1px solid var(--border)" : "none" }}
                  >
                    <span className="text-[0.65rem]" style={{ color: "var(--text-muted)" }}>
                      {g.at_vs} {g.opponent}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[0.65rem] tabular-nums" style={{ color: "var(--text-secondary)" }}>
                        {g.score}
                      </span>
                      <span
                        className="text-[0.55rem] font-bold w-4 text-center"
                        style={{
                          color: g.result === "W" ? "var(--accent)" : "var(--bearish)",
                        }}
                      >
                        {g.result}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
