"use client";

export default function CricketPreMatch({ game }) {
  if (!game || game.status !== "pre") return null;

  const { squads, head_to_head, venue, home, away } = game;
  const homeSquad = squads?.home || [];
  const awaySquad = squads?.away || [];

  if (homeSquad.length === 0 && awaySquad.length === 0 && !head_to_head) return null;

  const roleBadgeColor = (role) => {
    const r = role?.toLowerCase() || "";
    if (r.includes("wicketkeeper")) return "rgba(168, 85, 247, 0.15)";
    if (r.includes("allrounder")) return "rgba(59, 130, 246, 0.15)";
    if (r.includes("bowler")) return "rgba(239, 68, 68, 0.1)";
    return "rgba(0, 194, 106, 0.1)";
  };

  const roleText = (role) => {
    const r = role?.toLowerCase() || "";
    if (r.includes("wicketkeeper")) return "WK";
    if (r.includes("allrounder") || r.includes("all-rounder")) return "AR";
    if (r.includes("bowler")) return "BOWL";
    return "BAT";
  };

  function SquadList({ players, teamName }) {
    if (!players || players.length === 0) return null;
    return (
      <div>
        <div
          className="text-[0.6rem] font-semibold uppercase tracking-wider mb-2"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
        >
          {teamName}
        </div>
        <div className="flex flex-col gap-1">
          {players.map((p, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span style={{ color: "var(--text-primary)" }}>{p.name}</span>
              {p.role && (
                <span
                  className="rounded px-1 py-0.5 text-[0.5rem] font-bold uppercase"
                  style={{ background: roleBadgeColor(p.role), color: "var(--text-secondary)" }}
                >
                  {roleText(p.role)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      <div className="px-4 py-2.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <h3
          className="text-[0.6rem] font-semibold uppercase tracking-widest"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
        >
          Match Preview
        </h3>
      </div>

      <div className="p-4">
        {/* Head to Head */}
        {head_to_head && (
          <div className="mb-4 text-center text-xs" style={{ color: "var(--text-secondary)" }}>
            Season record: <b style={{ color: "var(--text-primary)" }}>{home.short_name} {head_to_head.home_wins}-{head_to_head.away_wins} {away.short_name}</b>
            {" "}({head_to_head.total} matches)
          </div>
        )}

        {/* Squads */}
        {(homeSquad.length > 0 || awaySquad.length > 0) && (
          <div className="grid grid-cols-2 gap-4">
            <SquadList players={homeSquad} teamName={home.short_name || home.name} />
            <SquadList players={awaySquad} teamName={away.short_name || away.name} />
          </div>
        )}
      </div>
    </div>
  );
}
