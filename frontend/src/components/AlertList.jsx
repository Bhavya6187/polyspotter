import Link from "next/link";
import { useState, useEffect } from "react";
import { fetchMarketLive } from "../lib/api";
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

/** A single alert entry within a market group — always fully visible, no expand needed. */
function AlertEntry({ alert, liveData }) {
  const copyAction = alert.llm_copy_action;
  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;

  const liveMarket = liveData[alert.condition_id];
  const liveOutcome = liveMarket?.outcomes?.find((o) => o.name === alertOutcome);
  const currentPrice = liveOutcome?.price ?? null;

  // Subtitle from llm_headline / cluster_headline / wallet profile
  let subtitle = alert.llm_headline || alert.cluster_headline;
  if (!subtitle && alert.win_rate != null) {
    const wr = `${Math.round(alert.win_rate * 100)}% wins`;
    const pnl =
      alert.total_pnl != null
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

  // Bullets — available directly from the list endpoint
  const bullets = alert.llm_bullets || [];

  // CTA
  let ctaLabel = "";
  const marketUrl = alert.market_url;
  if (copyAction?.outcome) {
    const side = copyAction.side === "SELL" ? "Sell" : "Buy";
    ctaLabel = `${side} ${copyAction.outcome}`;
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Header row: subtitle + bet summary + price movement + CTA */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
            {subtitle && (
              <span className="text-gray-600 dark:text-gray-300">{subtitle}</span>
            )}
            <span className="font-medium text-gray-700 dark:text-gray-300">{betSummary}</span>
            {alertPrice > 0 && currentPrice > 0 && (
              <PriceMovement alertPrice={alertPrice} currentPrice={currentPrice} outcome={alertOutcome} compact />
            )}
          </div>
        </div>

        {/* CTA button */}
        {ctaLabel && marketUrl ? (
          <a
            href={marketUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-700"
          >
            {ctaLabel}
          </a>
        ) : ctaLabel ? (
          <span className="shrink-0 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            {ctaLabel}
          </span>
        ) : null}
      </div>

      {/* Bullets */}
      {bullets.length > 0 && (
        <ul className="space-y-1.5">
          {bullets.map((bullet, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500 dark:bg-blue-400" />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Payout estimate */}
      {currentPrice > 0 && currentPrice < 0.99 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Pay {Math.round(currentPrice * 100)}&cent; &rarr; win $1.00
          <span className="ml-1 text-green-600 dark:text-green-400">
            ({Math.round(((1 - currentPrice) / currentPrice) * 100)}% return)
          </span>
        </p>
      )}
    </div>
  );
}

/** Pick the best alert: most recent first, highest score as tiebreaker. */
function pickBestAlert(alerts) {
  if (!alerts || alerts.length === 0) return null;
  if (alerts.length === 1) return alerts[0];
  return alerts.reduce((best, a) => {
    const bestTime = best.created_at ? new Date(best.created_at).getTime() : 0;
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    if (aTime > bestTime) return a;
    if (aTime === bestTime && a.composite_score > best.composite_score) return a;
    return best;
  });
}

/** A market group card — shows the single best alert with full details. */
function MarketGroupCard({ market, liveData }) {
  const alert = pickBestAlert(market.alerts);
  if (!alert) return null;
  const tags = market.tags || [];

  const resolution = timeToResolution(market.end_date);
  const resolutionMs = market.end_date ? new Date(market.end_date).getTime() - Date.now() : null;
  const resColor =
    resolutionMs != null && resolutionMs < 3600000
      ? "text-red-500 dark:text-red-400 font-medium"
      : resolutionMs != null && resolutionMs < 86400000
        ? "text-amber-600 dark:text-amber-400"
        : "text-gray-500 dark:text-gray-400";

  const marketUrl = market.market_url || alert.market_url;

  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950">
      {/* Market header */}
      <div className="px-4 py-3 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <StrengthMeter maxScore={alert.composite_score} />
          <Link
            href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
            className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug truncate hover:underline"
          >
            {market.market_title ?? "\u2014"}
          </Link>
          {resolution && (
            <span className={`text-xs ${resColor}`}>resolves {resolution}</span>
          )}
        </div>
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500" suppressHydrationWarning>
          {relativeTime(alert.created_at)}
        </span>
      </div>

      {/* Single best alert */}
      <div className="px-4 pb-4">
        <AlertEntry alert={alert} liveData={liveData} />
      </div>

      {/* Footer: tags + view market */}
      <div className="border-t border-gray-100 dark:border-gray-800 px-4 py-3 flex flex-wrap items-center gap-3">
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <Link
                key={t}
                href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}
                className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
              >
                {t}
              </Link>
            ))}
          </div>
        )}
        {marketUrl && (
          <Link
            href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors ml-auto"
          >
            View this market
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        )}
      </div>
    </div>
  );
}

export default function AlertList({ markets, filters, loading }) {
  const [liveData, setLiveData] = useState({});

  // Fetch live prices for all visible markets
  useEffect(() => {
    if (!markets || markets.length === 0) return;

    const cids = markets.map((m) => m.condition_id).filter(Boolean);
    if (cids.length === 0) return;

    let cancelled = false;

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
  }, [markets]);

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        Loading alerts...
      </div>
    );
  }

  if (!markets || markets.length === 0) {
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

  const afterResolve = resolvesInMs
    ? markets.filter((m) => {
        if (!m.end_date) return false;
        const ms = new Date(m.end_date).getTime() - Date.now();
        return ms > 0 && ms <= resolvesInMs;
      })
    : markets;

  // Sort by the picked alert: newest first, highest score as tiebreaker
  const filtered = [...afterResolve].sort((a, b) => {
    const aAlert = pickBestAlert(a.alerts);
    const bAlert = pickBestAlert(b.alerts);
    const aTime = aAlert?.created_at ? new Date(aAlert.created_at).getTime() : 0;
    const bTime = bAlert?.created_at ? new Date(bAlert.created_at).getTime() : 0;
    if (bTime !== aTime) return bTime - aTime;
    return (bAlert?.composite_score || 0) - (aAlert?.composite_score || 0);
  });

  if (filtered.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        No alerts match the current filters.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {filtered.map((market) => (
        <MarketGroupCard key={market.condition_id} market={market} liveData={liveData} />
      ))}
    </div>
  );
}
