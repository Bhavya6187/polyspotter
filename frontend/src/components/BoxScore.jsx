"use client";

import { useState } from "react";

export default function BoxScore({ boxScore, homeTricode, awayTricode }) {
  const [activeTab, setActiveTab] = useState("away");

  if (!boxScore) return null;

  const tabs = [
    { key: "away", label: awayTricode || "Away", data: boxScore.away },
    { key: "home", label: homeTricode || "Home", data: boxScore.home },
  ];

  const activeData = tabs.find((t) => t.key === activeTab)?.data;
  if (!activeData || activeData.players.length === 0) return null;

  const starters = activeData.players.filter((p) => p.starter);
  const bench = activeData.players.filter((p) => !p.starter);

  const sortByMin = (a, b) => {
    const parseMin = (m) => {
      const [mins, secs] = m.split(":").map(Number);
      return (mins || 0) * 60 + (secs || 0);
    };
    return parseMin(b.minutes) - parseMin(a.minutes);
  };
  starters.sort(sortByMin);
  bench.sort(sortByMin);

  const renderRow = (p) => (
    <tr key={p.name} style={{ borderBottom: "1px solid var(--border)" }}>
      <td className="py-1.5 pr-2 text-xs font-medium truncate max-w-[100px]" style={{ color: "var(--text-primary)" }}>
        {p.name}
        {p.position && (
          <span className="ml-1 text-[0.55rem]" style={{ color: "var(--text-muted)" }}>{p.position}</span>
        )}
      </td>
      <td className="py-1.5 px-1.5 text-center text-[0.65rem] tabular-nums" style={{ color: "var(--text-muted)" }}>{p.minutes}</td>
      <td className="py-1.5 px-1.5 text-center text-xs font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>{p.points}</td>
      <td className="py-1.5 px-1.5 text-center text-[0.65rem] tabular-nums" style={{ color: "var(--text-secondary)" }}>{p.rebounds}</td>
      <td className="py-1.5 px-1.5 text-center text-[0.65rem] tabular-nums" style={{ color: "var(--text-secondary)" }}>{p.assists}</td>
      <td className="py-1.5 px-1.5 text-center text-[0.65rem] tabular-nums" style={{ color: "var(--text-secondary)" }}>{p.fg}</td>
      <td className="py-1.5 px-1.5 text-center text-[0.65rem] tabular-nums" style={{ color: p.plus_minus > 0 ? "var(--accent)" : p.plus_minus < 0 ? "var(--bearish)" : "var(--text-muted)" }}>
        {p.plus_minus > 0 ? "+" : ""}{p.plus_minus}
      </td>
    </tr>
  );

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}
      >
        Box Score
      </h3>
      <div className="flex gap-1 mb-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className="rounded-md px-3 py-1 text-xs font-semibold cursor-pointer transition-colors"
            style={{
              fontFamily: "var(--font-display)",
              background: activeTab === tab.key ? "var(--accent)" : "var(--surface-2)",
              color: activeTab === tab.key ? "#fff" : "var(--text-muted)",
              border: "none",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        className="overflow-x-auto rounded-xl border"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        <table className="w-full" style={{ minWidth: "380px" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Player", "MIN", "PTS", "REB", "AST", "FG", "+/-"].map((h) => (
                <th key={h} className={`py-1.5 ${h === "Player" ? "pr-2 text-left" : "px-1.5 text-center"} text-[0.55rem] uppercase tracking-wider font-semibold`} style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody style={{ fontSize: "0.75rem" }}>
            {starters.map(renderRow)}
            {bench.length > 0 && (
              <tr>
                <td colSpan={7} className="py-1 text-[0.55rem] uppercase tracking-wider font-semibold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)", background: "var(--surface-2)" }}>
                  &nbsp;Bench
                </td>
              </tr>
            )}
            {bench.map(renderRow)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
