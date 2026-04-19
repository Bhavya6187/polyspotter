"use client";
import Link from "next/link";
import Chip from "./ui/Chip";
import StrengthBars from "./ui/StrengthBars";
import CountdownText from "./ui/CountdownText";
import BookmarkButton from "./ui/BookmarkButton";
import CopyButton from "./ui/CopyButton";
import { useWatchlist } from "../hooks/useWatchlist";
import { SIGNAL_LABELS } from "../lib/signalLabels";
import { usdK, cents } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function Top3Card({ signal, rank }) {
  const { has, toggle } = useWatchlist();
  const saved = has(signal.market.condition_id);
  const moves = signal.price_now != null && signal.price_at_alert != null
    ? Math.round((signal.price_now - signal.price_at_alert) * 100)
    : null;
  const slug = signal.market.condition_id ? marketSlug(signal.market.title, signal.market.condition_id) : null;
  const copyHref = signal.market.condition_id ? `https://polymarket.com/event/${signal.market.condition_id}` : null;

  return (
    <div
      className="relative rounded-2xl p-4"
      style={{
        background: "linear-gradient(180deg, var(--surface-card), var(--surface-1))",
        border: `1px solid ${rank === 1 ? "rgba(0,194,106,0.3)" : "var(--border-strong)"}`,
        boxShadow: rank === 1 ? "var(--shadow-glow)" : "var(--shadow-card)",
      }}
    >
      <div
        className="absolute top-3 right-3"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11, fontWeight: 700, letterSpacing: 1,
          color: rank === 1 ? "var(--accent)" : "var(--text-muted)",
        }}
      >#{rank}</div>

      <div className="flex items-center gap-1.5 mb-2.5">
        <span className="text-sm">{signal.market.icon}</span>
        <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-secondary)" }}>
          {signal.market.topic}
        </span>
        <span style={{ color: "var(--text-muted)", fontSize: 10 }}>·</span>
        <CountdownText endDate={signal.market.end_date} className="text-[10px] font-semibold" />
      </div>

      <Link
        href={slug ? `/market/${slug}` : "#"}
        className="block mb-2.5 font-semibold leading-snug line-clamp-2"
        style={{ fontSize: 14, color: "var(--text-primary)" }}
      >
        {signal.market.title}
      </Link>

      <div
        className="px-2.5 py-2 mb-2.5 rounded-lg text-xs leading-snug line-clamp-3"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--border)",
          color: "var(--text-secondary)",
        }}
      >
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>Why: </span>
        {signal.why}
      </div>

      <div className="flex items-center gap-1 flex-wrap mb-2.5">
        {signal.signals.slice(0, 2).map((k) => {
          const def = SIGNAL_LABELS[k];
          if (!def) return null;
          return <Chip key={k} tone={def.tone}>{def.label}</Chip>;
        })}
        <StrengthBars rating={signal.rating} />
      </div>

      <div
        className="grid grid-cols-3 gap-2 py-2 mb-2.5"
        style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}
      >
        <Stat label="Entry" value={cents(signal.entry_price)} />
        <Stat label="Now"   value={cents(signal.price_now)} delta={moves} />
        <Stat label="Stake" value={usdK(signal.stake_usd)} />
      </div>

      <div className="flex gap-2">
        <CopyButton
          full
          side={signal.side || "YES"}
          returnPct={signal.return_pct}
          onClick={(e) => { e.preventDefault(); if (copyHref) window.open(copyHref, "_blank", "noopener"); }}
        />
        <BookmarkButton
          active={saved}
          onClick={() => { if (signal.market.condition_id) toggle(signal.market.condition_id); }}
        />
      </div>
    </div>
  );
}

function Stat({ label, value, delta }) {
  return (
    <div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
        {value}
        {typeof delta === "number" && (
          <span style={{ fontSize: 10, marginLeft: 4, fontWeight: 600, color: delta >= 0 ? "var(--accent)" : "var(--bearish)" }}>
            {delta >= 0 ? "+" : ""}{delta}¢
          </span>
        )}
      </div>
    </div>
  );
}
