"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useWatchlist } from "../../hooks/useWatchlist";
import { fetchMarketCard } from "../../lib/api";
import Sparkline from "../Sparkline";
import { cents } from "../../lib/signalAdapter";
import { marketSlug } from "../../lib/slugify";

export default function WatchlistBlock({ full = false }) {
  const { ids, remove } = useWatchlist();
  const [markets, setMarkets] = useState({});

  useEffect(() => {
    ids.forEach((cid) => {
      if (markets[cid]) return;
      fetchMarketCard(cid).then((m) => setMarkets((s) => ({ ...s, [cid]: m }))).catch(() => {});
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  if (!ids.length) {
    return (
      <div className={`rounded-xl p-4 ${full ? "" : "mb-3"}`} style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
        <div className="text-xs font-bold mb-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Watchlist
        </div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          Tap the bookmark icon on any card to watch a market.
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-xl p-4 ${full ? "" : "mb-3"}`} style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Watchlist
        </div>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{ids.length}</span>
      </div>
      <ul className="space-y-3">
        {ids.map((cid) => {
          const m = markets[cid];
          if (!m) return <li key={cid} className="text-xs" style={{ color: "var(--text-muted)" }}>Loading…</li>;
          const up = (m.price_change_24h || 0) >= 0;
          const color = up ? "var(--accent)" : "var(--bearish)";
          const slug = marketSlug(m.title, cid);
          return (
            <li key={cid} className="flex items-center gap-2">
              <Link href={`/market/${slug}`} className="flex-1 min-w-0">
                <div className="text-xs font-semibold line-clamp-1" style={{ color: "var(--text-primary)" }}>{m.title}</div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
                  {cents(m.yes_price)}
                  <span style={{ color, marginLeft: 4, fontSize: 10 }}>
                    {up ? "▲" : "▼"} {Math.abs(Math.round((m.price_change_24h || 0) * 100))}¢
                  </span>
                </div>
              </Link>
              <Sparkline data={m.candles || []} width={50} height={20} color={color} />
              <button
                onClick={() => remove(cid)}
                aria-label="Remove from watchlist"
                className="text-xs px-2 py-1"
                style={{ color: "var(--text-muted)" }}
              >✕</button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
