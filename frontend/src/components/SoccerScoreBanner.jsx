"use client";

import { useState, useEffect } from "react";

function Countdown({ targetDate }) {
  const [timeLeft, setTimeLeft] = useState("");
  useEffect(() => {
    const tick = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) { setTimeLeft("Kickoff soon"); return; }
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
    return <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold uppercase tracking-wider" style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}>Full Time</span>;
  }
  return null;
}

export default function SoccerScoreBanner({ game, polymarketPrice }) {
  if (!game) return null;
  const { status, game_time, minute, competition, home, away, aggregate, odds } = game;

  return (
    <div className="mb-4 overflow-hidden rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <div className="flex items-center justify-center gap-6 px-4 py-4 sm:gap-10 sm:px-8">
        <div className="text-center min-w-[80px]">
          {away.crest_url && <img src={away.crest_url} alt={away.name} className="mx-auto mb-1 h-8 w-8" />}
          <div className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>{away.abbr || away.name}</div>
          <div className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>{status === "pre" ? "—" : away.score}</div>
          {away.form && <div className="text-[0.6rem] tabular-nums tracking-wider" style={{ color: "var(--text-muted)" }}>{away.form}</div>}
        </div>

        <div className="text-center">
          <div className="mb-1 text-[0.55rem] font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{competition}</div>
          <StatusBadge status={status} />
          {status === "pre" && game_time && (
            <div className="mt-1 text-sm font-medium" style={{ color: "var(--text-secondary)" }}><Countdown targetDate={game_time} /></div>
          )}
          {status === "live" && minute && (
            <div className="mt-1 text-lg font-bold tabular-nums sm:text-xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
              {minute}
            </div>
          )}
          {aggregate && (
            <div className="mt-1 text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Agg {aggregate.away}-{aggregate.home} · Leg {aggregate.leg}
            </div>
          )}
        </div>

        <div className="text-center min-w-[80px]">
          {home.crest_url && <img src={home.crest_url} alt={home.name} className="mx-auto mb-1 h-8 w-8" />}
          <div className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>{home.abbr || home.name}</div>
          <div className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>{status === "pre" ? "—" : home.score}</div>
          {home.form && <div className="text-[0.6rem] tabular-nums tracking-wider" style={{ color: "var(--text-muted)" }}>{home.form}</div>}
        </div>
      </div>

      {(odds || polymarketPrice != null) && (
        <div className="flex items-center justify-center gap-4 border-t px-4 py-2 text-center text-xs" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          {odds && (
            <span>
              {odds.home_odds && <span><span className="font-semibold" style={{ color: "var(--text-primary)" }}>{home.abbr || "H"}</span> {odds.home_odds}</span>}
              {odds.draw_odds && <span className="ml-3">Draw {odds.draw_odds}</span>}
              {odds.away_odds && <span className="ml-3"><span className="font-semibold" style={{ color: "var(--text-primary)" }}>{away.abbr || "A"}</span> {odds.away_odds}</span>}
            </span>
          )}
          {polymarketPrice != null && <span>Polymarket: {(polymarketPrice * 100).toFixed(0)}¢</span>}
        </div>
      )}
    </div>
  );
}
