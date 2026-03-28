import HomeClient from "./home-client";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getHomeData() {
  try {
    const [marketsRes, tagsRes, thesesRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/theses?page=1&per_page=5`, {
        next: { revalidate: 60 },
      }),
    ]);

    const marketsData = marketsRes.ok ? await marketsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;
    const thesesData = thesesRes.ok ? await thesesRes.json() : null;

    return {
      markets: marketsData?.markets || [],
      total: marketsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
      theses: thesesData?.theses || thesesData || [],
    };
  } catch {
    return { markets: [], total: 0, tags: [], theses: [] };
  }
}

export default async function HomePage() {
  const { markets, total, tags, theses } = await getHomeData();

  return (
    <HomeClient
      initialMarkets={markets}
      initialTotal={total}
      tags={tags}
      initialTheses={theses}
    />
  );
}
