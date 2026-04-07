import { marketSlug } from "../lib/slugify";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export default async function sitemap() {
  const staticPages = [
    {
      url: SITE_URL,
      lastModified: new Date(),
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
      lastModified: market.scanned_at ? new Date(market.scanned_at) : new Date(),
      changeFrequency: "hourly",
      priority: 0.8,
    }));

    // Fetch tags for tag pages
    let tagPages = [];
    try {
      const tagsRes = await fetch(`${API_URL}/api/tags`, { cache: "no-store" });
      if (tagsRes.ok) {
        const tagsData = await tagsRes.json();
        const tags = tagsData?.tags || tagsData || [];
        tagPages = tags.map((t) => {
          const tag = typeof t === "string" ? t : t.tag;
          const slug = tag.toLowerCase().replace(/\s+/g, "-");
          return {
            url: `${SITE_URL}/tag/${encodeURIComponent(slug)}`,
            lastModified: new Date(),
            changeFrequency: "daily",
            priority: 0.7,
          };
        });
      }
    } catch {}

    // Fetch theses for thesis pages
    let thesisPages = [];
    try {
      let allTheses = [];
      let thesisPage = 1;
      let thesisTotalPages = 1;

      while (thesisPage <= thesisTotalPages) {
        const thesesRes = await fetch(
          `${API_URL}/api/theses?per_page=100&page=${thesisPage}`,
          { cache: "no-store" }
        );
        if (!thesesRes.ok) break;
        const data = await thesesRes.json();
        const theses = data?.theses || data || [];
        allTheses.push(...theses);
        const thesisTotal = data?.total || 0;
        thesisTotalPages = Math.ceil(thesisTotal / 100);
        thesisPage++;
      }

      thesisPages = allTheses
        .filter((t) => t.markets?.length > 0)
        .map((t) => ({
          url: `${SITE_URL}/thesis/${t.id}`,
          lastModified: new Date(),
          changeFrequency: "daily",
          priority: 0.7,
        }));
    } catch {}

    // Fetch top wallets for wallet pages
    let walletPages = [];
    try {
      const walletsRes = await fetch(
        `${API_URL}/api/wallets/top?limit=50`,
        { cache: "no-store" }
      );
      if (walletsRes.ok) {
        const walletsData = await walletsRes.json();
        const wallets = walletsData?.wallets || walletsData || [];
        walletPages = wallets.map((w) => {
          const address = typeof w === "string" ? w : w.wallet;
          return {
            url: `${SITE_URL}/wallet/${address.toLowerCase()}`,
            lastModified: new Date(),
            changeFrequency: "daily",
            priority: 0.6,
          };
        });
      }
    } catch {}

    return [...staticPages, ...marketPages, ...tagPages, ...thesisPages, ...walletPages];
  } catch {
    return staticPages;
  }
}
