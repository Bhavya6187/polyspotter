"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchResolvingSoon, fetchVolumeSpikes, fetchActiveWallets, fetchTopMovers } from "../lib/api";
import { useCountdown } from "../hooks/useCountdown";

function formatUsd(n) {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n)}`;
}

function walletName(address) {
  if (!address) return "";
  return `Trader_${address.slice(0, 7)}`;
}

const TIER_COLORS = {
  diamond: { bg: "#58a6ff", label: "DIAMOND" },
  gold: { bg: "#d29922", label: "GOLD" },
  silver: { bg: "#8b949e", label: "SILVER" },
  bronze: { bg: "#a87756", label: "BRONZE" },
};

function CountdownLabel({ endDate }) {
  const countdown = useCountdown(endDate);
  if (!countdown || countdown.total <= 0) return <span style={{ color: "var(--text-muted)" }}>Ended</span>;

  const isUrgent = countdown.total < 6 * 3600 * 1000;
  const hours = Math.floor(countdown.total / 3600000);
  const minutes = Math.floor((countdown.total % 3600000) / 60000);

  let label;
  if (hours > 0) label = `${hours}h ${minutes}m`;
  else label = `${minutes}m`;

  return (
    <span className="font-bold text-sm" style={{ color: isUrgent ? "var(--bearish)" : "var(--warning)" }}>
      {label}
    </span>
  );
}

function ResolvingSoonModule() {
  const [markets, setMarkets] = useState([]);

  useEffect(() => {
    fetchResolvingSoon().then(setMarkets).catch(() => setMarkets([]));
  }, []);

  if (!markets.length) return null;

  return (
    <div className="rounded-lg p-4 mb-3" style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--bearish)" }}>
          Resolving Soon
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{markets.length} markets</span>
      </div>
      <div className="flex flex-col gap-2">
        {markets.slice(0, 5).map((m) => {
          const isUrgent = m.end_date && (new Date(m.end_date) - Date.now()) < 6 * 3600 * 1000;
          return (
            <Link key={m.id || m.condition_id} href={`/market/${m.condition_id}`}
              className="rounded-md p-2.5 hover:opacity-80 transition-opacity"
              style={{ background: "var(--surface-2)", borderLeft: `3px solid ${isUrgent ? "var(--bearish)" : "var(--warning)"}` }}>
              <div className="flex justify-between items-center">
                <span className="text-xs font-semibold truncate" style={{ color: "var(--text-primary)", maxWidth: "160px" }}>
                  {m.market_title}
                </span>
                <CountdownLabel endDate={m.end_date} />
              </div>
              <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {formatUsd(m.total_usd)} smart money{m.dominant_side ? ` on ${m.dominant_side}` : ""}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function LiveFlowModule() {
  const [spikes, setSpikes] = useState([]);
  const [wallets, setWallets] = useState([]);

  useEffect(() => {
    const load = () => {
      fetchVolumeSpikes(5).then(setSpikes).catch(() => setSpikes([]));
      fetchActiveWallets(5).then(setWallets).catch(() => setWallets([]));
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!spikes.length && !wallets.length) return null;

  const maxSpike = spikes.length ? Math.max(...spikes.map((s) => s.spike_ratio)) : 1;

  return (
    <div className="rounded-lg p-4 mb-3" style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--bullish)" }}>
          &#9679; Live Flow
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>last 30m</span>
      </div>

      {spikes.length > 0 && (
        <div className="mb-3">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
            Volume Spikes
          </div>
          {spikes.map((s) => (
            <Link key={s.condition_id} href={`/market/${s.condition_id}`}
              className="block rounded-md p-2 mb-1 hover:opacity-80 transition-opacity"
              style={{ background: "var(--surface-2)" }}>
              <div className="flex justify-between items-center text-xs">
                <span className="truncate" style={{ color: "var(--text-primary)", maxWidth: "150px" }}>
                  {s.market_title}
                </span>
                <span className="font-bold"
                  style={{ color: s.spike_ratio >= 3 ? "var(--warning)" : "var(--text-secondary)" }}>
                  {s.spike_ratio}x
                </span>
              </div>
              <div className="mt-1 rounded-full overflow-hidden" style={{ background: "var(--border)", height: "4px" }}>
                <div className="h-full rounded-full"
                  style={{
                    width: `${Math.min((s.spike_ratio / maxSpike) * 100, 100)}%`,
                    background: s.spike_ratio >= 3 ? "var(--warning)" : "var(--text-muted)",
                  }} />
              </div>
            </Link>
          ))}
        </div>
      )}

      {wallets.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
            Active Sharp Wallets
          </div>
          {wallets.map((w) => (
            <Link key={w.wallet} href={`/wallet/${w.wallet}`}
              className="flex items-center gap-2 rounded-md p-2 mb-1 hover:opacity-80 transition-opacity"
              style={{ background: "var(--surface-2)" }}>
              <span className="text-xs font-bold px-1 py-0.5 rounded"
                style={{ background: TIER_COLORS[w.tier]?.bg || "#8b949e", color: "#0d1117", fontSize: "8px" }}>
                {TIER_COLORS[w.tier]?.label || "BRONZE"}
              </span>
              <span className="text-xs" style={{ color: "var(--text-primary)" }}>
                {walletName(w.wallet)}
              </span>
              <span className="text-xs ml-auto" style={{ color: "var(--text-muted)" }}>
                {w.trade_count} trades
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function TopMoversModule() {
  const [movers, setMovers] = useState([]);

  useEffect(() => {
    fetchTopMovers(6).then(setMovers).catch(() => setMovers([]));
  }, []);

  if (!movers.length) return null;

  return (
    <div className="rounded-lg p-4" style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between items-center mb-3">
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--warning)" }}>
          Top Movers
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>24h</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {movers.map((m) => (
          <Link key={m.condition_id} href={`/market/${m.condition_id}`}
            className="flex justify-between items-center rounded-md p-2 hover:opacity-80 transition-opacity text-xs"
            style={{ background: "var(--surface-2)" }}>
            <span className="truncate" style={{ color: "var(--text-primary)", maxWidth: "170px" }}>
              {m.market_title}
            </span>
            <span className="font-bold" style={{ color: m.change_pct >= 0 ? "var(--bullish)" : "var(--bearish)" }}>
              {m.change_pct >= 0 ? "+" : ""}{m.change_pct}%
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function DashboardSidebar() {
  return (
    <aside className="sticky top-4" style={{ maxHeight: "calc(100vh - 2rem)", overflowY: "auto" }}>
      <ResolvingSoonModule />
      <LiveFlowModule />
      <TopMoversModule />
    </aside>
  );
}
