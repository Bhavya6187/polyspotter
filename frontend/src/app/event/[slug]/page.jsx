import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { marketSlug } from "../../../lib/slugify";
import EventPageHeader from "./event-page-header";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

// Best-effort humanizer for slugs that didn't hydrate from Gamma. Most
// hydrated rows have a real title — this is a fallback so the H1 never
// shows a raw slug. Sports prefixes (nba/ucl/mlb/etc.) get a coarser
// treatment because Polymarket slugs encode them differently.
function humanizeSlug(slug) {
  if (!slug) return "";
  return slug
    .split("-")
    .map((p) => (p.length <= 3 ? p.toUpperCase() : p.replace(/^\w/, (c) => c.toUpperCase())))
    .join(" ");
}

const loadEvent = cache(async (slug) => {
  try {
    const res = await fetch(`${API_URL}/api/event/${encodeURIComponent(slug)}`, {
      next: { revalidate: 60 },
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`API ${res.status}`);
    return res.json();
  } catch {
    return null;
  }
});

async function getAllTags() {
  try {
    const res = await fetch(`${API_URL}/api/tags`, { next: { revalidate: 300 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data?.tags || data || [];
  } catch {
    return [];
  }
}

async function getTopWalletsForCommandPalette() {
  try {
    const res = await fetch(`${API_URL}/api/wallets/top?limit=10`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data?.wallets || [];
  } catch {
    return [];
  }
}

export async function generateMetadata({ params }) {
  const { slug } = await params;
  const data = await loadEvent(slug);

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const canonical = `/event/${encodeURIComponent(slug)}`;

  if (!data) {
    return {
      title: "Event not found | PolySpotter",
      robots: { index: false, follow: true },
      alternates: { canonical },
    };
  }

  const eventTitle = data.event.title || humanizeSlug(slug);
  const stats = data.stats || {};
  const usd = stats.total_usd || 0;
  const usdStr = usd > 0 ? usdFmt.format(usd) : "";
  const nMarkets = stats.total_markets || 0;
  const nAlerts = stats.total_alerts || 0;

  // Single-market events duplicate the /market/[id] page — let Google fold
  // them by canonicalizing to the market URL. Keep follow for link equity.
  const isSingleMarket = nMarkets <= 1;
  const marketCanonical =
    isSingleMarket && data.markets?.[0]
      ? `/market/${marketSlug(data.markets[0].market_title, data.markets[0].condition_id)}`
      : canonical;

  const description =
    data.event.seo_description ||
    (nAlerts > 0
      ? `${nAlerts} smart money signal${nAlerts !== 1 ? "s" : ""} on ${eventTitle}${
          usdStr ? ` totaling ${usdStr}` : ""
        } across ${nMarkets} Polymarket market${nMarkets !== 1 ? "s" : ""}.`
      : `${eventTitle} — odds and smart money signals on Polymarket.`);

  const title =
    data.event.seo_title ||
    `${eventTitle} — Polymarket Odds & Smart Money`;

  return {
    title,
    description,
    alternates: { canonical: marketCanonical },
    robots: isSingleMarket ? { index: false, follow: true } : undefined,
    openGraph: {
      title: `${eventTitle} | PolySpotter`,
      description,
      images: data.event.image ? [data.event.image] : [],
    },
    twitter: {
      card: "summary_large_image",
      title: `${eventTitle} | PolySpotter`,
      description,
    },
  };
}

export default async function EventPage({ params }) {
  const { slug } = await params;
  const data = await loadEvent(slug);

  if (!data) {
    notFound();
  }

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const eventUrl = `${siteUrl}/event/${encodeURIComponent(slug)}`;
  const eventTitle = data.event.title || humanizeSlug(slug);
  const seoSummary = data.event.seo_summary;
  const description = data.event.description;

  const stats = data.stats || {};
  const totalUsd = stats.total_usd || 0;
  const totalAlerts = stats.total_alerts || 0;
  const totalMarkets = stats.total_markets || 0;

  const markets = (data.markets || []).slice().sort(
    (a, b) => (b.total_usd || 0) - (a.total_usd || 0)
  );
  const topAlerts = data.top_alerts || [];
  const topWallets = data.top_wallets || [];
  const tags = (data.event.tags || []).map((t) => t.label).filter(Boolean);
  const relatedThesis = data.related_thesis;
  const relatedArticle = data.related_article;

  const [allTags, topWalletsForPalette] = await Promise.all([
    getAllTags(),
    getTopWalletsForCommandPalette(),
  ]);

  // -- JSON-LD ---------------------------------------------------------------
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: siteUrl },
      { "@type": "ListItem", position: 2, name: eventTitle, item: eventUrl },
    ],
  };

  const collectionLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${eventTitle} — Polymarket Smart Money Trades`,
    description: seoSummary || description || `Notable trades for ${eventTitle} on Polymarket.`,
    url: eventUrl,
    isPartOf: { "@type": "WebSite", name: "PolySpotter", url: siteUrl },
  };

  const itemListLd = markets.length > 0 ? {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `${eventTitle} markets`,
    numberOfItems: markets.length,
    itemListElement: markets.map((m, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: m.market_title,
      url: `${siteUrl}/market/${marketSlug(m.market_title, m.condition_id)}`,
    })),
  } : null;

  const faqs = data.event.seo_faqs || [];
  const faqLd = faqs.length > 0 ? {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question",
      name: f.question,
      acceptedAnswer: { "@type": "Answer", text: f.answer },
    })),
  } : null;

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(collectionLd) }} />
      {itemListLd && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListLd) }} />
      )}
      {faqLd && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }} />
      )}

      <main className="mx-auto max-w-6xl px-4 py-6">
        <EventPageHeader
          allTags={allTags}
          topWallets={topWalletsForPalette}
          eventTitle={eventTitle}
          tags={tags}
          totalAlerts={totalAlerts}
          totalMarkets={totalMarkets}
          totalUsd={totalUsd}
          endDate={data.event.end_date}
          image={data.event.image}
          summary={seoSummary || description}
        />

        {/* Markets list — primary content for SEO + UX */}
        {markets.length > 0 && (
          <section aria-label="Markets in this event" className="mb-8">
            <h2 className="mb-3 text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              Markets ({markets.length})
            </h2>
            <ol className="space-y-2">
              {markets.map((m) => (
                <li
                  key={m.condition_id}
                  className="rounded-xl border p-4 transition-colors"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <Link
                    href={`/market/${marketSlug(m.market_title, m.condition_id)}`}
                    className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <span className="font-medium" style={{ color: "var(--text-primary)" }}>
                      {m.market_title}
                    </span>
                    <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                      {m.alert_count} signal{m.alert_count !== 1 ? "s" : ""} ·{" "}
                      {usdFmt.format(m.total_usd || 0)} tracked
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* Top alerts across the event */}
        {topAlerts.length > 0 && (
          <section aria-label="Top trades" className="mb-8">
            <h2 className="mb-3 text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              Top trades across all markets
            </h2>
            <ol className="space-y-2">
              {topAlerts.slice(0, 10).map((a) => (
                <li
                  key={a.id}
                  className="rounded-xl border p-4"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <Link href={`/alert/${a.id}`} className="block">
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>
                      {a.llm_headline || a.market_title}
                    </div>
                    {a.llm_summary && (
                      <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                        {a.llm_summary}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: "var(--text-muted)" }}>
                      <span>{usdFmt.format(a.total_usd || 0)}</span>
                      {a.win_rate != null && (
                        <span>Wallet win rate: {Math.round(a.win_rate * 100)}%</span>
                      )}
                      <span>Score: {a.composite_score?.toFixed?.(1) ?? a.composite_score}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* Top wallets */}
        {topWallets.length > 0 && (
          <section aria-label="Top wallets" className="mb-8">
            <h2 className="mb-3 text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              Top wallets in this event
            </h2>
            <ol className="space-y-2">
              {topWallets.slice(0, 10).map((w) => (
                <li
                  key={w.wallet}
                  className="rounded-xl border p-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <Link href={`/wallet/${w.wallet}`} className="font-mono text-sm" style={{ color: "var(--text-primary)" }}>
                    {w.wallet.slice(0, 8)}…{w.wallet.slice(-4)}
                  </Link>
                  <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                    {usdFmt.format(w.total_usd_in_event || 0)} ·{" "}
                    {w.n_markets} market{w.n_markets !== 1 ? "s" : ""} ·{" "}
                    {w.n_alerts} alert{w.n_alerts !== 1 ? "s" : ""}
                    {w.win_rate != null && ` · ${Math.round(w.win_rate * 100)}% wins`}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* Cross-links: thesis + article */}
        {(relatedThesis || relatedArticle) && (
          <section aria-label="More on this event" className="mb-8">
            <h2 className="mb-3 text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              More on this event
            </h2>
            <div className="space-y-2">
              {relatedArticle && (
                <Link
                  href={`/article/${relatedArticle.published_date}/${slug}`}
                  className="block rounded-xl border p-4"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    PolySpotter article
                  </div>
                  <div className="mt-1 font-medium" style={{ color: "var(--text-primary)" }}>
                    {relatedArticle.headline}
                  </div>
                </Link>
              )}
              {relatedThesis && (
                <Link
                  href={`/thesis/${relatedThesis.id}`}
                  className="block rounded-xl border p-4"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Cross-market thesis
                  </div>
                  <div className="mt-1 font-medium" style={{ color: "var(--text-primary)" }}>
                    {relatedThesis.thesis_headline || `Thesis covering ${relatedThesis.markets?.length || 0} markets`}
                  </div>
                </Link>
              )}
            </div>
          </section>
        )}

        {/* FAQs */}
        {faqs.length > 0 && (
          <section aria-label="FAQs" className="mb-8">
            <h2 className="mb-3 text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              FAQs
            </h2>
            <div className="space-y-3">
              {faqs.map((f, i) => (
                <details
                  key={i}
                  className="rounded-xl border p-4"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <summary className="cursor-pointer font-medium" style={{ color: "var(--text-primary)" }}>
                    {f.question}
                  </summary>
                  <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                    {f.answer}
                  </p>
                </details>
              ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}
