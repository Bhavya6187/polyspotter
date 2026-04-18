import Link from "next/link";
import Sparkline from "./Sparkline";
import { cents } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function MoverCard({ mover, pulseDelay = 0 }) {
  const up = (mover.price_change_24h || 0) >= 0;
  const color = up ? "var(--accent)" : "var(--bearish)";
  const slug = mover.condition_id ? marketSlug(mover.title, mover.condition_id) : null;

  return (
    <Link
      href={slug ? `/market/${slug}` : "#"}
      className="block flex-shrink-0 w-[150px] md:w-[180px] rounded-xl p-2.5"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-xs">{mover.icon}</span>
        <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
          {mover.topic}
        </span>
      </div>
      <div
        className="text-[11px] leading-snug font-medium line-clamp-2 mb-2 min-h-[28px]"
        style={{ color: "var(--text-primary)" }}
      >
        {mover.title}
      </div>
      <div className="flex items-end justify-between gap-1">
        <div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 700 }}>
            {cents(mover.yes_price)}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600, color }}>
            {up ? "↑" : "↓"} {Math.abs(Math.round((mover.price_change_24h || 0) * 100))}¢
          </div>
        </div>
        <div className="animate-mover-pulse" style={{ animationDelay: `${pulseDelay}s` }}>
          <Sparkline data={mover.candles} width={50} height={22} color={color} />
        </div>
      </div>
    </Link>
  );
}
