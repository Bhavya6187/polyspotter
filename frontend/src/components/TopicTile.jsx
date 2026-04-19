import Sparkline from "./Sparkline";
import { usdK } from "../lib/signalAdapter";

export default function TopicTile({ topic, onClick }) {
  const up = (topic.trend || 0) >= 0;
  const color = up ? "var(--accent)" : "var(--bearish)";
  return (
    <button
      onClick={() => onClick?.(topic.name)}
      className="text-left rounded-xl p-3 md:p-4"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between mb-2.5">
        <div className="grid place-items-center" style={{ width: 32, height: 32, borderRadius: 9, background: "rgba(255,255,255,0.04)", fontSize: 16 }}>
          {topic.icon}
        </div>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 700, color }}>
          {up ? "+" : ""}{topic.trend}%
        </span>
      </div>
      <div className="font-bold text-sm md:text-base mb-1" style={{ color: "var(--text-primary)" }}>
        {topic.name}
      </div>
      <div className="text-xs mb-2.5" style={{ color: "var(--text-muted)" }}>
        {topic.signals} signals · {usdK(topic.volume_24h)}
      </div>
      <Sparkline data={topic.spark} width={120} height={26} color={color} />
    </button>
  );
}
