"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchMarketAlerts } from "../../../lib/api";
import AlertList from "../../../components/AlertList";
import Pagination from "../../../components/Pagination";

export default function TagPageClient({ initialMarkets, initialTotal, initialTotalAlerts, tag }) {
  const [markets, setMarkets] = useState(initialMarkets);
  const [total, setTotal] = useState(initialTotal);
  const [totalAlerts, setTotalAlerts] = useState(initialTotalAlerts);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [loading, setLoading] = useState(false);

  const pageRef = useRef(page);
  pageRef.current = page;

  const refresh = useCallback(() => {
    setLoading(true);
    fetchMarketAlerts({
      page: pageRef.current,
      perPage,
      tag,
    })
      .then((data) => {
        setMarkets(data.markets || []);
        setTotal(data.total || 0);
        setTotalAlerts(data.total_alerts || 0);
      })
      .catch(() => {
        setMarkets([]);
        setTotal(0);
        setTotalAlerts(0);
      })
      .finally(() => setLoading(false));
  }, [perPage, tag]);

  const [hasInteracted, setHasInteracted] = useState(false);

  useEffect(() => {
    if (!hasInteracted) return;
    refresh();
  }, [page, hasInteracted, refresh]);

  const handlePageChange = useCallback((newPage) => {
    setHasInteracted(true);
    setPage(newPage);
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <>
      <AlertList
        markets={markets}
        filters={{ tag: "", resolvesIn: "" }}
        loading={loading}
      />
      <nav aria-label="Pagination">
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
        />
      </nav>
    </>
  );
}
