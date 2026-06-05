import { useEffect, useState, useRef } from "react";
import { fetchMarketLive } from "../lib/api";

const POLL_INTERVAL = 30_000; // 30 seconds

/**
 * Fetch and poll live market data for a condition_id.
 * Returns { data, loading, error } where data is the LiveMarketData shape.
 * Only fetches when enabled=true (default).
 */
export default function useLiveMarket(conditionId, { enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!conditionId || !enabled) return;

    let cancelled = false;
    let loaded = false; // first fetch for this conditionId shows loading; polls don't

    const load = () => {
      if (!loaded) setLoading(true);
      fetchMarketLive(conditionId)
        .then((result) => {
          if (!cancelled) {
            loaded = true;
            setData(result);
            setError(null);
            setLoading(false);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err);
            setLoading(false);
          }
        });
    };

    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL);

    return () => {
      cancelled = true;
      clearInterval(intervalRef.current);
    };
  }, [conditionId, enabled]);

  return { data, loading, error };
}
