const TONES = {
  default: { bg: "var(--surface-2)",                   fg: "var(--text-secondary)", bd: "transparent" },
  accent:  { bg: "var(--accent-subtle)",               fg: "var(--accent)",         bd: "rgba(0,194,106,0.3)" },
  danger:  { bg: "rgba(239,68,68,0.1)",                fg: "var(--bearish)",        bd: "rgba(239,68,68,0.3)" },
  warn:    { bg: "rgba(245,158,11,0.1)",               fg: "var(--warning)",        bd: "rgba(245,158,11,0.3)" },
  info:    { bg: "rgba(59,130,246,0.1)",               fg: "var(--info)",           bd: "rgba(59,130,246,0.3)" },
  violet:  { bg: "rgba(139,92,246,0.1)",               fg: "var(--violet)",         bd: "rgba(139,92,246,0.3)" },
};

export default function Chip({ tone = "default", children, className = "", ...rest }) {
  const t = TONES[tone] || TONES.default;
  return (
    <span
      {...rest}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide ${className}`}
      style={{ background: t.bg, color: t.fg, border: `1px solid ${t.bd}`, fontFamily: "var(--font-mono)" }}
    >
      {children}
    </span>
  );
}
