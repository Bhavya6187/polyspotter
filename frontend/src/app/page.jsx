import HomeClient from "./home-client";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getHomeData() {
  try {
    const [marketsRes, tagsRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
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
