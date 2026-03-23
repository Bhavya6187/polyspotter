import { useEffect, useState } from "react";
import { fetchAlertDetail } from "../lib/api";
import PriceMovement from "./PriceMovement";

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
  const now = Date.now();
  const end = new Date(dateStr).getTime();
  const diffMs = end - now;
  if (diffMs <= 0) return "Resolved";
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

export default function AlertRow({ alert, autoExpand, activeTag, onTagClick, compact, liveMarket }) {
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const tags = alert.tags || [];
  const copyAction = alert.llm_copy_action;

  // Find the live price for the outcome this alert is about
  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;
  const liveOutcome = liveMarket?.outcomes?.find(
    (o) => o.name === alertOutcome
  );
  const currentPrice = liveOutcome?.price ?? null;
  const resolution = timeToResolution(alert.end_date);

  // Auto-fetch detail when rendered in compact (expanded market) mode
  useEffect(() => {
    if (!autoExpand) return;
    let cancelled = false;
    setLoadingDetail(true);
    fetchAlertDetail(alert.id).then((data) => {
      if (!cancelled) {
        setDetail(data);
        setLoadingDetail(false);
      }
    }).catch(() => {
      if (!cancelled) setLoadingDetail(false);
    });
    return () => { cancelled = true; };
  }, [alert.id, autoExpand]);

  // Build the bet summary line from copy_action or fallback to raw data
  let betSummary = "";
  if (copyAction && copyAction.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    betSummary = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  } else {
    betSummary = `${usdFmt.format(alert.total_usd)}`;
  }

  // Build a compact label: LLM headline > cluster headline > bettor profile > fallback
  let compactLabel = null;
  if (alert.llm_headline) {
    compactLabel = alert.llm_headline;
  } else if (alert.cluster_headline) {
    compactLabel = alert.cluster_headline;
  } else if (alert.win_rate != null) {
    const wr = `${Math.round(alert.win_rate * 100)}% wins`;
    const pnl = alert.total_pnl != null
      ? ` · ${alert.total_pnl >= 0 ? "+" : ""}${usdFmt.format(alert.total_pnl)}`
      : "";
    compactLabel = `Wallet with ${wr}${pnl}`;
  }

  // CTA from detail or from alert-level copy action
  const detailCopyAction = detail?.llm_copy_action || copyAction;
  const marketUrl = detail?.market_url;
  let ctaText = "";
  if (detailCopyAction && detailCopyAction.outcome) {
    const side = detailCopyAction.side === "SELL" ? "Sell" : "Buy";
    ctaText = `${side} ${detailCopyAction.outcome}`;
  }

  // Bullets from detail
  const bullets = detail?.llm_bullets || [];
  const displayBullets =
    bullets.length > 0 ? bullets : detail?.llm_summary ? [detail.llm_summary] : [];

  return (
    <div
      className={`rounded-lg border bg-white transition-all dark:bg-gray-900 ${
        compact ? "p-3" : "p-4"
      } border-gray-200 dark:border-gray-800`}
    >
      {/* Row 1: Market title (full mode) or wallet (compact mode) + resolution */}
      <div className="flex items-start justify-between gap-3">
        {compact ? (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {compactLabel ?? "\u2014"}
          </span>
        ) : (
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug">
            {alert.market_title ?? "\u2014"}
          </h3>
        )}
        <div className="flex shrink-0 items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
          {!compact && resolution && (
            <span
              className={
                resolution === "Resolved"
                  ? "text-gray-400 dark:text-gray-600"
                  : new Date(alert.end_date).getTime() - Date.now() < 3600000
                    ? "font-medium text-red-500 dark:text-red-400"
                    : new Date(alert.end_date).getTime() - Date.now() < 86400000
                      ? "text-amber-600 dark:text-amber-400"
                      : ""
              }
            >
              {resolution}
            </span>
          )}
          <span>{relativeTime(alert.scanned_at)}</span>
        </div>
      </div>

      {/* Row 2: Bet summary + live price */}
      <div className={`mt-1 flex items-center gap-2 ${compact ? "" : ""}`}>
        <p className={`text-sm text-gray-600 dark:text-gray-300 ${compact ? "text-xs" : ""}`}>
          {betSummary}
        </p>
        {alertPrice > 0 && currentPrice > 0 && (
          <PriceMovement
            alertPrice={alertPrice}
            currentPrice={currentPrice}
            outcome={alertOutcome}
            compact
          />
        )}
      </div>

      {/* Inline detail: bullets + CTA (auto-expanded in compact mode) */}
      {autoExpand && (
        <div className="mt-2">
          {loadingDetail ? (
            <p className="text-xs text-gray-400 dark:text-gray-500">Loading...</p>
          ) : (
            <>
              {displayBullets.length > 0 && (
                <ul className="space-y-1 mt-1">
                  {displayBullets.map((bullet, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500 dark:bg-blue-400" />
                      <span>{bullet}</span>
                    </li>
                  ))}
                </ul>
              )}
              {ctaText && marketUrl && (
                <div className="mt-3 flex items-center gap-3">
                  <a
                    href={marketUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-blue-600 bg-blue-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 dark:border-blue-500 dark:bg-blue-600 dark:hover:bg-blue-700"
                  >
                    Copy this trade &rarr; {ctaText}
                  </a>
                  {currentPrice > 0 && currentPrice < 0.99 && (
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Pay {Math.round(currentPrice * 100)}&cent; &rarr; win $1.00
                      <span className="ml-1 text-green-600 dark:text-green-400">
                        ({Math.round(((1 - currentPrice) / currentPrice) * 100)}% return)
                      </span>
                    </span>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Row 3: Tags (only in full mode) */}
      {!compact && tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tags.map((t) => (
            <span
              key={t}
              role="button"
              onClick={(e) => {
                e.stopPropagation();
                onTagClick(t);
              }}
              className={`inline-block cursor-pointer rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                activeTag === t
                  ? "bg-blue-600 text-blue-50 dark:bg-blue-700 dark:text-blue-100"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
              }`}
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
