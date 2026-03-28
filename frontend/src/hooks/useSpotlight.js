"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchSpotlight } from "../lib/api";

export function useSpotlight() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const result = await fetchSpotlight();
      setData(result);
    } catch {
      // silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}
