"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import AlertRow from "../../../components/AlertRow";
import PriceChart from "../../../components/PriceChart";
import MarketStats from "../../../components/MarketStats";
import HoldersLeaderboard from "../../../components/HoldersLeaderboard";
import MarketPulse from "../../../components/MarketPulse";
import MarketTheses from "../../../components/MarketTheses";
import CricketScoreBanner from "../../../components/CricketScoreBanner";
import BallByBallFeed from "../../../components/BallByBallFeed";
import CricketScorecard from "../../../components/CricketScorecard";
import CricketMatchInfo from "../../../components/CricketMatchInfo";
import CricketPreMatch from "../../../components/CricketPreMatch";
import useLiveMarket from "../../../hooks/useLiveMarket";
import useCricketData from "../../../hooks/useCricketData";
import ThemeToggle from "../../../components/ThemeToggle";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return "Resolved";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

export default function CricketPageClient({
  conditionId,
  initialLive,
  initialAlerts,
  priceHistory,
  holders,
  theses,
  initialCricketData,
  eventSlug = "",
}) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];
  const [descExpanded, setDescExpanded] = useState(false);

  const marketTitle = live?.title || alerts?.[0]?.market_title || "";
  const slug = eventSlug || alerts?.[0]?.event_slug || "";
  const { data: cricketData } = useCricketData(conditionId, { initialData: initialCricketData, title: marketTitle, eventSlug: slug });

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const isUrgent = endDate && new Date(endDate).getTime() - Date.now() < 3600000 && new Date(endDate).getTime() - Date.now() > 0;
  const isSoon = endDate && new Date(endDate).getTime() - Date.now() < 86400000 && new Date(endDate).getTime() - Date.now() > 0;

  const outcomes = live?.outcomes || [];
  const description = alerts?.[0]?.market_description || live?.description;

  return (
    <main className="mx-auto max-w-5xl px-4 py-4">
      {/* Nav */}
      <nav className="mb-4 flex items-center justify-between" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: "var(--text-muted)" }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <ThemeToggle />
      </nav>

      {/* Compact header */}
      <header className="mb-4">
        <div className="flex gap-4 items-start">
          {alerts?.[0]?.market_image && (
            <div
              className="relative shrink-0 rounded-lg overflow-hidden"
              style={{ width: "72px", height: "72px", border: "1px solid var(--border)" }}
            >
              <Image src={alerts[0].market_image} alt="" fill className="object-cover" />
            </div>
          )}

          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
              {title}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
              {resolution && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"
                  style={{
                    background: isUrgent ? "rgba(239, 68, 68, 0.1)" : isSoon ? "rgba(245, 158, 11, 0.1)" : "var(--surface-2)",
                    color: resolution === "Resolved" ? "var(--text-muted)" : isUrgent ? "var(--bearish)" : isSoon ? "var(--warning)" : "var(--text-secondary)",
                    fontSize: "0.65rem",
                  }}
                >
                  {isUrgent && (
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                    </span>
                  )}
                  {resolution}
                </span>
              )}
              {totalUsd > 0 && (
                <span style={{ fontFamily: "var(--font-display)" }}>{usdFmt.format(totalUsd)} tracked</span>
              )}
              <span>{alerts.length} signal{alerts.length !== 1 ? "s" : ""}</span>
              {tags.map((t) => (
                <span key={t} className="rounded-full px-1.5 py-0.5" style={{ background: "var(--surface-2)", color: "var(--text-muted)", fontSize: "0.6rem" }}>
                  {t}
                </span>
              ))}
            </div>
          </div>

          {/* Outcome pills */}
          {outcomes.length > 0 && (
            <div className="hidden sm:flex items-center gap-2 shrink-0">
              {outcomes.map((o) => {
                const pct = Math.round((o.price || 0) * 100);
                const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
                const isLeading = pct === maxPct && pct > 50;
                return (
                  <div key={o.name} className="rounded-lg border px-3 py-1.5 text-center" style={{ borderColor: isLeading ? "rgba(0, 194, 106, 0.3)" : "var(--border)", background: "var(--surface-card)", boxShadow: isLeading ? "var(--glow-medium)" : "none", minWidth: "72px" }}>
                    <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>{o.name}</div>
                    <div className="text-lg font-bold tabular-nums leading-tight" style={{ fontFamily: "var(--font-display)", color: isLeading ? "var(--accent)" : "var(--text-primary)" }}>{pct}&cent;</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Mobile outcome row */}
        {outcomes.length > 0 && (
          <div className="sm:hidden mt-3 flex gap-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
              const isLeading = pct === maxPct && pct > 50;
              return (
                <div key={o.name} className="flex-1 rounded-lg border px-3 py-1.5 text-center" style={{ borderColor: isLeading ? "rgba(0, 194, 106, 0.3)" : "var(--border)", background: "var(--surface-card)", boxShadow: isLeading ? "var(--glow-medium)" : "none" }}>
                  <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>{o.name}</div>
                  <div className="text-lg font-bold tabular-nums leading-tight" style={{ fontFamily: "var(--font-display)", color: isLeading ? "var(--accent)" : "var(--text-primary)" }}>{pct}&cent;</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Description */}
        {description && (
          <div className="mt-2">
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)", display: "-webkit-box", WebkitLineClamp: descExpanded ? "unset" : 2, WebkitBoxOrient: "vertical", overflow: descExpanded ? "visible" : "hidden" }}>
              {description}
            </p>
            {description.length > 140 && (
              <button onClick={() => setDescExpanded(!descExpanded)} className="mt-0.5 text-xs font-medium cursor-pointer" style={{ color: "var(--accent)", background: "none", border: "none", padding: 0 }}>
                {descExpanded ? "Less" : "More"}
              </button>
            )}
          </div>
        )}
      </header>

      {/* Cricket Score Banner */}
      <CricketScoreBanner game={cricketData} polymarketPrice={outcomes?.[0]?.price} />

      {/* Cricket Match Info bar */}
      {cricketData && cricketData.status !== "pre" && (
        <div className="mb-4">
          <CricketMatchInfo game={cricketData} />
        </div>
      )}

      {/* Two-column: Trades (primary) + Sidebar */}
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        {/* Left: Notable Trades */}
        <section>
          {alerts.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}>
                Notable Trades
              </h2>
              {alerts.map((alert) => (
                <AlertRow key={alert.id} alert={alert} autoExpand activeTag="" onTagClick={() => {}} liveMarket={live} />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border p-12 text-center" style={{ borderColor: "var(--border)", background: "var(--surface-card)", color: "var(--text-muted)" }}>
              No signals found for this market.
            </div>
          )}
        </section>

        {/* Right sidebar */}
        <aside className="flex flex-col gap-4">
          {/* Price Chart */}
          {priceHistory && priceHistory.history?.length > 1 && (
            <PriceChart history={priceHistory.history} outcome={priceHistory.outcome} alerts={alerts} conditionId={conditionId} />
          )}

          {/* Market Stats */}
          <MarketStats volume24h={live?.volume_24h} liquidity={live?.liquidity} spread={live?.spread} alerts={alerts} />

          {/* Cricket Widgets */}
          {cricketData && (
            <>
              {/* Pre-match preview */}
              {cricketData.status === "pre" && (
                <CricketPreMatch game={cricketData} />
              )}

              {/* Ball-by-ball feed (live/complete) */}
              {cricketData.balls?.length > 0 && (
                <BallByBallFeed balls={cricketData.balls} />
              )}

              {/* Scorecard (live/complete) */}
              {cricketData.innings?.length > 0 && (
                <CricketScorecard innings={cricketData.innings} />
              )}
            </>
          )}

          {/* Holders + Pulse */}
          {(holders?.length > 0 || alerts.length > 0) && (
            <>
              <HoldersLeaderboard holders={holders} />
              <MarketPulse alerts={alerts} volume24h={live?.volume_24h} />
            </>
          )}
        </aside>
      </div>

      {/* Related Theses */}
      {theses?.length > 0 && (
        <div className="mt-8">
          <MarketTheses theses={theses} />
        </div>
      )}
    </main>
  );
}
