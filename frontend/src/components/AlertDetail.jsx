import { useEffect, useState } from "react";
import { fetchAlertDetail } from "../api";
import useLiveMarket from "../hooks/useLiveMarket";
import PriceMovement from "./PriceMovement";

export default function AlertDetail({ alertId }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetchAlertDetail(alertId).then((data) => {
      if (!cancelled) {
        setDetail(data);
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [alertId]);

  const { data: liveMarket } = useLiveMarket(detail?.condition_id, {
    enabled: !!detail?.condition_id,
  });

  if (loading) {
    return (
      <div className="px-4 pb-4 pt-1 text-sm text-gray-400 dark:text-gray-500">
        Loading...
      </div>
    );
  }

  if (!detail) return null;

  const bullets = detail.llm_bullets || [];
  const copyAction = detail.llm_copy_action;
  const marketUrl = detail.market_url;

  // Fallback: if no bullets, show llm_summary as a single bullet
  const displayBullets =
    bullets.length > 0 ? bullets : detail.llm_summary ? [detail.llm_summary] : [];

  // Build copy CTA text
  let ctaText = "";
  if (copyAction && copyAction.outcome) {
    const side = copyAction.side === "SELL" ? "Sell" : "Buy";
    ctaText = `${side} ${copyAction.outcome}`;
  }

  // Find live price for this alert's outcome
  const alertPrice = copyAction?.entry_price;
  const liveOutcome = liveMarket?.outcomes?.find(
    (o) => o.name === copyAction?.outcome
  );
  const currentPrice = liveOutcome?.price ?? null;

  return (
    <div className="px-4 pb-4 pt-1">
      {/* Price movement */}
      {alertPrice > 0 && currentPrice > 0 && (
        <div className="mb-3">
          <PriceMovement
            alertPrice={alertPrice}
            currentPrice={currentPrice}
            outcome={copyAction?.outcome}
          />
        </div>
      )}

      {/* Bullet points */}
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

      {/* Copy Trade CTA with payout */}
      {ctaText && marketUrl && (
        <div className="mt-4 flex items-center gap-3">
          <a
            href={marketUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-blue-600 transition-colors hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/30"
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
