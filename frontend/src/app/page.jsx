import HomeClient from "./home-client";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getHomeData() {
  try {
    const [alertsRes, tagsRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts?page=1&per_page=20`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
    ]);

    const alertsData = alertsRes.ok ? await alertsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;

    return {
      alerts: alertsData?.alerts || [],
      total: alertsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
    };
  } catch {
    return { alerts: [], total: 0, tags: [] };
  }
}

export default async function HomePage() {
  const { alerts, total, tags } = await getHomeData();

  return (
    <HomeClient
      initialAlerts={alerts}
      initialTotal={total}
      tags={tags}
    />
  );
}
