"use client";
import { useEffect, useRef, useState } from "react";
import { fetchTickerRecent } from "../lib/api";

export function useLiveTicker({ interval = 5000, limit = 20 } = {}) {
  const [trades, setTrades] = useState([]);
  const seen = useRef(new Set());

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const d = await fetchTickerRecent(limit);
        if (!alive) return;
        const incoming = d.trades || [];
        const next = [];
        for (const t of incoming) {
          if (!seen.current.has(t.id)) {
            seen.current.add(t.id);
            next.push(t);
          }
        }
        if (next.length) setTrades((curr) => [...next, ...curr].slice(0, limit));
      } catch {}
    }
    tick();
    const id = setInterval(tick, interval);
    return () => { alive = false; clearInterval(id); };
  }, [interval, limit]);

  return trades;
}
