import { Fragment } from "react";
import AlertRow from "./AlertRow";
import AlertDetail from "./AlertDetail";

const SORTABLE_COLUMNS = [
  { key: "composite_score", label: "Score" },
  { key: null, label: "Tags" },
  { key: null, label: "Market" },
  { key: "total_usd", label: "USD" },
  { key: "trade_count", label: "Trades" },
  { key: "end_date", label: "Resolution" },
  { key: "scanned_at", label: "Time" },
];

function SortIcon({ active, dir }) {
  if (!active) {
    return <span className="ml-1 text-gray-400 dark:text-gray-600">↕</span>;
  }
  return (
    <span className="ml-1">
      {dir === "asc" ? "↑" : "↓"}
    </span>
  );
}

export default function AlertTable({
  alerts,
  expandedAlertId,
  onToggleAlert,
  onFilterChange,
  filters,
  loading,
  sort,
  onSort,
}) {
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

  return (
    <div className="overflow-x-auto rounded-lg">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="sticky top-0 z-10 border-b border-gray-200 bg-white text-xs uppercase tracking-wider text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-500">
            {SORTABLE_COLUMNS.map((col) => (
              <th
                key={col.label}
                className={`px-4 py-3 ${col.key ? "cursor-pointer select-none hover:text-gray-600 dark:hover:text-gray-300" : ""}`}
                onClick={col.key ? () => onSort(col.key) : undefined}
              >
                {col.label}
                {col.key && <SortIcon active={sort.key === col.key} dir={sort.dir} />}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => {
            const id = alert.id;
            const isExpanded = expandedAlertId === id;
            return (
              <Fragment key={id}>
                <AlertRow
                  alert={alert}
                  onToggle={() => onToggleAlert(id)}
                  activeTag={filters.tag}
                  onTagClick={(t) =>
                    onFilterChange({
                      ...filters,
                      tag: filters.tag === t ? "" : t,
                    })
                  }
                />
                {isExpanded && (
                  <AlertDetail alertId={id} wallet={alert.wallet} alertType={alert.alert_type} />
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
