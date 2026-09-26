// Deterministic absolute timestamp ("2026-09-26 14:03 UTC") used as the
// server-safe fallback while useNow() is still null, so SSR and hydration
// render identical text regardless of the viewer's clock or timezone.
export function formatUtc(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
