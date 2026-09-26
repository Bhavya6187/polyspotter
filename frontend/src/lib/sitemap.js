// Helpers for the split markets sitemap (/sitemap-markets.xml index +
// /sitemap-markets-<n>.xml children).

// Sitemaps cap at 50,000 URLs; 40k leaves headroom for growth between
// hourly regenerations of the index.
export const MARKETS_PER_SITEMAP = 40000;

// Number of child sitemaps needed for `total` URLs. Always at least 1 so the
// index is never empty (an empty child <urlset> is valid).
export function chunkCount(total, size) {
  return Math.max(1, Math.ceil((Number(total) || 0) / size));
}

export function escapeXml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
