import HomeClient from "./home-client";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getHomeData() {
  try {
    const [marketsRes, tagsRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20`, {
        cache: "no-store",
      }),
      fetch(`${API_URL}/api/tags`, { cache: "no-store" }),
    ]);

    const marketsData = marketsRes.ok ? await marketsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;

    return {
      markets: marketsData?.markets || [],
      total: marketsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
    };
  } catch {
    return { markets: [], total: 0, tags: [] };
  }
}

export default async function HomePage() {
  const { markets, total, tags } = await getHomeData();

  return (
    <HomeClient
      initialMarkets={markets}
      initialTotal={total}
      tags={tags}
    />
  );
}
