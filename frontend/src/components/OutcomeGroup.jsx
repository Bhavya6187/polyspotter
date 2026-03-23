import { useEffect, useState } from "react";
import { fetchAlertDetail } from "../api";
import PriceMovement from "./PriceMovement";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/**
 * Renders a consolidated card for all alerts sharing the same outcome direction.
 * Instead of showing 8 separate wallet cards all saying "Buy Yes", this shows
 * one card with aggregated info and the best bullets across all alerts.
 */
export default function OutcomeGroup({ alerts, liveMarket }) {
  const [details, setDetails] = useState({}); // alert.id -> detail
  const [loading, setLoading] = useState(true);

  // Fetch detail for all alerts in this group
  useEffect(() => {
    let cancelled = false;
    const ids = alerts.map((a) => a.id);
    Promise.all(
      ids.map((id) =>
        fetchAlertDetail(id)
          .then((d) => [id, d])
          .catch(() => [id, null])
      )
    ).then((results) => {
      if (cancelled) return;
      const map = {};
      for (const [id, d] of results) {
        if (d) map[id] = d;
      }
      setDetails(map);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [alerts]);

  // Sort alerts by composite_score descending so best signals come first
  const sorted = [...alerts].sort(
    (a, b) => (b.composite_score || 0) - (a.composite_score || 0)
  );

  // Use the top alert's copy action for the CTA
  const topAlert = sorted[0];
  const copyAction = topAlert?.llm_copy_action;
  const outcome = copyAction?.outcome;
  const side = copyAction?.side === "SELL" ? "Sell" : "Buy";
  const ctaText = outcome ? `${side} ${outcome}` : null;

  // Aggregate total USD
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);

  // Find the live price for this outcome
  const liveOutcome = liveMarket?.outcomes?.find((o) => o.name === outcome);
  const currentPrice = liveOutcome?.price ?? null;
  const alertPrice = copyAction?.entry_price;

  // Market URL from any detail
  const marketUrl = Object.values(details)[0]?.market_url;

  // Collect wallet labels for each alert
  const walletLabels = sorted.map((alert) => {
    if (alert.llm_headline) return alert.llm_headline;
    if (alert.cluster_headline) return alert.cluster_headline;
    if (alert.win_rate != null) {
      const wr = `${Math.round(alert.win_rate * 100)}% wins`;
      const pnl =
        alert.total_pnl != null
          ? ` · ${alert.total_pnl >= 0 ? "+" : ""}${usdFmt.format(alert.total_pnl)}`
          : "";
      return `Wallet with ${wr}${pnl}`;
    }
    return null;
  }).filter(Boolean);

  // Collect the best bullets from the top 3 alerts (avoid overwhelming the user)
  const allBullets = [];
  for (const alert of sorted.slice(0, 3)) {
    const detail = details[alert.id];
    const bullets = detail?.llm_bullets || alert.llm_bullets || [];
    // Take up to 2 bullets per alert, pick first ones (most important)
    for (const b of bullets.slice(0, 2)) {
      if (allBullets.length < 4 && !allBullets.includes(b)) {
        allBullets.push(b);
      }
    }
  }

  const priceCents = alertPrice > 0 ? `${Math.round(alertPrice * 100)}\u00a2` : null;

  return (
    <div className="rounded-lg border bg-white p-3 border-gray-200 dark:bg-gray-900 dark:border-gray-800">
      {/* Header: direction + total amount */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {ctaText || "Signal"}
            {priceCents && (
              <span className="ml-1.5 font-normal text-gray-500 dark:text-gray-400">
                at {priceCents}
              </span>
            )}
          </span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {usdFmt.format(totalUsd)} across {alerts.length}{" "}
            {alerts.length === 1 ? "wallet" : "wallets"}
          </span>
        </div>
        {alertPrice > 0 && currentPrice > 0 && (
          <PriceMovement
            alertPrice={alertPrice}
            currentPrice={currentPrice}
            outcome={outcome}
            compact
          />
        )}
      </div>

      {/* Wallet labels */}
      {walletLabels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {walletLabels.slice(0, 5).map((label, i) => (
            <span
              key={i}
              className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400"
            >
              {label}
            </span>
          ))}
          {walletLabels.length > 5 && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              +{walletLabels.length - 5} more
            </span>
          )}
        </div>
      )}

      {/* Bullets */}
      {loading ? (
        <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">Loading...</p>
      ) : (
        allBullets.length > 0 && (
          <ul className="mt-2 space-y-1">
            {allBullets.map((bullet, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300"
              >
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500 dark:bg-blue-400" />
                <span>{bullet}</span>
              </li>
            ))}
          </ul>
        )
      )}

      {/* CTA */}
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
    </div>
  );
}
