// Dedicated sitemap for market pages. Separate from the main sitemap because
// markets are the largest section (~19k URLs and growing) — paging them through
// the heavy /api/alerts/by-market endpoint at build time took ~16 minutes and
// timed out the build's static-generation step. Isolating them keeps the main
// sitemap small and prevents one slow upstream from blocking content discovery.
//
// force-dynamic (rather than ISR revalidate) avoids a deploy-race footgun: if
// the frontend ships before the backend's /api/markets/sitemap endpoint exists,
// ISR would bake an empty XML into the static cache and serve it stale until
// revalidation. With force-dynamic the response is recomputed on each request,
// and the explicit Cache-Control below delegates caching to the CDN edge.

import { marketSlug } from "../../lib/slugify";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const PER_PAGE = 1000;
// no-store on the upstream fetch — we don't want a partially-successful prior
// fetch to be replayed from Next's data cache. The CDN caches the final XML.
const FETCH_OPTS = { cache: "no-store" };

function escapeXml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

async function fetchAllMarkets() {
  const all = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages) {
    const res = await fetch(
      `${API_URL}/api/markets/sitemap?page=${page}&per_page=${PER_PAGE}`,
      FETCH_OPTS
    );
    if (!res.ok) break;
    const data = await res.json();
    const markets = data?.markets || [];
    all.push(...markets);
    const total = data?.total || 0;
    totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    page++;
  }

  return all;
}

export async function GET() {
  let markets = [];
  try {
    markets = await fetchAllMarkets();
  } catch {
    markets = [];
  }

  const now = new Date();
  const urls = markets
    .map((m) => {
      const slug = marketSlug(m.market_title, m.condition_id);
      if (!slug) return "";
      const lastmod = (m.scanned_at ? new Date(m.scanned_at) : now).toISOString();
      // Resolved markets change infrequently (outcome is fixed), so give them
      // a lower crawl-budget signal. Open markets still get hourly freshness.
      const isResolved = m.end_date && new Date(m.end_date) <= now;
      const changefreq = isResolved ? "monthly" : "hourly";
      const priority = isResolved ? "0.5" : "0.8";
      return `<url><loc>${escapeXml(SITE_URL)}/market/${escapeXml(slug)}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`;
    })
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`;

  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
