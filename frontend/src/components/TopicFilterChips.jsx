"use client";
export default function TopicFilterChips({ topics = [], active = "All", onChange }) {
  const all = [{ name: "All", signals: topics.reduce((s, t) => s + (t.signals || 0), 0) }, ...topics];
  return (
    <div className="px-4 md:px-6 mt-4">
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 md:mx-0 md:px-0">
        {all.map((t) => {
          const on = active === t.name;
          return (
            <button
              key={t.name}
              onClick={() => onChange?.(t.name)}
              className="flex-shrink-0 inline-flex items-center gap-1 px-3 py-1.5 rounded-full whitespace-nowrap text-xs font-semibold"
              style={{
                background: on ? "var(--text-primary)" : "rgba(255,255,255,0.05)",
                color:      on ? "var(--surface-0)"    : "var(--text-secondary)",
                border:     `1px solid ${on ? "var(--text-primary)" : "var(--border)"}`,
                letterSpacing: -0.1,
              }}
            >
              {t.icon && <span>{t.icon}</span>}
              {t.name}
              {typeof t.signals === "number" && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600, color: on ? "rgba(5,8,15,0.55)" : "var(--text-muted)" }}>
                  {t.signals}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
