import MarketPageClient from "./market-page-client";
import { partialIdFromSlug, marketSlug } from "../../../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function resolveConditionId(partialId) {
  // If it already looks like a full condition ID (66 chars), use it directly
  if (/^0x[a-fA-F0-9]{64}$/.test(partialId)) return partialId;
  try {
    const res = await fetch(`${API_URL}/api/market/resolve/${partialId}`, {
      next: { revalidate: 60 },
    });
    if (res.ok) {
      const data = await res.json();
      return data.condition_id;
    }
  } catch {}
  return partialId;
}

async function getMarketData(conditionId) {
  try {
    const [liveRes, alertsRes, priceRes, holdersRes, thesesRes] = await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        next: { revalidate: 60 },
      }),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { next: { revalidate: 60 } }
      ),
      fetch(`${API_URL}/api/market/${conditionId}/price-history?range=7d`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/market/${conditionId}/holders`, {
        next: { revalidate: 300 },
      }),
      fetch(`${API_URL}/api/market/${conditionId}/theses`, {
        next: { revalidate: 300 },
      }),
    ]);

    const live = liveRes.ok ? await liveRes.json() : null;
    const alertsData = alertsRes.ok ? await alertsRes.json() : null;
    const priceData = priceRes.ok ? await priceRes.json() : null;
    const holdersData = holdersRes.ok ? await holdersRes.json() : null;
    const thesesData = thesesRes.ok ? await thesesRes.json() : null;

    return {
      live,
      alerts: alertsData?.alerts || [],
      priceHistory: priceData,
      holders: holdersData?.holders || [],
      theses: thesesData?.theses || [],
    };
  } catch {
    return { live: null, alerts: [], priceHistory: null, holders: [], theses: [] };
  }
}

export async function generateMetadata({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const conditionId = await resolveConditionId(partialId);
  const { live, alerts } = await getMarketData(conditionId);

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
      ? `${alertCount} notable trade${alertCount !== 1 ? "s" : ""} detected totaling ${usdStr}. Large bets. Sharp wallets. Early signals.`
      : `Large bets. Sharp wallets. Early signals. "${title}" — live on Polymarket.`;

  const canonicalSlug = marketSlug(title, conditionId);

  const bestAlert = [...alerts].sort((a, b) => (b.composite_score || 0) - (a.composite_score || 0))[0];
  const alertId = bestAlert?.id;
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  return {
    title,
    description,
    alternates: {
      canonical: `/market/${canonicalSlug}`,
    },
    openGraph: {
      title: `${title} | PolySpotter`,
      description,
      images: alertId ? [`${siteUrl}/api/og/${alertId}`] : [],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | PolySpotter`,
      description,
    },
  };
}

export default async function MarketPage({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const conditionId = await resolveConditionId(partialId);
  const { live, alerts, priceHistory, holders, theses } = await getMarketData(conditionId);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const alertCount = alerts.length;
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const marketUrl = `${siteUrl}/market/${marketSlug(title, conditionId)}`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: title,
    description: `${alertCount} notable trade${alertCount !== 1 ? "s" : ""} detected on "${title}" — ${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(totalUsd)} in smart money flow.`,
    url: marketUrl,
    isPartOf: {
      "@type": "WebSite",
      name: "PolySpotter",
      url: siteUrl,
    },
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "Home",
        item: siteUrl,
      },
      {
        "@type": "ListItem",
        position: 2,
        name: title,
        item: marketUrl,
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />
      <MarketPageClient
  conditionId={conditionId}
  initialLive={live}
  initialAlerts={alerts}
  priceHistory={priceHistory}
  holders={holders}
  theses={theses}
/>
    </>
  );
}
