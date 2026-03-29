"use client";

import { useState } from "react";
import Link from "next/link";
import AlertRow from "../../../components/AlertRow";
import PriceMovement from "../../../components/PriceMovement";
import PriceChart from "../../../components/PriceChart";
import MarketStats from "../../../components/MarketStats";
import HoldersLeaderboard from "../../../components/HoldersLeaderboard";
import MarketPulse from "../../../components/MarketPulse";
import MarketTheses from "../../../components/MarketTheses";
import useLiveMarket from "../../../hooks/useLiveMarket";
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

export default function MarketPageClient({
  conditionId,
  initialLive,
  initialAlerts,
  priceHistory,
  holders,
  theses,
}) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const isUrgent = endDate && new Date(endDate).getTime() - Date.now() < 3600000 && new Date(endDate).getTime() - Date.now() > 0;
  const isSoon = endDate && new Date(endDate).getTime() - Date.now() < 86400000 && new Date(endDate).getTime() - Date.now() > 0;

  const outcomes = live?.outcomes || [];

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      {/* Nav */}
      <nav className="mb-6 flex items-center justify-between" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: 'var(--text-muted)' }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <ThemeToggle />
      </nav>

      {/* Market image */}
      {(alerts?.[0]?.market_image || live?.image) && (
        <div
          className="rounded-xl overflow-hidden mb-6"
          style={{ border: "1px solid var(--border)" }}
        >
          <div className="relative w-full" style={{ aspectRatio: "16/9" }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={alerts[0]?.market_image || live?.image}
              alt={title}
              className="w-full h-full object-cover"
            />
          </div>
        </div>
      )}

      {/* Market header */}
      <header className="mb-8">
        <h1 className="text-2xl font-bold leading-snug" style={{ color: 'var(--text-primary)' }}>
          {title}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {resolution && (
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
              style={{
                background: isUrgent ? 'rgba(239, 68, 68, 0.1)' : isSoon ? 'rgba(245, 158, 11, 0.1)' : 'var(--surface-2)',
                color: resolution === "Resolved"
                  ? 'var(--text-muted)'
                  : isUrgent
                    ? 'var(--bearish)'
                    : isSoon
                      ? 'var(--warning)'
                      : 'var(--text-secondary)',
              }}
            >
              {isUrgent && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                </span>
              )}
              Resolves in {resolution}
            </span>
          )}
          {totalUsd > 0 && (
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.8rem' }}>
              {usdFmt.format(totalUsd)} tracked
            </span>
          )}
          <span>
            {alerts.length} signal{alerts.length !== 1 ? "s" : ""}
          </span>
        </div>

        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <span
                key={t}
                className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
              >
                {t}
              </span>
            ))}
          </div>
        )}

        {(alerts?.[0]?.market_description || live?.description) && (
          <p
            className="mt-3 text-sm leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            {alerts[0]?.market_description || live?.description}
          </p>
        )}
      </header>

      {/* Live outcomes */}
      {outcomes.length > 0 && (() => {
        const maxPct = Math.max(...outcomes.map((o) => Math.round((o.price || 0) * 100)));
        return (
          <div className="mb-6 grid gap-3 sm:grid-cols-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              const isLeading = pct === maxPct && pct > 50;
              return (
                <div
                  key={o.name}
                  className="rounded-xl border p-4 relative overflow-hidden"
                  style={{
                    borderColor: isLeading ? 'rgba(0, 194, 106, 0.3)' : 'var(--border)',
                    background: 'var(--surface-card)',
                    boxShadow: isLeading ? 'var(--glow-medium)' : 'none',
                  }}
                >
                  <div
                    className="absolute inset-y-0 left-0 transition-all duration-700"
                    style={{
                      width: `${pct}%`,
                      background: isLeading
                        ? 'linear-gradient(90deg, rgba(0, 194, 106, 0.10) 0%, rgba(0, 194, 106, 0.04) 100%)'
                        : 'linear-gradient(90deg, rgba(139, 145, 163, 0.07) 0%, rgba(139, 145, 163, 0.02) 100%)',
                    }}
                  />
                  <div className="relative flex items-center justify-between mb-3">
                    <span className="font-medium text-[0.95rem]" style={{ color: 'var(--text-primary)' }}>
                      {o.name}
                    </span>
                    <span
                      className="text-xl font-bold tabular-nums"
                      style={{
                        fontFamily: 'var(--font-display)',
                        color: isLeading ? 'var(--accent)' : 'var(--text-primary)',
                      }}
                    >
                      {pct}&cent;
                    </span>
                  </div>
                  <div
                    className="h-2 w-full rounded-full overflow-hidden"
                    style={{ background: 'var(--surface-2)' }}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{
                        width: `${pct}%`,
                        background: isLeading
                          ? 'linear-gradient(90deg, var(--accent), #00e87b)'
                          : 'var(--text-muted)',
                        opacity: isLeading ? 1 : 0.35,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* Price Chart */}
      {priceHistory && priceHistory.history?.length > 1 && (
        <div className="mb-6">
          <PriceChart
            history={priceHistory.history}
            outcome={priceHistory.outcome}
            alerts={alerts}
            conditionId={conditionId}
          />
        </div>
      )}

      {/* Market Stats */}
      <div className="mb-6">
        <MarketStats
          volume24h={live?.volume_24h}
          liquidity={live?.liquidity}
          spread={live?.spread}
          alerts={alerts}
        />
      </div>

      {/* Two-column: Notable Trades + Holders/Pulse */}
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Left: Notable Trades */}
        <section>
          {alerts.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2
                className="text-xs font-semibold uppercase tracking-widest"
                style={{
                  fontFamily: 'var(--font-display)',
                  color: 'var(--text-muted)',
                  fontSize: '0.6rem',
                }}
              >
                Notable Trades
              </h2>
              {alerts.map((alert) => (
                <AlertRow
                  key={alert.id}
                  alert={alert}
                  autoExpand
                  activeTag=""
                  onTagClick={() => {}}
                  liveMarket={live}
                />
              ))}
            </div>
          ) : (
            <div
              className="rounded-xl border p-12 text-center"
              style={{
                borderColor: 'var(--border)',
                background: 'var(--surface-card)',
                color: 'var(--text-muted)',
              }}
            >
              No signals found for this market.
            </div>
          )}
        </section>

        {/* Right: Holders + Pulse */}
        {(holders?.length > 0 || alerts.length > 0) && (
          <aside>
            <HoldersLeaderboard holders={holders} />
            <MarketPulse alerts={alerts} volume24h={live?.volume_24h} />
          </aside>
        )}
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
