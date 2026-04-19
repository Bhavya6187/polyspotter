const KEY = "polyspotter.watchlist.v1";

export function readWatchlist() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

export function writeWatchlist(ids) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(KEY, JSON.stringify(ids.slice(0, 200))); } catch {}
  window.dispatchEvent(new CustomEvent("polyspotter.watchlist.change", { detail: ids }));
}

export function addToWatchlist(id) {
  const list = readWatchlist();
  if (list.includes(id)) return list;
  const next = [id, ...list];
  writeWatchlist(next);
  return next;
}

export function removeFromWatchlist(id) {
  const next = readWatchlist().filter((x) => x !== id);
  writeWatchlist(next);
  return next;
}

export function toggleWatchlist(id) {
  return readWatchlist().includes(id) ? removeFromWatchlist(id) : addToWatchlist(id);
}
