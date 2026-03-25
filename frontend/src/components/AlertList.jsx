import { useState, useEffect } from "react";
import Link from "next/link";
import { fetchAlertDetail, fetchMarketLive } from "../lib/api";
import { marketSlug } from "../lib/slugify";
import PriceMovement from "./PriceMovement";
import StrengthMeter from "./StrengthMeter";

function relativeTime(dateStr) {
  if (!dateStr) return "\u2014";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return null;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d`;
}

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function priceToCents(price) {
  if (price == null || price <= 0) return null;
  return `${Math.round(price * 100)}\u00a2`;
}

function AlertItem({ alert, filters, liveData }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const copyAction = alert.llm_copy_action;
  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;

  // Fetch detail when expanded
  useEffect(() => {
    if (!expanded || detail) return;
    let cancelled = false;
    setLoadingDetail(true);
    fetchAlertDetail(alert.id)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoadingDetail(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => { cancelled = true; };
  }, [expanded, alert.id, detail]);

  // Live price from parent-level cache
  const liveMarket = liveData[alert.condition_id];
  const liveOutcome = liveMarket?.outcomes?.find((o) => o.name === alertOutcome);
  const currentPrice = liveOutcome?.price ?? null;

  // Build subtitle from llm_headline / cluster_headline / wallet profile
  let subtitle = alert.llm_headline || alert.cluster_headline;
  if (!subtitle && alert.win_rate != null) {
    const wr = `${Math.round(alert.win_rate * 100)}% wins`;
    const pnl = alert.total_pnl != null
      ? ` \u00b7 ${alert.total_pnl >= 0 ? "+" : ""}${usdFmt.format(alert.total_pnl)}`
      : "";
    subtitle = `Wallet with ${wr}${pnl}`;
  }

  // Bet summary
  let betSummary = usdFmt.format(alert.total_usd);
  if (copyAction?.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    betSummary = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  }

  // Resolution
  const resolution = timeToResolution(alert.end_date);
  const resolutionMs = alert.end_date ? new Date(alert.end_date).getTime() - Date.now() : null;
  const resColor =
    resolutionMs != null && resolutionMs < 3600000
      ? "text-red-500 dark:text-red-400 font-medium"
      : resolutionMs != null && resolutionMs < 86400000
        ? "text-amber-600 dark:text-amber-400"
        : "text-gray-500 dark:text-gray-400";

  // CTA
  const detailCopyAction = detail?.llm_copy_action || copyAction;
  const marketUrl = alert.market_url || detail?.market_url;
  let ctaLabel = "";
  if (detailCopyAction?.outcome) {
    const side = detailCopyAction.side === "SELL" ? "Sell" : "Buy";
    ctaLabel = `${side} ${detailCopyAction.outcome}`;
  }

  // Bullets
  const bullets = detail?.llm_bullets || [];
  const displayBullets = bullets.length > 0 ? bullets : detail?.llm_summary ? [detail.llm_summary] : [];

  // Tags
  const tags = alert.tags || [];

  return (
    <div
      className={`rounded-lg border bg-white transition-all dark:bg-gray-950 ${
        expanded
          ? "border-blue-200 dark:border-blue-900/50 shadow-sm"
          : "border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700"
      }`}
    >
      {/* Collapsed row — always visible */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-start gap-3"
      >
        {/* Expand chevron */}
        <svg
          className={`mt-0.5 h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500 transition-transform duration-200 ${
            expanded ? "rotate-90" : ""
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Row 1: market title + strength + time */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <StrengthMeter maxScore={alert.composite_score} />
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug truncate">
                {alert.market_title ?? "\u2014"}
              </span>
            </div>
            <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500" suppressHydrationWarning>
              {relativeTime(alert.created_at)}
            </span>
          </div>

          {/* Row 2: subtitle + bet summary + price movement + resolution */}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
            {subtitle && (
              <span className="text-gray-600 dark:text-gray-300">{subtitle}</span>
            )}
            <span className="font-medium text-gray-700 dark:text-gray-300">{betSummary}</span>
            {alertPrice > 0 && currentPrice > 0 && (
              <PriceMovement alertPrice={alertPrice} currentPrice={currentPrice} outcome={alertOutcome} compact />
            )}
            {resolution && (
              <span className={resColor}>resolves {resolution}</span>
            )}
          </div>
        </div>

        {/* CTA button — visible even when collapsed */}
        {copyAction?.outcome && alert.market_url ? (
          <a
            href={alert.market_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 self-center rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-700"
          >
            {copyAction.side === "SELL" ? "Sell" : "Buy"} {copyAction.outcome}
          </a>
        ) : copyAction?.outcome ? (
          <span className="shrink-0 self-center rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            {copyAction.side === "SELL" ? "Sell" : "Buy"} {copyAction.outcome}
          </span>
        ) : null}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-4 pb-4 pt-3 ml-7">
          {loadingDetail ? (
            <p className="text-xs text-gray-400 dark:text-gray-500">Loading...</p>
          ) : (
            <>
              {/* Bullets */}
              {displayBullets.length > 0 && (
                <ul className="space-y-1.5">
                  {displayBullets.map((bullet, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500 dark:bg-blue-400" />
                      <span>{bullet}</span>
                    </li>
                  ))}
                </ul>
              )}

              {/* Payout estimate */}
              {currentPrice > 0 && currentPrice < 0.99 && (
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  Pay {Math.round(currentPrice * 100)}&cent; &rarr; win $1.00
                  <span className="ml-1 text-green-600 dark:text-green-400">
                    ({Math.round(((1 - currentPrice) / currentPrice) * 100)}% return)
                  </span>
                </p>
              )}

              {/* Tags */}
              {tags.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {tags.map((t) => (
                    <Link
                      key={t}
                      href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}
                      onClick={(e) => e.stopPropagation()}
                      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
                    >
                      {t}
                    </Link>
                  ))}
                </div>
              )}

              {/* View market link */}
              <div className="mt-3 flex items-center gap-3">
                {ctaLabel && marketUrl && (
                  <a
                    href={marketUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-700"
                  >
                    {ctaLabel}
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                )}
                <Link
                  href={`/market/${marketSlug(alert.market_title, alert.condition_id)}`}
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
                >
                  View this market
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </Link>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function AlertList({ alerts, filters, loading }) {
  const [liveData, setLiveData] = useState({}); // condition_id -> LiveMarketData

  // Fetch live prices for all visible markets after initial render
  useEffect(() => {
    if (!alerts || alerts.length === 0) return;

    // Dedupe condition_ids
    const cids = [...new Set(alerts.map((a) => a.condition_id).filter(Boolean))];
    if (cids.length === 0) return;

    let cancelled = false;

    // Small delay so the page renders first, then fetch prices in background
    const timer = setTimeout(() => {
      cids.forEach((cid) => {
        fetchMarketLive(cid)
          .then((data) => {
            if (!cancelled) {
              setLiveData((prev) => ({ ...prev, [cid]: data }));
            }
          })
          .catch(() => {});
      });
    }, 100);

    return () => { cancelled = true; clearTimeout(timer); };
  }, [alerts]);

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        Loading alerts...
      </div>
    );
  }

  if (!alerts || alerts.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        No alerts found.
      </div>
    );
  }

  // Client-side resolve window filter
  const resolvesInMs = {
    "1h": 3600000,
    "24h": 86400000,
    "7d": 604800000,
  }[filters.resolvesIn] || null;

  const filtered = resolvesInMs
    ? alerts.filter((a) => {
        if (!a.end_date) return false;
        const ms = new Date(a.end_date).getTime() - Date.now();
        return ms > 0 && ms <= resolvesInMs;
      })
    : alerts;

  if (filtered.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        No alerts match the current filters.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {filtered.map((alert) => (
        <AlertItem key={alert.id} alert={alert} filters={filters} liveData={liveData} />
      ))}
    </div>
  );
}
