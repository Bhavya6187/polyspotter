"use client";
import { useEffect, useState, useCallback } from "react";
import { readWatchlist, toggleWatchlist, addToWatchlist, removeFromWatchlist } from "../lib/watchlist";

export function useWatchlist() {
  const [ids, setIds] = useState([]);

  useEffect(() => {
    setIds(readWatchlist());
    const onChange = (e) => setIds(e.detail || readWatchlist());
    const onStorage = (e) => { if (e.key === "polyspotter.watchlist.v1") setIds(readWatchlist()); };
    window.addEventListener("polyspotter.watchlist.change", onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("polyspotter.watchlist.change", onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const toggle = useCallback((id) => setIds(toggleWatchlist(id)), []);
  const add    = useCallback((id) => setIds(addToWatchlist(id)), []);
  const remove = useCallback((id) => setIds(removeFromWatchlist(id)), []);
  const has    = useCallback((id) => ids.includes(id), [ids]);

  return { ids, has, toggle, add, remove };
}
