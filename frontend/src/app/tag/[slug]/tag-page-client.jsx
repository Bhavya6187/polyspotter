"use client";

import { useState, useCallback } from "react";
import AlertTable from "../../../components/AlertTable";

export default function TagPageClient({ markets }) {
  const [expandedMarketIds, setExpandedMarketIds] = useState(new Set());
  const [filters] = useState({ tag: "", resolvesIn: "" });

  const handleToggleMarket = useCallback((conditionId) => {
    setExpandedMarketIds((prev) => {
      const next = new Set(prev);
      if (next.has(conditionId)) next.delete(conditionId);
      else next.add(conditionId);
      return next;
    });
  }, []);

  return (
    <AlertTable
      markets={markets}
      expandedMarketIds={expandedMarketIds}
      onToggleMarket={handleToggleMarket}
      onFilterChange={() => {}}
      filters={filters}
      loading={false}
    />
  );
}
