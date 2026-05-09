"use client";

import { useState, useEffect } from "react";

function Countdown({ targetDate }) {
  const [timeLeft, setTimeLeft] = useState("");
  useEffect(() => {
    const tick = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) { setTimeLeft("First pitch soon"); return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setTimeLeft(h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetDate]);
  return <span>{timeLeft}</span>;
}

function StatusBadge({ status }) {
  if (status === "live") {
    return (
      <div className="flex items-center gap-1.5">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: "var(--accent)" }} />
          <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} />
        </span>
        <span className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Live</span>
      </div>
    );
  }
  if (status === "final") {
    return (
      <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold uppercase tracking-wider" style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}>Final</span>
    );
  }
  return null;
}

function BaseDiamond({ runners }) {
  if (!runners) return null;
  const dot = (filled) => ({
    width: 8,
    height: 8,
    background: filled ? "var(--accent)" : "var(--surface-2)",
    transform: "rotate(45deg)",
    border: `1px solid var(--border)`,
  });
  return (
    <div className="relative" style={{ width: 32, height: 32 }} aria-label="bases">
      <div className="absolute" style={{ left: 12, top: 0,  ...dot(runners.on_second) }} />
      <div className="absolute" style={{ left: 0,  top: 12, ...dot(runners.on_third)  }} />
      <div className="absolute" style={{ left: 24, top: 12, ...dot(runners.on_first)  }} />
    </div>
  );
}

export default function MLBScoreBanner({ game, polymarketPrice }) {
  if (!game) return null;
  const { status, game_time, inning, half, count, runners, home, away } = game;
  const arrow = half === "top" ? "▲" : half === "bot" ? "▼" : "";

  return (
    <div className="mb-4 overflow-hidden rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <div className="flex items-center justify-center gap-6 px-4 py-4 sm:gap-10 sm:px-8">
        <div className="text-center min-w-[60px]">
          <div className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>{away.abbr}</div>
          <div className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
            {status === "pre" ? "—" : away.runs}
          </div>
          {away.record && <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>{away.record}</div>}
        </div>

        <div className="text-center">
          <StatusBadge status={status} />
          {status === "pre" && game_time && (
            <div className="mt-1 text-sm font-medium" style={{ color: "var(--text-secondary)" }}><Countdown targetDate={game_time} /></div>
          )}
          {status === "live" && (
            <div className="mt-1 text-lg font-bold tabular-nums sm:text-xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
              {arrow} {inning}
            </div>
          )}
          {status === "live" && count && (
            <div className="mt-1 text-[0.65rem] tabular-nums" style={{ color: "var(--text-secondary)" }}>
              {count.balls}-{count.strikes}, {count.outs} out
            </div>
          )}
          {status === "live" && runners && (
            <div className="mt-1 flex justify-center"><BaseDiamond runners={runners} /></div>
          )}
        </div>

        <div className="text-center min-w-[60px]">
          <div className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>{home.abbr}</div>
          <div className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
            {status === "pre" ? "—" : home.runs}
          </div>
          {home.record && <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>{home.record}</div>}
        </div>
      </div>

      {polymarketPrice != null && (
        <div className="border-t px-4 py-2 text-center text-xs" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          Polymarket: {(polymarketPrice * 100).toFixed(0)}¢
        </div>
      )}
    </div>
  );
}
