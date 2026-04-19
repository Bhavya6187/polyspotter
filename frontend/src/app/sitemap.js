import { marketSlug } from "../lib/slugify";

// Regenerate at most hourly — avoids hammering the API on every crawler hit
// while keeping the sitemap fresh enough for Google's typical crawl cadence.
export const revalidate = 3600;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const FETCH_OPTS = { next: { revalidate: 3600 } };

async function getMarketEntries() {
  try {
    const allMarkets = [];
    let page = 1;
    let totalPages = 1;
    while (page <= totalPages) {
      const res = await fetch(
        `${API_URL}/api/alerts/by-market?per_page=100&page=${page}`,
        FETCH_OPTS
      );
      if (!res.ok) break;
      const data = await res.json();
      allMarkets.push(...(data.markets || []));
      const total = data.total || 0;
      totalPages = Math.ceil(total / 100);
      page++;
    }
    return allMarkets.map((market) => ({
      url: `${SITE_URL}/market/${marketSlug(market.market_title, market.condition_id)}`,
      lastModified: market.scanned_at
        ? new Date(market.scanned_at)
        : new Date(),
      changeFrequency: "hourly",
      priority: 0.8,
    }));
  } catch {
    return [];
  }
}

async function getTagEntries() {
  try {
    const res = await fetch(`${API_URL}/api/tags`, FETCH_OPTS);
    if (!res.ok) return [];
    const data = await res.json();
    const tags = data?.tags || data || [];
    return tags.map((t) => {
      const tag = typeof t === "string" ? t : t.tag;
      const slug = tag.toLowerCase().replace(/\s+/g, "-");
      return {
        url: `${SITE_URL}/tag/${encodeURIComponent(slug)}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.7,
      };
    });
  } catch {
    return [];
  }
}

// Theses are intentionally excluded from the sitemap. As of 2026-04-19 the DB
// has ~17k thesis rows but 0 of them have thesis_headline populated, so every
// thesis page renders as the generic "Cross-Market Thesis" title — pure thin/
// duplicate content. Indexing them would dilute site authority. Additionally,
// paginating through all theses (backend caps per_page=50 → 340 sequential
// pages) was causing the /sitemap.xml static-generation step to time out.
//
// When the LLM starts writing thesis_headline values, restore this section
// and filter on `t.thesis_headline && t.markets?.length > 0`.

// Wallets are served from a separate sitemap at /sitemap-wallets.xml.
// They're unbounded in count and updated on a different cadence than content
// pages, so isolating them keeps this main sitemap small and fast.

export default async function sitemap() {
  const staticPages = [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: "hourly",
      priority: 1.0,
    },
  ];

  // Run all sections in parallel. Each section is self-contained with its own
  // try/catch so one failing upstream (e.g. a /api/theses timeout) degrades
  // only that section instead of collapsing the entire sitemap to the homepage.
  const [markets, tags] = await Promise.all([
    getMarketEntries(),
    getTagEntries(),
  ]);

  return [...staticPages, ...markets, ...tags];
}
