"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSignals } from "../lib/api";

export function useSignalFeed({ topic = "All", minRating, resolvesWithin, limit = 20 } = {}) {
  const [signals, setSignals] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const offsetRef = useRef(0);

  const load = useCallback((reset = false) => {
    setLoading(true);
    const requestOffset = reset ? 0 : offsetRef.current;
    fetchSignals({
      topic: topic === "All" ? undefined : topic,
      limit,
      offset: requestOffset,
      minRating,
      resolvesWithin,
    })
      .then((d) => {
        setSignals((prev) => reset ? d.signals : [...prev, ...d.signals]);
        setTotal(d.total);
        offsetRef.current = requestOffset + d.signals.length;
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [topic, limit, minRating, resolvesWithin]);

  useEffect(() => { load(true); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [topic, minRating, resolvesWithin]);

  return { signals, total, loading, loadMore: () => load(false) };
}
