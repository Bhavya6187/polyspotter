"use client";

import { useState } from "react";

function BattingTable({ batting }) {
  if (!batting || batting.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="text-left py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Batter</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>R</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>B</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>4s</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>6s</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>SR</th>
          </tr>
        </thead>
        <tbody>
          {batting.map((b, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-1.5 px-2">
                <div style={{ color: "var(--text-primary)" }}>{b.name}</div>
                {b.how_out && (
                  <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
                    {b.how_out}
                  </div>
                )}
              </td>
              <td className="text-right py-1.5 px-2 font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>{b.runs}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.balls}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.fours}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.sixes}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-muted)" }}>{b.strike_rate.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BowlingTable({ bowling }) {
  if (!bowling || bowling.length === 0) return null;

  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="text-left py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Bowler</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>O</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>M</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>R</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>W</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Econ</th>
          </tr>
        </thead>
        <tbody>
          {bowling.map((b, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-1.5 px-2" style={{ color: "var(--text-primary)" }}>{b.name}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.overs}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.maidens}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.runs}</td>
              <td className="text-right py-1.5 px-2 font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>{b.wickets}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-muted)" }}>{b.economy.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CricketScorecard({ innings = [], home, away }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!innings || innings.length === 0) return null;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      {/* Tabs */}
      <div className="flex" style={{ borderBottom: "1px solid var(--border)" }}>
        {innings.map((inn, i) => (
          <button
            key={i}
            onClick={() => setActiveTab(i)}
            className="flex-1 py-2 text-xs font-semibold uppercase tracking-wider cursor-pointer"
            style={{
              fontFamily: "var(--font-display)",
              background: activeTab === i ? "var(--surface-card)" : "var(--surface-1)",
              color: activeTab === i ? "var(--text-primary)" : "var(--text-muted)",
              border: "none",
              borderBottom: activeTab === i ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            {inn.team}
            {inn.score > 0 && (
              <span className="ml-1.5" style={{ color: "var(--text-secondary)" }}>
                {inn.score}/{inn.wickets}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Active innings */}
      <div className="p-3">
        <BattingTable batting={innings[activeTab]?.batting} />
        <BowlingTable bowling={innings[activeTab]?.bowling} />

        {/* Fall of wickets */}
        {innings[activeTab]?.fall_of_wickets?.length > 0 && (
          <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="text-[0.55rem] uppercase tracking-wider font-semibold mb-1" style={{ color: "var(--text-muted)" }}>
              Fall of Wickets
            </div>
            <div className="flex flex-wrap gap-2 text-[0.6rem]" style={{ color: "var(--text-secondary)" }}>
              {innings[activeTab].fall_of_wickets.map((fow, i) => (
                <span key={i}>
                  {fow.wicket_num}/{fow.score}
                  {fow.batsman && ` (${fow.batsman})`}
                  {fow.over && `, ${fow.over} ov`}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
