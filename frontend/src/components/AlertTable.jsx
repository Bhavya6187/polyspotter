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
    <div className="flex flex-col gap-3">
      {alerts.map((alert) => {
        const id = alert.id;
        const isExpanded = expandedAlertId === id;
        return (
          <div key={id}>
            <AlertRow
              alert={alert}
              isExpanded={isExpanded}
              onToggle={() => onToggleAlert(id)}
              activeTag={filters.tag}
              onTagClick={(t) =>
                onFilterChange({
                  ...filters,
                  tag: filters.tag === t ? "" : t,
                })
              }
            />
            {isExpanded && <AlertDetail alertId={id} />}
          </div>
        );
      })}
    </div>
  );
}
