"use client";

import { useState } from "react";
import Link from "next/link";
import AlertRow from "../../../components/AlertRow";
import PriceMovement from "../../../components/PriceMovement";
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

export default function MarketPageClient({ conditionId, initialLive, initialAlerts }) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];

  // Outcomes from live data
  const outcomes = live?.outcomes || [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      {/* Nav */}
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to all markets
        </Link>
        <ThemeToggle />
      </div>

      {/* Market header */}
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50 leading-snug">
          {title}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-500 dark:text-gray-400">
          {resolution && (
            <span
              className={
                resolution === "Resolved"
                  ? "text-gray-400 dark:text-gray-600"
                  : endDate && new Date(endDate).getTime() - Date.now() < 3600000
                    ? "font-medium text-red-500 dark:text-red-400"
                    : endDate && new Date(endDate).getTime() - Date.now() < 86400000
                      ? "text-amber-600 dark:text-amber-400"
                      : ""
              }
            >
              Resolves in {resolution}
            </span>
          )}
          {totalUsd > 0 && (
            <span>{usdFmt.format(totalUsd)} in notable trades</span>
          )}
          <span>
            {alerts.length} alert{alerts.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Tags */}
        {tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {tags.map((t) => (
              <span
                key={t}
                className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-400"
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </header>

      {/* Live outcomes */}
      {outcomes.length > 0 && (
        <div className="mb-6 grid gap-3 sm:grid-cols-2">
          {outcomes.map((o) => (
            <div
              key={o.name}
              className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {o.name}
                </span>
                <span className="text-lg font-bold text-gray-900 dark:text-gray-50">
                  {Math.round((o.price || 0) * 100)}&cent;
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Alerts */}
      {alerts.length > 0 ? (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
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
        <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
          No alerts found for this market.
        </div>
      )}
    </div>
  );
}
