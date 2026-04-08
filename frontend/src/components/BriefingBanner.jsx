"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchBriefing, fetchTrackRecord, fetchResolvedSignals } from "../lib/api";

function formatUsd(n) {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n)}`;
}

function walletName(address) {
  if (!address) return "";
  return `Trader_${address.slice(0, 7)}`;
}

function timeSinceLabel(isoString) {
  if (!isoString) return "";
  const ms = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(ms / 3600000);
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const TIER_COLORS = {
  diamond: { bg: "#58a6ff", label: "DIAMOND" },
  gold: { bg: "#d29922", label: "GOLD" },
  silver: { bg: "#8b949e", label: "SILVER" },
  bronze: { bg: "#a87756", label: "BRONZE" },
};

export default function BriefingBanner() {
  const [briefing, setBriefing] = useState(null);
  const [trackRecord, setTrackRecord] = useState(null);
  const [resolved, setResolved] = useState([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    try {
      const d = sessionStorage.getItem("polyspotter_briefing_dismissed");
      if (d === "true") { setDismissed(true); return; }
    } catch {}

    let since = null;
    try {
      since = localStorage.getItem("polyspotter_last_visit");
    } catch {}

    Promise.all([
      fetchBriefing(since).catch(() => null),
      fetchTrackRecord(7).catch(() => null),
      fetchResolvedSignals(5).catch(() => []),
    ]).then(([b, tr, rs]) => {
      setBriefing(b);
      setTrackRecord(tr);
      setResolved(rs || []);
    });

    try {
      localStorage.setItem("polyspotter_last_visit", new Date().toISOString());
    } catch {}

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        let s = null;
        try { s = localStorage.getItem("polyspotter_last_visit"); } catch {}
        fetchBriefing(s).then(setBriefing).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    try { sessionStorage.setItem("polyspotter_briefing_dismissed", "true"); } catch {}
  };

  if (dismissed || (!briefing && !trackRecord)) return null;

  const sinceLabel = briefing ? timeSinceLabel(briefing.since) : "";

  return (
    <div
      className="rounded-xl mb-5"
      style={{
        background: "linear-gradient(135deg, var(--surface-1) 0%, var(--surface-2) 100%)",
        border: "1px solid var(--border)",
        padding: "16px 20px",
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--warning)" }}>
            Briefing
          </span>
          {sinceLabel && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Since {sinceLabel}
            </span>
          )}
        </div>
        <button
          onClick={handleDismiss}
          className="text-xs hover:opacity-70 transition-opacity"
          style={{ color: "var(--text-muted)" }}
        >
          Dismiss &times;
        </button>
      </div>

      {/* Row 1: Stats | Biggest Move | Hot Wallet */}
      <div className="flex flex-col md:flex-row md:items-center gap-4 md:gap-6">
        {briefing && (
          <div className="flex gap-5 flex-shrink-0">
            <div className="text-center">
              <div className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                {briefing.new_signals}
              </div>
              <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                New Signals
              </div>
            </div>
            {trackRecord && (
              <>
                <div className="text-center">
                  <div className="text-2xl font-bold"
                    style={{ color: trackRecord.hypothetical_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" }}>
                    {trackRecord.hypothetical_pnl >= 0 ? "+" : ""}{formatUsd(trackRecord.hypothetical_pnl)}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Signal P&L
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                    {trackRecord.total}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Resolved
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold" style={{ color: "var(--bullish)" }}>
                    {trackRecord.wins}/{trackRecord.total}
                  </div>
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Won
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        <div className="hidden md:block w-px self-stretch" style={{ background: "var(--border)" }} />

        {briefing?.biggest_move && (
          <Link href={`/market/${briefing.biggest_move.condition_id}`}
            className="flex items-center gap-3 flex-1 min-w-0 hover:opacity-80 transition-opacity">
            <div className="flex-shrink-0">
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
                Biggest Move
              </div>
              <div className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)", maxWidth: "200px" }}>
                {briefing.biggest_move.market_title}
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {formatUsd(briefing.biggest_move.total_usd)} smart money &bull; {briefing.biggest_move.wallet_count} wallet{briefing.biggest_move.wallet_count !== 1 ? "s" : ""}
              </div>
            </div>
          </Link>
        )}

        <div className="hidden md:block w-px self-stretch" style={{ background: "var(--border)" }} />

        {briefing?.hot_wallet && (
          <Link href={`/wallet/${briefing.hot_wallet.wallet}`}
            className="flex items-center gap-2 flex-shrink-0 hover:opacity-80 transition-opacity">
            <div>
              <div className="text-xs uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
                Hot Wallet
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold px-1.5 py-0.5 rounded"
                  style={{
                    background: TIER_COLORS[briefing.hot_wallet.tier]?.bg || "#8b949e",
                    color: "#0d1117",
                  }}>
                  {TIER_COLORS[briefing.hot_wallet.tier]?.label || "BRONZE"}
                </span>
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {walletName(briefing.hot_wallet.wallet)}
                </span>
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                {Math.round(briefing.hot_wallet.win_rate * 100)}% WR &bull; {briefing.hot_wallet.trade_count} trades
              </div>
            </div>
          </Link>
        )}
      </div>

      {/* Row 2: Track Record Streak + Just Resolved */}
      {(trackRecord || resolved.length > 0) && (
        <>
          <div className="my-3" style={{ borderTop: "1px solid var(--border)" }} />
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            {trackRecord && trackRecord.total > 0 && (
              <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--warning)" }}>Last {trackRecord.days}d:</span>{" "}
                {trackRecord.wins}/{trackRecord.total} signals won ({Math.round(trackRecord.win_rate * 100)}%)
                {" — "}
                <span style={{ color: trackRecord.hypothetical_pnl >= 0 ? "var(--bullish)" : "var(--bearish)" }}>
                  {trackRecord.hypothetical_pnl >= 0 ? "+" : ""}{formatUsd(trackRecord.hypothetical_pnl)} hypothetical P&L
                </span>
              </div>
            )}

            {trackRecord && resolved.length > 0 && (
              <div className="hidden sm:block w-px h-4" style={{ background: "var(--border)" }} />
            )}

            {resolved.length > 0 && (
              <div className="flex gap-3 overflow-x-auto flex-1">
                {resolved.map((r) => (
                  <Link key={r.id} href={`/market/${r.condition_id}`}
                    className="flex items-center gap-1.5 flex-shrink-0 text-xs hover:opacity-80 transition-opacity">
                    <span style={{ color: r.signal_was_correct ? "var(--bullish)" : "var(--bearish)" }}>
                      {r.signal_was_correct ? "✓" : "✗"}
                    </span>
                    <span className="truncate" style={{ color: "var(--text-secondary)", maxWidth: "120px" }}>
                      {r.market_title}
                    </span>
                    <span className="font-semibold"
                      style={{ color: r.pnl_per_share >= 0 ? "var(--bullish)" : "var(--bearish)" }}>
                      {r.pnl_per_share >= 0 ? "+" : ""}{Math.round(r.pnl_per_share * 100)}%
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
