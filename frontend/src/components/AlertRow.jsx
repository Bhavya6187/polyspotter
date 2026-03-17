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

export default function AlertRow({ alert, isExpanded, onToggle, activeTag, onTagClick, compact }) {
  const tags = alert.tags || [];
  const copyAction = alert.llm_copy_action;
  const resolution = timeToResolution(alert.end_date);

  // Build the bet summary line from copy_action or fallback to raw data
  let betSummary = "";
  if (copyAction && copyAction.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    betSummary = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  } else {
    betSummary = `${usdFmt.format(alert.total_usd)}`;
  }

  const walletShort = alert.wallet
    ? `${alert.wallet.slice(0, 6)}...${alert.wallet.slice(-4)}`
    : null;

  return (
    <div
      onClick={onToggle}
      className={`cursor-pointer rounded-lg border bg-white p-4 transition-all hover:shadow-md dark:bg-gray-900 ${
        isExpanded
          ? "border-blue-300 shadow-md dark:border-blue-700"
          : "border-gray-200 dark:border-gray-800"
      } ${compact ? "p-3" : "p-4"}`}
    >
      {/* Row 1: Market title (full mode) or wallet (compact mode) + resolution */}
      <div className="flex items-start justify-between gap-3">
        {compact ? (
          <span className="text-xs font-mono text-gray-500 dark:text-gray-400">
            {walletShort ?? "\u2014"}
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

      {/* Row 2: Bet summary */}
      <p className={`mt-1 text-sm text-gray-600 dark:text-gray-300 ${compact ? "text-xs" : ""}`}>
        {betSummary}
      </p>

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
