// Child market sitemap: /sitemap-markets-<n>.xml (rewritten to
// /sitemap-markets/<n> in next.config.js). Child n covers markets
// [(n-1)*MARKETS_PER_SITEMAP, n*MARKETS_PER_SITEMAP) of the backend's
// /api/markets/sitemap listing (ordered by recency), fetched in
// UPSTREAM_PER_PAGE slices.
//
// ISR-cached for an hour. A failed upstream page throws rather than emitting
// a truncated <urlset>, so Next keeps serving the previous version.

import { marketSlug } from "../../../lib/slugify";
import { API_URL } from "../../../lib/apiBase";
import { MARKETS_PER_SITEMAP, escapeXml } from "../../../lib/sitemap";

export const revalidate = 3600;

// No children are prerendered at build; each is generated on first request
// and then cached (ISR) for `revalidate` seconds.
export async function generateStaticParams() {
  return [];
}

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

// Backend caps per_page at 5000; 5000 rows is ~1.2MB of JSON, under Next's
// 2MB data-cache item limit. MARKETS_PER_SITEMAP must be a multiple of it.
const UPSTREAM_PER_PAGE = 5000;
const PAGES_PER_CHILD = MARKETS_PER_SITEMAP / UPSTREAM_PER_PAGE;

async function fetchChildMarkets(n) {
  const all = [];
  const firstPage = (n - 1) * PAGES_PER_CHILD + 1;
  for (let page = firstPage; page < firstPage + PAGES_PER_CHILD; page++) {
    const res = await fetch(
      `${API_URL}/api/markets/sitemap?page=${page}&per_page=${UPSTREAM_PER_PAGE}`,
      { next: { revalidate: 3600 } }
    );
    if (!res.ok) throw new Error(`markets sitemap page ${page}: HTTP ${res.status}`);
    const data = await res.json();
    const markets = data?.markets || [];
    all.push(...markets);
    if (markets.length < UPSTREAM_PER_PAGE) break; // last upstream page
  }
  return all;
}

function notFoundResponse() {
  return new Response("Not Found", {
    status: 404,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

export async function GET(_request, { params }) {
  const { n: raw } = await params;
  if (!/^[1-9]\d*$/.test(raw)) return notFoundResponse();
  const n = Number(raw);

  const markets = await fetchChildMarkets(n);
  // Child 1 always exists (the index lists it even with zero markets);
  // higher children beyond the data are 404s.
  if (n > 1 && markets.length === 0) return notFoundResponse();

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
