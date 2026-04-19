"use client";
import Link from "next/link";
import { useState } from "react";
import Chip from "./ui/Chip";
import StrengthBars from "./ui/StrengthBars";
import CountdownText from "./ui/CountdownText";
import WalletAvatar from "./ui/WalletAvatar";
import BookmarkButton from "./ui/BookmarkButton";
import CopyButton from "./ui/CopyButton";
import { useWatchlist } from "../hooks/useWatchlist";
import { SIGNAL_LABELS } from "../lib/signalLabels";
import { usdK, cents, relTime } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function SignalCard({ signal }) {
  const [expanded, setExpanded] = useState(false);
  const { has, toggle } = useWatchlist();
  const saved = has(signal.market.condition_id);
  const moves = signal.price_now != null && signal.price_at_alert != null
    ? Math.round((signal.price_now - signal.price_at_alert) * 100)
    : null;
  const slug = signal.market.condition_id ? marketSlug(signal.market.title, signal.market.condition_id) : null;
  const copyHref = signal.market.condition_id ? `https://polymarket.com/event/${signal.market.condition_id}` : null;
  const panelId = `why-${signal.id}`;

  return (
    <article
      className="rounded-2xl p-3 md:p-4 mb-3"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <WalletAvatar wallet={signal.wallet} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Link
              href={`/wallet/${signal.wallet.addr}`}
              style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, letterSpacing: 0.3, color: "var(--text-primary)" }}
            >
              {signal.wallet.alias}
            </Link>
            {signal.wallet.tier === "legend" && <span className="text-[10px]">★</span>}
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600, color: "var(--accent)" }}>
              {Math.round(signal.wallet.win_rate * 100)}%
            </span>
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
            {signal.wallet.bets} bets · {relTime(signal.created_at)}
          </div>
        </div>
        <StrengthBars rating={signal.rating} />
      </div>

      <Link
        href={slug ? `/market/${slug}` : "#"}
        className="block mb-2 text-sm md:text-[15px] font-semibold leading-snug"
        style={{ color: "var(--text-primary)" }}
      >
        <span className="mr-1.5">{signal.market.icon}</span>
        {signal.market.title}
      </Link>

      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="block w-full text-left px-2.5 py-2 mb-2.5 rounded-lg text-xs leading-snug"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--border)",
          color: "var(--text-secondary)",
          transition: "max-height 200ms ease-out",
        }}
      >
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>Why: </span>
        {signal.why}
        {expanded && signal.bullets?.length > 0 && (
          <ul id={panelId} className="mt-2 pl-4 text-[10.5px] leading-relaxed list-disc" style={{ color: "var(--text-secondary)" }}>
            {signal.bullets.filter(Boolean).map((b, i) => <li key={i} className="mb-0.5">{b}</li>)}
          </ul>
        )}
      </button>

      <div className="flex flex-wrap gap-1 mb-2.5">
        {(signal.signals || []).map((k) => {
          const def = SIGNAL_LABELS[k];
          if (!def) return null;
          return <Chip key={k} tone={def.tone}>{def.label}</Chip>;
        })}
      </div>

      <div className="flex items-center gap-3 pt-2.5" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="flex-1 flex gap-4">
          <Stat
            label={signal.side || "SIDE"}
            value={cents(signal.price_now)}
            delta={moves}
          />
          <Stat label="Stake" value={usdK(signal.stake_usd)} />
          <div>
            <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
              Ends
            </div>
            <CountdownText endDate={signal.market.end_date} className="text-[13px] font-bold" />
          </div>
        </div>
        <BookmarkButton
          active={saved}
          size={36}
          onClick={() => { if (signal.market.condition_id) toggle(signal.market.condition_id); }}
        />
        <CopyButton
          size="sm"
          side={signal.side || "YES"}
          returnPct={signal.return_pct}
          onClick={() => copyHref && window.open(copyHref, "_blank", "noopener")}
        />
      </div>
    </article>
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
