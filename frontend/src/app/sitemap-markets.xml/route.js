// Sitemap INDEX for market pages. Markets are the largest section (~50k URLs
// and growing, right at the 50k-per-sitemap limit), so this route lists
// /sitemap-markets-<n>.xml children of at most MARKETS_PER_SITEMAP URLs each.
// The children are served by src/app/sitemap-markets/[n]/route.js via the
// rewrite in next.config.js.
//
// One cheap count call (per_page=1 returns `total`) per regeneration, cached
// as ISR for an hour. If the count call fails at runtime we throw, so Next
// keeps serving the previous index; during `next build` we fall back to a
// single child so the build never depends on the backend being up.

import { API_URL } from "../../lib/apiBase";
import { MARKETS_PER_SITEMAP, chunkCount, escapeXml } from "../../lib/sitemap";

export const revalidate = 3600;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
const isBuildPhase = process.env.NEXT_PHASE === "phase-production-build";

async function fetchMarketTotal() {
  const res = await fetch(`${API_URL}/api/markets/sitemap?page=1&per_page=1`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) throw new Error(`markets sitemap count: HTTP ${res.status}`);
  const data = await res.json();
  if (typeof data?.total !== "number") throw new Error("markets sitemap count: no total");
  return data.total;
}

export async function GET() {
  let total;
  try {
    total = await fetchMarketTotal();
  } catch (err) {
    if (!isBuildPhase) throw err;
    total = 0; // one child; corrected on the first hourly revalidation
  }

  const lastmod = new Date().toISOString().slice(0, 10);
  const children = Array.from(
    { length: chunkCount(total, MARKETS_PER_SITEMAP) },
    (_, i) => `<sitemap><loc>${escapeXml(SITE_URL)}/sitemap-markets-${i + 1}.xml</loc><lastmod>${lastmod}</lastmod></sitemap>`
  ).join("");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${children}</sitemapindex>`;

  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
