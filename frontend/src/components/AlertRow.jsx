import ScoreBadge from "./ScoreBadge";

function truncateAddress(addr) {
  if (!addr) return "\u2014";
  if (addr.length <= 12) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

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

export default function AlertRow({ alert, isExpanded, onToggle, activeCategory, onCategoryClick }) {
  const isCluster = alert.alert_type === "cluster";

  return (
    <tr
      onClick={onToggle}
      className="cursor-pointer border-b border-gray-800 bg-gray-900 hover:bg-gray-800"
    >
      <td className="px-4 py-3">
        <ScoreBadge score={alert.composite_score ?? 0} />
      </td>
      <td className="px-4 py-3">
        <span
          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
            isCluster
              ? "bg-purple-900 text-purple-300"
              : "bg-blue-900 text-blue-300"
          }`}
        >
          {alert.alert_type ?? "composite"}
        </span>
      </td>
      <td className="px-4 py-3">
        {alert.category ? (
          <span
            role="button"
            onClick={(e) => {
              e.stopPropagation();
              onCategoryClick(alert.category);
            }}
            className={`inline-block cursor-pointer rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
              activeCategory === alert.category
                ? "bg-blue-700 text-blue-100"
                : "bg-gray-700 text-gray-300 hover:bg-gray-600"
            }`}
          >
            {alert.category}
          </span>
        ) : (
          <span className="text-gray-600">&mdash;</span>
        )}
      </td>
      <td className="max-w-xs truncate px-4 py-3 text-sm">
        {alert.market_title ?? "\u2014"}
        {isCluster && alert.cluster_headline && (
          <span className="block text-xs text-gray-400 truncate">
            {alert.cluster_headline}
          </span>
        )}
      </td>
      <td className="px-4 py-3 font-mono text-sm">
        {truncateAddress(alert.wallet)}
      </td>
      <td className="px-4 py-3 text-sm">
        {alert.total_usd != null ? usdFmt.format(alert.total_usd) : "\u2014"}
      </td>
      <td className="px-4 py-3 text-sm">{alert.trade_count ?? "\u2014"}</td>
      <td className="px-4 py-3 text-sm text-gray-400">
        {relativeTime(alert.scanned_at)}
      </td>
    </tr>
  );
}
