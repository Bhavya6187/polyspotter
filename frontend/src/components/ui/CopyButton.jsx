"use client";
export default function CopyButton({ onClick, returnPct, side = "YES", size = "md", full = false }) {
  const pad = size === "sm" ? "7px 12px" : size === "lg" ? "12px 20px" : "10px 14px";
  const fs = size === "sm" ? 11 : size === "lg" ? 15 : 13;
  return (
    <button
      onClick={onClick}
      style={{
        padding: pad,
        borderRadius: 10,
        background: "var(--accent)",
        color: "#001a0e",
        border: "none",
        fontWeight: 700,
        fontSize: fs,
        letterSpacing: 0.2,
        fontFamily: "var(--font-body)",
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        width: full ? "100%" : "auto",
        boxShadow: "var(--glow-medium)",
        cursor: "pointer",
        transition: "filter 150ms, transform 150ms",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(1.1)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = ""; e.currentTarget.style.transform = ""; }}
    >
      Copy {side} {typeof returnPct === "number" && returnPct > 0 && <span style={{ opacity: 0.7, fontWeight: 500 }}>· +{returnPct}%</span>}
    </button>
  );
}
