"use client";

export default function NHLMatchInfo({ game }) {
  if (!game) return null;
  const { venue, broadcast, attendance } = game;
  const items = [];
  if (venue) items.push({ label: "Arena", value: venue.city ? `${venue.name}, ${venue.city}` : venue.name });
  if (broadcast) items.push({ label: "TV", value: broadcast });
  if (attendance) items.push({ label: "Attendance", value: attendance.toLocaleString() });
  if (!items.length) return null;
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
    </div>
  );
}
