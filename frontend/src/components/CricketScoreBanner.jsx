"use client";

import { useState, useEffect } from "react";

function Countdown({ targetDate }) {
  const [timeLeft, setTimeLeft] = useState("");

  useEffect(() => {
    const tick = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) {
        setTimeLeft("Starting soon");
        return;
      }
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
        <span className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>
          Live
        </span>
      </div>
    );
  }
  if (status === "final") {
    return (
      <span
        className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold uppercase tracking-wider"
        style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}
      >
        Final
      </span>
    );
  }
  return null;
}

export default function CricketScoreBanner({ game, polymarketPrice }) {
  if (!game) return null;

  const { status, match_time, home, away, toss, venue, odds, status_text } = game;

  return (
    <div
      className="mb-4 overflow-hidden rounded-xl border"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      {/* Score row */}
      <div className="flex items-center justify-center gap-6 px-4 py-4 sm:gap-10 sm:px-8">
        {/* Away team */}
        <div className="text-center min-w-[80px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {away.short_name}
          </div>
          <div
            className="text-2xl font-extrabold tabular-nums leading-tight sm:text-3xl"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-primary)",
            }}
          >
            {status === "pre" ? "\u2014" : away.score || "\u2014"}
          </div>
          {status !== "pre" && away.overs && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              ({away.overs} ov)
            </div>
          )}
        </div>

        {/* Center: status */}
        <div className="text-center">
          <StatusBadge status={status} />
          {status === "pre" && match_time && (
            <div className="mt-1 text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              <Countdown targetDate={match_time} />
            </div>
          )}
          {status_text && status !== "pre" && (
            <div className="mt-1 text-xs max-w-[200px]" style={{ color: "var(--text-secondary)" }}>
              {status_text}
            </div>
          )}
          {venue && (
            <div className="mt-0.5 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              {venue.name}{venue.city ? `, ${venue.city}` : ""}
            </div>
          )}
        </div>

        {/* Home team */}
        <div className="text-center min-w-[80px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {home.short_name}
          </div>
          <div
            className="text-2xl font-extrabold tabular-nums leading-tight sm:text-3xl"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-primary)",
            }}
          >
            {status === "pre" ? "\u2014" : home.score || "\u2014"}
          </div>
          {status !== "pre" && home.overs && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              ({home.overs} ov)
            </div>
          )}
        </div>
      </div>

      {/* Toss info */}
      {toss && toss.winner && (
        <div className="text-center pb-2 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
          Toss: {toss.winner}{toss.decision ? `, elected to ${toss.decision}` : ""}
        </div>
      )}

      {/* Info strip: Odds + Polymarket */}
      <div
        className="grid grid-cols-1 gap-px sm:grid-cols-2"
        style={{ background: "var(--border)", borderTop: "1px solid var(--border)" }}
      >
        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {odds?.provider || "Odds"}
          </div>
          {odds && (odds.home_odds || odds.away_odds) ? (
            <div className="flex gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
              <span>{home.short_name}: <b style={{ color: "var(--text-primary)" }}>{odds.home_odds}</b></span>
              <span>{away.short_name}: <b style={{ color: "var(--text-primary)" }}>{odds.away_odds}</b></span>
            </div>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>

        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            Polymarket
          </div>
          {polymarketPrice != null ? (
            <div className="text-xs font-bold" style={{ color: "var(--accent)" }}>
              {Math.round(polymarketPrice * 100)}&cent;
            </div>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>
      </div>
    </div>
  );
}
