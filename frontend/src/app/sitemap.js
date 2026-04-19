import { marketSlug } from "../lib/slugify";

// Regenerate at most hourly — avoids hammering the API on every crawler hit
// while keeping the sitemap fresh enough for Google's typical crawl cadence.
export const revalidate = 3600;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const FETCH_OPTS = { next: { revalidate: 3600 } };

// Split into a sitemap index. One slow/failing upstream fetch degrades a
// single section instead of collapsing the entire sitemap to the homepage.
export async function generateSitemaps() {
  return [
    { id: "static" },
    { id: "markets" },
    { id: "tags" },
    { id: "theses" },
    { id: "wallets" },
  ];
}

export default async function sitemap({ id }) {
  if (id === "static") {
    return [
      {
        url: SITE_URL,
        lastModified: new Date(),
        changeFrequency: "hourly",
        priority: 1.0,
      },
    ];
  }

  if (id === "markets") {
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
        lastModified: market.scanned_at ? new Date(market.scanned_at) : new Date(),
        changeFrequency: "hourly",
        priority: 0.8,
      }));
    } catch {
      return [];
    }
  }

  if (id === "tags") {
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

  if (id === "theses") {
    try {
      const allTheses = [];
      let page = 1;
      let totalPages = 1;

      while (page <= totalPages) {
        const res = await fetch(
          `${API_URL}/api/theses?per_page=100&page=${page}`,
          FETCH_OPTS
        );
        if (!res.ok) break;
        const data = await res.json();
        allTheses.push(...(data?.theses || data || []));
        const total = data?.total || 0;
        totalPages = Math.ceil(total / 100);
        page++;
      }

      return allTheses
        .filter((t) => t.markets?.length > 0)
        .map((t) => ({
          url: `${SITE_URL}/thesis/${t.id}`,
          lastModified: new Date(),
          changeFrequency: "daily",
          priority: 0.7,
        }));
    } catch {
      return [];
    }
  }

  if (id === "wallets") {
    try {
      const res = await fetch(`${API_URL}/api/wallets/top?limit=50`, FETCH_OPTS);
      if (!res.ok) return [];
      const data = await res.json();
      const wallets = data?.wallets || data || [];
      return wallets.map((w) => {
        const address = typeof w === "string" ? w : w.wallet;
        return {
          url: `${SITE_URL}/wallet/${address.toLowerCase()}`,
          lastModified: new Date(),
          changeFrequency: "daily",
          priority: 0.6,
        };
      });
    } catch {
      return [];
    }
  }

  return [];
}
