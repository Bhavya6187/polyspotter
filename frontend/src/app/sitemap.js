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
    const res = await fetch(`${API_URL}/api/alerts/by-market?per_page=1000`, {
      cache: "no-store",
    });

    if (!res.ok) return staticPages;

    const data = await res.json();
    const markets = data.markets || [];

    const marketPages = markets.map((market) => ({
      url: `${SITE_URL}/market/${market.condition_id}`,
      changeFrequency: "hourly",
      priority: 0.8,
    }));

    return [...staticPages, ...marketPages];
  } catch {
    return staticPages;
  }
}
