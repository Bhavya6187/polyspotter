import { marketSlug } from "../lib/slugify";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export default async function sitemap() {
  const staticPages = [
    {
      url: SITE_URL,
      changeFrequency: "hourly",
      priority: 1.0,
    },
  ];

  // Fetch all markets to generate dynamic entries
  try {
    let allMarkets = [];
    let page = 1;
    let totalPages = 1;

    while (page <= totalPages) {
      const res = await fetch(
        `${API_URL}/api/alerts/by-market?per_page=100&page=${page}`,
        { cache: "no-store" }
      );

      if (!res.ok) break;

      const data = await res.json();
      const markets = data.markets || [];
      allMarkets.push(...markets);

      const total = data.total || 0;
      totalPages = Math.ceil(total / 100);
      page++;
    }

    const marketPages = allMarkets.map((market) => ({
      url: `${SITE_URL}/market/${marketSlug(market.market_title, market.condition_id)}`,
      changeFrequency: "hourly",
      priority: 0.8,
    }));

    return [...staticPages, ...marketPages];
  } catch {
    return staticPages;
  }
}
