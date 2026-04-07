"use client";
import { useSyncExternalStore } from "react";

const queries = new Map();

function getOrCreateQuery(query) {
  if (queries.has(query)) return queries.get(query);
  const mql = window.matchMedia(query);
  let listeners = new Set();
  const handler = () => listeners.forEach((l) => l());
  mql.addEventListener("change", handler);
  const store = {
    subscribe(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    getSnapshot() {
      return mql.matches;
    },
  };
  queries.set(query, store);
  return store;
}

export function useMediaQuery(query) {
  const store = typeof window !== "undefined" ? getOrCreateQuery(query) : null;
  return useSyncExternalStore(
    store ? store.subscribe : () => () => {},
    store ? store.getSnapshot : () => false,
    () => false
  );
}
