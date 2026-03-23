import MarketPageClient from "./market-page-client";
import { partialIdFromSlug, marketSlug } from "../../../lib/slugify";

export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function resolveConditionId(partialId) {
  // If it already looks like a full condition ID (66 chars), use it directly
  if (/^0x[a-fA-F0-9]{64}$/.test(partialId)) return partialId;
  try {
    const res = await fetch(`${API_URL}/api/market/resolve/${partialId}`, {
      cache: "no-store",
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
    const [liveRes, alertsRes] = await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        cache: "no-store",
      }),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { cache: "no-store" }
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

  return {
    title,
    description,
    alternates: {
      canonical: `/market/${canonicalSlug}`,
    },
    openGraph: {
      title: `${title} | PolySpotter`,
      description,
    },
    twitter: {
      card: "summary",
      title: `${title} | PolySpotter`,
      description,
    },
  };
}

export default async function MarketPage({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const conditionId = await resolveConditionId(partialId);
  const { live, alerts } = await getMarketData(conditionId);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const alertCount = alerts.length;
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: title,
    description: `${alertCount} notable trade${alertCount !== 1 ? "s" : ""} detected on "${title}" — ${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(totalUsd)} in smart money flow.`,
    url: `${process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com"}/market/${marketSlug(title, conditionId)}`,
    isPartOf: {
      "@type": "WebSite",
      name: "PolySpotter",
      url: process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com",
    },
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <MarketPageClient conditionId={conditionId} initialLive={live} initialAlerts={alerts} />
    </>
  );
}
