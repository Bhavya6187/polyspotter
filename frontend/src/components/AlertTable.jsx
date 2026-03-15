import { Fragment } from "react";
import AlertRow from "./AlertRow";
import AlertDetail from "./AlertDetail";

export default function AlertTable({
  alerts,
  expandedAlertId,
  onToggleAlert,
  onFilterChange,
  filters,
  loading,
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
            <th className="px-4 py-3">Score</th>
            <th className="px-4 py-3">Category</th>
            <th className="px-4 py-3">Market</th>
            <th className="px-4 py-3">USD</th>
            <th className="px-4 py-3">Trades</th>
            <th className="px-4 py-3">Time</th>
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
                  activeCategory={filters.category}
                  onCategoryClick={(cat) =>
                    onFilterChange({
                      ...filters,
                      category: filters.category === cat ? "" : cat,
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
