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

export default function LiveScoreBanner({ game, polymarketPrice }) {
  if (!game) return null;

  const { status, clock, period, period_label, home, away, odds, win_probability, plays, venue, broadcast } = game;
  const lastPlay = plays?.[0];
  const awayLeading = away.score > home.score;
  const homeLeading = home.score > away.score;

  return (
    <div
      className="mb-4 overflow-hidden rounded-xl border"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      {/* Score row */}
      <div className="flex items-center justify-center gap-6 px-4 py-4 sm:gap-10 sm:px-8">
        <div className="text-center min-w-[60px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {away.tricode}
          </div>
          <div
            className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl"
            style={{
              fontFamily: "var(--font-display)",
              color: awayLeading ? "var(--text-primary)" : "var(--text-secondary)",
            }}
          >
            {status === "pre" ? "\u2014" : away.score}
          </div>
          {away.record && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              {away.record}
            </div>
          )}
        </div>

        <div className="text-center">
          <StatusBadge status={status} />
          {status === "live" && (
            <div
              className="mt-1 text-lg font-bold tabular-nums sm:text-xl"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              {period_label} {clock}
            </div>
          )}
          {status === "pre" && (
            <div className="mt-1 text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              <Countdown targetDate={game.tipoff || ""} />
            </div>
          )}
          {venue && (
            <div className="mt-0.5 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              {venue}
            </div>
          )}
        </div>

        <div className="text-center min-w-[60px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {home.tricode}
          </div>
          <div
            className="text-3xl font-extrabold tabular-nums leading-tight sm:text-4xl"
            style={{
              fontFamily: "var(--font-display)",
              color: homeLeading ? "var(--text-primary)" : "var(--text-secondary)",
            }}
          >
            {status === "pre" ? "\u2014" : home.score}
          </div>
          {home.record && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              {home.record}
            </div>
          )}
        </div>
      </div>

      {/* Quarter scores */}
      {status !== "pre" && home.quarter_scores?.length > 0 && (
        <div
          className="flex justify-center gap-3 pb-2 text-[0.6rem] tabular-nums"
          style={{ color: "var(--text-muted)" }}
        >
          {home.quarter_scores.map((_, i) => (
            <span key={i}>
              {i < 4 ? `Q${i + 1}` : `OT${i - 3}`}: {away.quarter_scores?.[i] ?? 0}-{home.quarter_scores[i]}
            </span>
          ))}
        </div>
      )}

      {/* Info strip: Odds + Win Prob + Last Play */}
      <div
        className="grid grid-cols-1 gap-px sm:grid-cols-3"
        style={{ background: "var(--border)", borderTop: "1px solid var(--border)" }}
      >
        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {odds?.provider || "Odds"}
          </div>
          {odds ? (
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
              {odds.spread && <span>Spread: <b style={{ color: "var(--text-primary)" }}>{odds.spread.display}</b></span>}
              {odds.over_under && <span>O/U: <b style={{ color: "var(--text-primary)" }}>{odds.over_under}</b></span>}
              {odds.moneyline && (
                <span>ML: <b style={{ color: "var(--text-primary)" }}>{odds.moneyline.away}/{odds.moneyline.home}</b></span>
              )}
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
            Win Prob
          </div>
          {win_probability ? (
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "var(--surface-2)" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.round(win_probability.away * 100)}%`, background: "var(--accent)" }}
                />
              </div>
              <span className="text-xs font-bold tabular-nums" style={{ color: "var(--accent)" }}>
                {Math.round(win_probability.away * 100)}%
              </span>
            </div>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
          {polymarketPrice != null && (
            <div className="mt-0.5 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              Poly: {Math.round(polymarketPrice * 100)}&cent;
            </div>
          )}
        </div>

        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            Last Play
          </div>
          {lastPlay ? (
            <>
              <div className="text-xs truncate" style={{ color: "var(--text-primary)" }}>
                {lastPlay.text}
              </div>
              <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
                {period_label} {lastPlay.clock} &middot; {away.tricode} {lastPlay.away_score}-{lastPlay.home_score} {home.tricode}
              </div>
            </>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              {status === "pre" ? "Game hasn\u2019t started" : "\u2014"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
