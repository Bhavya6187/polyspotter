import DiscoverClient from "./discover-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const revalidate = 60;

export const metadata = {
  title: "Discover — signal activity by topic",
  description: "Browse signal activity by topic across Politics, Crypto, NBA, Geopolitics, and more.",
};

async function getData() {
  try {
    const [topicsRes, tagsRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/topics`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);
    const topicsData = topicsRes.ok ? await topicsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;
    const walletsData = walletsRes.ok ? await walletsRes.json() : null;
    return {
      topics: topicsData?.topics || [],
      tags: tagsData?.tags || tagsData || [],
      topWallets: walletsData?.wallets || [],
    };
  } catch {
    return { topics: [], tags: [], topWallets: [] };
  }
}

export default async function DiscoverPage() {
  const { topics, tags, topWallets } = await getData();
  return <DiscoverClient topics={topics} tags={tags} topWallets={topWallets} />;
}
