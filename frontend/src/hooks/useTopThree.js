"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchTopThree } from "../lib/api";

const POLL_INTERVAL_MS = 60_000;

export function useTopThree() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const result = await fetchTopThree();
      if (Array.isArray(result)) {
        setData(result);
        setLastUpdated(new Date());
      }
    } catch {
      // silent fail — keep last-good data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, lastUpdated, refresh };
}
