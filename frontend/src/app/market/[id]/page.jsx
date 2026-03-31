import MarketPageClient from "./market-page-client";
import BasketballPageClient from "./basketball-page-client";
import { partialIdFromSlug, marketSlug } from "../../../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function resolveConditionId(partialId) {
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
    const [liveRes, alertsRes, priceRes, holdersRes, thesesRes] =
      await Promise.all([
        fetch(`${API_URL}/api/market/${conditionId}/live`, {
          next: { revalidate: 60 },
        }),
        fetch(
          `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
          { next: { revalidate: 60 } }
        ),
        fetch(
          `${API_URL}/api/market/${conditionId}/price-history?range=7d`,
          { next: { revalidate: 60 } }
        ),
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

    // Only fetch basketball data if tags suggest it's a basketball market
    const basketballTags = ["sports", "nba", "basketball", "ncaa", "march madness", "cbb", "games"];
    const tags = (alertsData?.alerts || []).flatMap((a) => a.tags || []);
    const maybeBasketball = tags.some((t) =>
      basketballTags.includes(t.toLowerCase())
    );
    let basketballData = null;
    if (maybeBasketball) {
      try {
        const basketballRes = await fetch(
          `${API_URL}/api/market/${conditionId}/basketball`,
          { next: { revalidate: 15 } }
        );
        basketballData = basketballRes?.ok ? await basketballRes.json() : null;
      } catch {}
    }

    return {
      live,
      alerts: alertsData?.alerts || [],
      priceHistory: priceData,
      holders: holdersData?.holders || [],
      theses: thesesData?.theses || [],
      basketballData,
    };
  } catch {
    return {
      live: null,
      alerts: [],
      priceHistory: null,
      holders: [],
      theses: [],
      basketballData: null,
    };
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
      ? `${alertCount} smart money signal${alertCount !== 1 ? "s" : ""} on "${title}" totaling ${usdStr}. Track sharp bettors and whale trades on PolySpotter.`
      : `"${title}" — track smart money, whale trades, and sharp bettor signals on PolySpotter.`;

  const canonicalSlug = marketSlug(title, conditionId);

  const bestAlert = [...alerts].sort(
    (a, b) => (b.composite_score || 0) - (a.composite_score || 0)
  )[0];
  const alertId = bestAlert?.id;
  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

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
  const { live, alerts, priceHistory, holders, theses, basketballData } =
    await getMarketData(conditionId);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const alertCount = alerts.length;
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const marketUrl = `${siteUrl}/market/${marketSlug(title, conditionId)}`;

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

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

  // FAQ JSON-LD from alert headlines + summaries
  const faqItems = alerts
    .filter((a) => a.llm_headline && a.llm_summary)
    .slice(0, 5)
    .map((a) => ({
      "@type": "Question",
      name: a.llm_headline,
      acceptedAnswer: {
        "@type": "Answer",
        text:
          a.llm_bullets?.length > 0
            ? a.llm_bullets.join(" ")
            : a.llm_summary,
      },
    }));

  const faqLd =
    faqItems.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqItems,
        }
      : null;

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />
      {faqLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }}
        />
      )}

      {/* Server-rendered SEO content */}
      <div className="seo-content">
        <article>
          <nav aria-label="Breadcrumb">
            <a href="/">PolySpotter</a> &gt; <span>{title}</span>
          </nav>

          <h1>{title}</h1>
          {live?.description && <p>{live.description}</p>}
          <p>
            {alertCount} smart money signal{alertCount !== 1 ? "s" : ""}{" "}
            detected{totalUsd > 0 ? `, totaling ${usdFmt.format(totalUsd)}` : ""}.
            {live?.end_date && (
              <>
                {" "}
                Resolution date:{" "}
                {new Date(live.end_date).toLocaleDateString("en-US", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
                .
              </>
            )}
          </p>

          {alerts.length > 0 && (
            <section>
              <h2>Notable Trades</h2>
              {alerts.slice(0, 10).map((alert) => (
                <article key={alert.id}>
                  <h3>{alert.llm_headline || alert.market_title}</h3>
                  {alert.llm_summary && <p>{alert.llm_summary}</p>}
                  {alert.llm_bullets?.length > 0 && (
                    <ul>
                      {alert.llm_bullets.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                  <p>
                    {usdFmt.format(alert.total_usd || 0)}
                    {alert.llm_copy_action?.outcome &&
                      ` on ${alert.llm_copy_action.outcome}`}
                    {alert.win_rate != null &&
                      ` | Wallet win rate: ${Math.round(alert.win_rate * 100)}%`}
                  </p>
                </article>
              ))}
            </section>
          )}

          {holders.length > 0 && (
            <section>
              <h2>Top Holders</h2>
              <ol>
                {holders.slice(0, 10).map((h, i) => (
                  <li key={h.wallet || i}>
                    <a href={`/wallet/${h.wallet}`}>
                      {h.wallet?.slice(0, 6)}...{h.wallet?.slice(-4)}
                    </a>{" "}
                    — {h.outcome},{" "}
                    {usdFmt.format(h.position_size || 0)}
                    {h.win_rate != null &&
                      ` (${Math.round(h.win_rate * 100)}% win rate)`}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {theses.length > 0 && (
            <section>
              <h2>Related Theses</h2>
              {theses.map((t) => (
                <div key={t.id}>
                  <h3>
                    <a href={`/thesis/${t.id}`}>{t.thesis_headline}</a>
                  </h3>
                  <p>
                    Covers {(t.markets || []).length} related market
                    {(t.markets || []).length !== 1 ? "s" : ""}
                  </p>
                </div>
              ))}
            </section>
          )}
        </article>
      </div>

      {(() => {
        const isBasketball = !!basketballData;
        const PageClient = isBasketball ? BasketballPageClient : MarketPageClient;
        const clientProps = {
          conditionId,
          initialLive: live,
          initialAlerts: alerts,
          priceHistory,
          holders,
          theses,
          ...(isBasketball ? { initialGameData: basketballData } : {}),
        };
        return <PageClient {...clientProps} />;
      })()}
    </>
  );
}
