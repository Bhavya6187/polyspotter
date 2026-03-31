import { useEffect, useState, useRef, useCallback } from "react";
import { fetchBasketballData } from "../lib/api";

const POLL_INTERVALS = {
  pre: 60_000,
  live: 15_000,
  final: null,
};

export default function useBasketballData(conditionId, { initialData = null } = {}) {
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  const retryDelay = useRef(15_000);

  const clearPoll = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!conditionId) return;

    let cancelled = false;

    const load = async () => {
      try {
        const result = await fetchBasketballData(conditionId);
        if (cancelled) return;

        setData(result);
        setError(null);
        setLoading(false);
        retryDelay.current = 15_000;

        const status = result?.status;
        const interval = POLL_INTERVALS[status] ?? POLL_INTERVALS.pre;

        clearPoll();
        if (interval !== null) {
          intervalRef.current = setInterval(load, interval);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err);
        setLoading(false);

        clearPoll();
        const nextDelay = Math.min(retryDelay.current * 2, 60_000);
        retryDelay.current = nextDelay;
        intervalRef.current = setInterval(load, nextDelay);
      }
    };

    load();

    return () => {
      cancelled = true;
      clearPoll();
    };
  }, [conditionId, clearPoll]);

  return { data, loading, error };
}
