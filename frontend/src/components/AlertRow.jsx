import ScoreBadge from "./ScoreBadge";

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

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export default function AlertRow({ alert, onToggle, activeTag, onTagClick }) {
  const isCluster = alert.alert_type === "cluster";
  const tags = alert.tags || [];

  return (
    <tr
      onClick={onToggle}
      className="cursor-pointer border-b border-gray-100 bg-white hover:bg-gray-50 dark:border-gray-800 dark:bg-gray-900 dark:hover:bg-gray-800"
    >
      <td className="px-4 py-3">
        <ScoreBadge score={alert.composite_score ?? 0} />
      </td>
      <td className="px-4 py-3">
        {tags.length > 0 ? (
          <div className="flex flex-wrap gap-1">
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
                    : "bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
                }`}
              >
                {t}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-gray-300 dark:text-gray-600">&mdash;</span>
        )}
      </td>
      <td className="max-w-xs truncate px-4 py-3 text-sm">
        {alert.market_title ?? "\u2014"}
        {isCluster && alert.cluster_headline && (
          <span className="block truncate text-xs text-gray-500 dark:text-gray-400">
            {alert.cluster_headline}
          </span>
        )}
      </td>
      <td className={`px-4 py-3 text-sm font-medium ${
        alert.total_usd >= 100000
          ? "text-red-500 dark:text-red-400"
          : alert.total_usd >= 25000
            ? "text-amber-600 dark:text-amber-400"
            : "text-gray-900 dark:text-gray-100"
      }`}>
        {alert.total_usd != null ? usdFmt.format(alert.total_usd) : "\u2014"}
      </td>
      <td className="px-4 py-3 text-sm">{alert.trade_count ?? "\u2014"}</td>
      <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
        {relativeTime(alert.scanned_at)}
      </td>
    </tr>
  );
}
