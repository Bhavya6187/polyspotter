import { useEffect, useState } from "react";
import { fetchAlertDetail } from "../api";

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

  return (
    <div className="px-4 pb-4 pt-1">
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

      {/* Copy Trade CTA */}
      {ctaText && marketUrl && (
        <div className="mt-4">
          <a
            href={marketUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 transition-colors hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
          >
            Copy this trade &rarr; {ctaText}
          </a>
        </div>
      )}
    </div>
  );
}
