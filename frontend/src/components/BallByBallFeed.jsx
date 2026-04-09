"use client";

import { useState } from "react";

export default function BallByBallFeed({ balls = [] }) {
  const [showAll, setShowAll] = useState(false);

  if (!balls || balls.length === 0) return null;

  const visible = showAll ? balls : balls.slice(0, 30);

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
          Ball by Ball
        </h3>
      </div>

      <div className="max-h-[400px] overflow-y-auto">
        {visible.map((ball, i) => {
          const bgStyle = ball.is_wicket
            ? { background: "rgba(239, 68, 68, 0.08)" }
            : ball.is_boundary
              ? { background: "rgba(0, 194, 106, 0.08)" }
              : {};

          return (
            <div
              key={i}
              className="flex gap-3 px-4 py-2 text-xs"
              style={{ ...bgStyle, borderBottom: "1px solid var(--border)" }}
            >
              {/* Over.ball badge */}
              <div
                className="shrink-0 w-10 text-center rounded px-1 py-0.5 font-mono text-[0.6rem] font-bold"
                style={{
                  background: "var(--surface-2)",
                  color: ball.is_wicket
                    ? "var(--bearish)"
                    : ball.is_boundary
                      ? "var(--accent)"
                      : "var(--text-muted)",
                }}
              >
                {ball.over}.{ball.ball_in_over}
              </div>

              {/* Commentary */}
              <div className="flex-1 min-w-0">
                <div style={{ color: "var(--text-primary)" }}>
                  {ball.commentary_short}
                </div>
                {ball.commentary_detail && ball.commentary_detail !== ball.commentary_short && (
                  <div className="mt-0.5 text-[0.6rem] leading-relaxed" style={{ color: "var(--text-muted)" }}>
                    {ball.commentary_detail}
                  </div>
                )}
              </div>

              {/* Runs badge */}
              <div className="shrink-0">
                {ball.is_wicket ? (
                  <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold" style={{ background: "rgba(239, 68, 68, 0.15)", color: "var(--bearish)" }}>
                    W
                  </span>
                ) : ball.is_boundary ? (
                  <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold" style={{ background: "rgba(0, 194, 106, 0.15)", color: "var(--accent)" }}>
                    {ball.runs}
                  </span>
                ) : ball.runs > 0 ? (
                  <span className="text-[0.6rem] font-bold" style={{ color: "var(--text-secondary)" }}>
                    {ball.runs}
                  </span>
                ) : (
                  <span className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
                    0
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {balls.length > 30 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full py-2 text-xs font-medium cursor-pointer"
          style={{ color: "var(--accent)", background: "var(--surface-1)", border: "none", borderTop: "1px solid var(--border)" }}
        >
          Show all {balls.length} deliveries
        </button>
      )}
    </div>
  );
}
