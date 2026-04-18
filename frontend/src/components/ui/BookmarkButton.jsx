"use client";
export default function BookmarkButton({ active, onClick, size = 40 }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={!!active}
      aria-label={active ? "Remove from watchlist" : "Add to watchlist"}
      style={{
        width: size, height: size, borderRadius: 10,
        background: active ? "var(--accent-subtle)" : "rgba(255,255,255,0.06)",
        border: `1px solid ${active ? "rgba(0,194,106,0.4)" : "var(--border)"}`,
        color: active ? "var(--accent)" : "var(--text-secondary)",
        display: "grid", placeItems: "center",
        transition: "transform 150ms, background 200ms",
        cursor: "pointer",
      }}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.92)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>
      </svg>
    </button>
  );
}
