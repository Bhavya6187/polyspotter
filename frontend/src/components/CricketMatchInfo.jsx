"use client";

export default function CricketMatchInfo({ game }) {
  if (!game) return null;

  const { partnership, run_rate, required_rate, head_to_head, home, away } = game;

  const hasAnyData = partnership || run_rate || required_rate || head_to_head;
  if (!hasAnyData) return null;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px" style={{ background: "var(--border)" }}>
        {/* Partnership */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Partnership
          </div>
          {partnership ? (
            <>
              <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
                {partnership.runs}({partnership.balls})
              </div>
              <div className="text-[0.55rem]" style={{ color: "var(--text-muted)" }}>
                {partnership.batsman1} &amp; {partnership.batsman2}
              </div>
            </>
          ) : (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>

        {/* Run Rate */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Run Rate
          </div>
          <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
            {run_rate != null ? run_rate.toFixed(2) : "\u2014"}
          </div>
        </div>

        {/* Required Rate */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Req. Rate
          </div>
          <div
            className="text-sm font-bold tabular-nums"
            style={{
              color: required_rate != null && run_rate != null && required_rate > run_rate
                ? "var(--bearish)"
                : "var(--text-primary)",
            }}
          >
            {required_rate != null ? required_rate.toFixed(2) : "\u2014"}
          </div>
        </div>

        {/* Head to Head */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            H2H
          </div>
          {head_to_head ? (
            <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
              {home.short_name} {head_to_head.home_wins}-{head_to_head.away_wins} {away.short_name}
            </div>
          ) : (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>
      </div>
    </div>
  );
}
