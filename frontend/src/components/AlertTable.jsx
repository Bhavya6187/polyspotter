import MarketCard from "./MarketCard";

export default function AlertTable({
  markets,
  expandedMarketId,
  onToggleMarket,
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

  if (!markets || markets.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
        No alerts found.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {markets.map((market) => (
        <MarketCard
          key={market.condition_id}
          market={market}
          isExpanded={expandedMarketId === market.condition_id}
          onToggle={() => onToggleMarket(market.condition_id)}
          activeTag={filters.tag}
          onTagClick={(t) =>
            onFilterChange({
              ...filters,
              tag: filters.tag === t ? "" : t,
            })
          }
        />
      ))}
    </div>
  );
}
