import WatchlistClient from "./watchlist-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const metadata = {
  title: "Watchlist — your saved markets",
  description: "Markets you've saved on PolySpotter.",
};

async function getData() {
  try {
    const [tagsRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;
    const walletsData = walletsRes.ok ? await walletsRes.json() : null;
    return {
      tags: tagsData?.tags || tagsData || [],
      topWallets: walletsData?.wallets || [],
    };
  } catch {
    return { tags: [], topWallets: [] };
  }
}

export default async function WatchlistPage() {
  const { tags, topWallets } = await getData();
  return <WatchlistClient tags={tags} topWallets={topWallets} />;
}
