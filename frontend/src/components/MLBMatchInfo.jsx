"use client";

export default function MLBMatchInfo({ game }) {
  if (!game) return null;
  const { venue, weather, attendance, broadcast, probable_home, probable_away, current_pitcher, current_batter, status } = game;
  const items = [];
  if (venue) items.push({ label: "Venue", value: venue.city ? `${venue.name}, ${venue.city}` : venue.name });
  if (broadcast) items.push({ label: "TV", value: broadcast });
  if (attendance) items.push({ label: "Attendance", value: attendance.toLocaleString() });
  if (weather && weather.temperature != null) items.push({ label: "Weather", value: `${weather.temperature}° ${weather.condition || ""} ${weather.wind || ""}`.trim() });

  return (
    <div className="rounded-xl border px-4 py-3" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {items.map((it) => (
          <div key={it.label}>
            <span className="text-[0.65rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{it.label}</span>
            <div style={{ color: "var(--text-primary)" }}>{it.value}</div>
          </div>
        ))}
      </div>
      {status === "pre" && (probable_home || probable_away) && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:gap-6">
          {probable_away && (
            <div>
              <span className="text-[0.65rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Away starter</span>
              <div style={{ color: "var(--text-primary)" }}>
                {probable_away.name} <span style={{ color: "var(--text-muted)" }}>({probable_away.record} · {probable_away.era} ERA)</span>
              </div>
            </div>
          )}
          {probable_home && (
            <div>
              <span className="text-[0.65rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Home starter</span>
              <div style={{ color: "var(--text-primary)" }}>
                {probable_home.name} <span style={{ color: "var(--text-muted)" }}>({probable_home.record} · {probable_home.era} ERA)</span>
              </div>
            </div>
          )}
        </div>
      )}
      {status === "live" && (current_pitcher || current_batter) && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {current_pitcher && <div><span className="text-[0.65rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Pitching</span><div style={{ color: "var(--text-primary)" }}>{current_pitcher}</div></div>}
          {current_batter && <div><span className="text-[0.65rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Batting</span><div style={{ color: "var(--text-primary)" }}>{current_batter}</div></div>}
        </div>
      )}
    </div>
  );
}
