"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { fetchAlerts } from "../../../lib/api";
import AlertList from "../../../components/AlertList";
import Pagination from "../../../components/Pagination";

export default function TagPageClient({ initialAlerts, initialTotal, tag }) {
  const [alerts, setAlerts] = useState(initialAlerts);
  const [total, setTotal] = useState(initialTotal);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [loading, setLoading] = useState(false);

  const pageRef = useRef(page);
  pageRef.current = page;

  const refresh = useCallback(() => {
    setLoading(true);
    fetchAlerts({
      page: pageRef.current,
      perPage,
      tag,
    })
      .then((data) => {
        setAlerts(data.alerts || []);
        setTotal(data.total || 0);
      })
      .catch(() => {
        setAlerts([]);
        setTotal(0);
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
        alerts={alerts}
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
