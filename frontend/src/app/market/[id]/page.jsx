import { cache } from "react";
import MarketPageClient from "./market-page-client";
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

// Single source of truth for everything generateMetadata and the page body need.
// Wrapped in React's cache() so both render phases share one execution per request
// — avoids the double JSON parsing and conditional basketball/cricket fetches that
// previously ran twice.
const loadMarketPage = cache(async (partialId) => {
  const conditionId = await resolveConditionId(partialId);

  const [liveRes, alertsRes, priceRes, holdersRes, thesesRes] =
    await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        next: { revalidate: 60 },
      }).catch(() => null),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { next: { revalidate: 60 } }
      ).catch(() => null),
      fetch(
        `${API_URL}/api/market/${conditionId}/price-history?range=7d`,
        { next: { revalidate: 60 } }
      ).catch(() => null),
      fetch(`${API_URL}/api/market/${conditionId}/holders`, {
        next: { revalidate: 300 },
      }).catch(() => null),
      fetch(`${API_URL}/api/market/${conditionId}/theses`, {
        next: { revalidate: 300 },
      }).catch(() => null),
    ]);

  const live = liveRes?.ok ? await liveRes.json() : null;
  const alertsData = alertsRes?.ok ? await alertsRes.json() : null;
  const priceHistory = priceRes?.ok ? await priceRes.json() : null;
  const holdersData = holdersRes?.ok ? await holdersRes.json() : null;
  const thesesData = thesesRes?.ok ? await thesesRes.json() : null;

  const alerts = alertsData?.alerts || [];
  const holders = holdersData?.holders || [];
  const theses = thesesData?.theses || [];
  const title = live?.title || alerts?.[0]?.market_title || "Market";

  const tagSet = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const overlayParams = new URLSearchParams({
    title,
    event_slug: alerts[0]?.event_slug || "",
  });
  for (const t of tagSet) overlayParams.append("tag", t);

  let initialOverlay = null;
  try {
    const ovRes = await fetch(
      `${API_URL}/api/market/${conditionId}/overlay?${overlayParams}`,
      { next: { revalidate: 15 } },
    );
    initialOverlay = ovRes?.ok ? await ovRes.json() : null;
  } catch {}

  // Event metadata for the "Part of: <event>" cross-link. Only fetch when
  // the market actually belongs to an event (most do; the few that don't
  // are standalone). Cheap because /api/event/{slug} is cached server-side
  // for 60s and the response is tiny when only `title` is consumed.
  const eventSlug = alerts?.[0]?.event_slug || null;
  let eventTitle = null;
  if (eventSlug) {
    try {
      const evRes = await fetch(
        `${API_URL}/api/event/${encodeURIComponent(eventSlug)}`,
        { next: { revalidate: 300 } }
      );
      if (evRes.ok) {
        const evData = await evRes.json();
        eventTitle = evData?.event?.title || null;
      }
    } catch {}
  }

  // LLM-generated SEO fields (title/description/summary/FAQs) live on the
  // market-group record. Fetch once here and expose to both render phases.
  let seoTitle = null;
  let seoDescription = null;
  let seoSummary = null;
  let seoFaqs = [];
  try {
    const mgRes = await fetch(
      `${API_URL}/api/alerts/by-market?q=${encodeURIComponent(title)}&per_page=1`,
      { next: { revalidate: 60 } }
    );
    if (mgRes.ok) {
      const mgData = await mgRes.json();
      const match = mgData.markets?.find((m) => m.condition_id === conditionId);
      if (match) {
        seoTitle = match.seo_title || null;
        seoDescription = match.seo_description || null;
        seoSummary = match.seo_summary || null;
        seoFaqs = match.seo_faqs || [];
      }
    }
  } catch {}

  return {
    conditionId,
    title,
    live,
    alerts,
    priceHistory,
    holders,
    theses,
    initialOverlay,
    eventSlug,
    eventTitle,
    seoTitle,
    seoDescription,
    seoSummary,
    seoFaqs,
  };
});

export async function generateMetadata({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const {
    conditionId,
    title,
    alerts,
    seoTitle,
    seoDescription,
  } = await loadMarketPage(partialId);

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

  // Markets with zero alerts have no unique PolySpotter-authored content —
  // live metadata alone duplicates polymarket.com. Noindex to avoid thin-content
  // penalties; keep follow so link equity still flows to tags/wallets/theses.
  const noindex = alertCount === 0;

  return {
    title: seoTitle || title,
    description: seoDescription || description,
    alternates: {
      canonical: `/market/${canonicalSlug}`,
    },
    robots: noindex ? { index: false, follow: true } : undefined,
    openGraph: {
      title: `${seoTitle || title} | PolySpotter`,
      description: seoDescription || description,
      images: alertId ? [`${siteUrl}/api/og/${alertId}`] : [],
    },
    twitter: {
      card: "summary_large_image",
      title: `${seoTitle || title} | PolySpotter`,
      description: seoDescription || description,
    },
  };
}

export default async function MarketPage({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const {
    conditionId,
    title,
    live,
    alerts,
    priceHistory,
    holders,
    theses,
    initialOverlay,
    eventSlug,
    eventTitle,
    seoSummary,
    seoFaqs,
  } = await loadMarketPage(partialId);

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

  // FAQ JSON-LD: prefer LLM-generated FAQs over alert-based ones
  const faqItems =
    seoFaqs.length > 0
      ? seoFaqs.map((faq) => ({
          "@type": "Question",
          name: faq.question,
          acceptedAnswer: {
            "@type": "Answer",
            text: faq.answer,
          },
        }))
      : alerts
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

          {eventSlug && (
            <p style={{ fontSize: "0.85rem" }}>
              Part of:{" "}
              <a href={`/event/${encodeURIComponent(eventSlug)}`}>
                {eventTitle || eventSlug}
              </a>
            </p>
          )}

          <h1>{title}</h1>
          {seoSummary && <p>{seoSummary}</p>}
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

          {(() => {
            const allTags = [...new Set(alerts.flatMap((a) => a.tags || []))].filter(
              (t) => t && t !== "Hide From New"
            );
            return allTags.length > 0 ? (
              <p>
                Categories:{" "}
                {allTags.map((t, i) => (
                  <span key={t}>
                    {i > 0 && ", "}
                    <a href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}>
                      {t}
                    </a>
                  </span>
                ))}
              </p>
            ) : null;
          })()}

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

      <MarketPageClient
        conditionId={conditionId}
        initialLive={live}
        initialAlerts={alerts}
        priceHistory={priceHistory}
        holders={holders}
        theses={theses}
        eventSlug={eventSlug}
        eventTitle={eventTitle}
        initialOverlay={initialOverlay}
      />
    </>
  );
}
