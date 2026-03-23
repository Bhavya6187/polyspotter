import MarketPageClient from "./market-page-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getMarketData(conditionId) {
  try {
    const [liveRes, alertsRes] = await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        next: { revalidate: 60 },
      }),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { next: { revalidate: 60 } }
      ),
    ]);

    const live = liveRes.ok ? await liveRes.json() : null;
    const alertsData = alertsRes.ok ? await alertsRes.json() : null;

    return {
      live,
      alerts: alertsData?.alerts || [],
    };
  } catch {
    return { live: null, alerts: [] };
  }
}

export async function generateMetadata({ params }) {
  const { id } = await params;
  const { live, alerts } = await getMarketData(id);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const alertCount = alerts.length;
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const usdStr = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(totalUsd);

  const description =
    alertCount > 0
      ? `${alertCount} notable trade${alertCount !== 1 ? "s" : ""} detected totaling ${usdStr}. Follow the smart money on this Polymarket market.`
      : `Follow the smart money on "${title}" — live on Polymarket.`;

  return {
    title,
    description,
    openGraph: {
      title: `${title} | PolySpotter`,
      description,
    },
  };
}

export default async function MarketPage({ params }) {
  const { id } = await params;
  const { live, alerts } = await getMarketData(id);

  return <MarketPageClient conditionId={id} initialLive={live} initialAlerts={alerts} />;
}
