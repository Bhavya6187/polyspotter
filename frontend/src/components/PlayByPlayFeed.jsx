"use client";

import { useState } from "react";

const PLAY_ICONS = {
  "2pt": "\u{1F3C0}",
  "3pt": "\u{1F525}",
  freethrow: "\u{1F3AF}",
  foul: "\u{26A0}\uFE0F",
  timeout: "\u{23F8}\uFE0F",
  turnover: "\u{1F504}",
  rebound: "\u{1F4AA}",
  substitution: "\u{1F501}",
  jumpball: "\u{2B06}\uFE0F",
};

function playIcon(type) {
  return PLAY_ICONS[type] || "\u{25CF}";
}

export default function PlayByPlayFeed({ plays, homeTricode, awayTricode }) {
  const [expanded, setExpanded] = useState(false);

  if (!plays || plays.length === 0) return null;

  const visible = expanded ? plays : plays.slice(0, 20);

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
      >
        Play-by-Play
      </h3>
      <div
        className="overflow-hidden rounded-xl border"
        style={{
          borderColor: "var(--border)",
          background: "var(--surface-1)",
          maxHeight: expanded ? "none" : "400px",
          overflowY: "auto",
        }}
      >
        {visible.map((play) => (
          <div
            key={play.id}
            className="flex items-start gap-2 px-3 py-2"
            style={{
              borderBottom: "1px solid var(--border)",
              background: play.scoring ? "rgba(0, 194, 106, 0.04)" : "transparent",
            }}
          >
            <span className="mt-0.5 text-sm shrink-0" style={{ width: "20px", textAlign: "center" }}>
              {playIcon(play.type)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span
                  className="text-xs truncate"
                  style={{
                    color: play.scoring ? "var(--text-primary)" : "var(--text-secondary)",
                    fontWeight: play.scoring ? 600 : 400,
                  }}
                >
                  {play.team && (
                    <span className="font-bold mr-1" style={{ color: "var(--text-muted)", fontSize: "0.6rem" }}>
                      {play.team}
                    </span>
                  )}
                  {play.text}
                </span>
                <span className="shrink-0 text-[0.6rem] tabular-nums" style={{ color: "var(--text-muted)" }}>
                  Q{play.period} {play.clock}
                </span>
              </div>
              <div className="text-[0.6rem] tabular-nums" style={{ color: "var(--text-muted)" }}>
                {awayTricode} {play.away_score} - {play.home_score} {homeTricode}
              </div>
            </div>
          </div>
        ))}
      </div>
      {plays.length > 20 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1.5 text-xs font-medium cursor-pointer"
          style={{ color: "var(--accent)", background: "none", border: "none", padding: 0 }}
        >
          {expanded ? "Show less" : `Show all ${plays.length} plays`}
        </button>
      )}
    </div>
  );
}
