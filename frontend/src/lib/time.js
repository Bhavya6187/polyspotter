// Deterministic absolute timestamp ("2026-09-26 14:03 UTC") used as the
// server-safe fallback while useNow() is still null, so SSR and hydration
// render identical text regardless of the viewer's clock or timezone.
export function formatUtc(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

// "5s ago" / "3m ago" / "2h ago" / "4d ago". `now` is null during
// SSR/hydration: fall back to the absolute UTC stamp so server and client
// markup match.
export function relativeTime(dateStr, now) {
  if (!dateStr) return "—";
  if (now == null) return formatUtc(dateStr);
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}
