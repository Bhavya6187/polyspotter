import Link from "next/link";
import TagPageClient from "./tag-page-client";
import TagPageHeader from "./tag-page-header";
import { marketSlug } from "../../../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function tagFromSlug(slug) {
  return decodeURIComponent(slug).replace(/-/g, " ");
}

function tagDisplayName(tag) {
  return tag.replace(/\b\w/g, (c) => c.toUpperCase());
}

function tagSlug(tag) {
  return encodeURIComponent(tag.toLowerCase().replace(/\s+/g, "-"));
}

const PER_PAGE = 20;

/** Extract tags that co-occur with the current tag from market data */
function extractRelatedTags(markets, currentTag) {
  const counts = {};
  for (const m of markets) {
    const seen = new Set();
    // Collect tags from market-level tags
    for (const t of m.tags || []) {
      seen.add(t);
    }
    // Collect tags from individual alerts
    for (const a of m.alerts || []) {
      for (const t of a.tags || []) {
        seen.add(t);
      }
    }
    for (const t of seen) {
      if (t.toLowerCase() !== currentTag.toLowerCase() && t !== "Hide From New") {
        counts[t] = (counts[t] || 0) + 1;
      }
    }
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([tag]) => tag);
}

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

async function getTagDescription(allTags, tag) {
  const match = allTags.find(
    (t) => (typeof t === "string" ? t : t.tag).toLowerCase() === tag.toLowerCase()
  );
  return match?.description || null;
}

async function getTagData(tag, page = 1) {
  try {
    const res = await fetch(
      `${API_URL}/api/alerts/by-market?page=${page}&per_page=${PER_PAGE}&tag=${encodeURIComponent(tag)}&include_resolved=true`,
      { next: { revalidate: 60 } }
    );
    if (!res.ok) return { markets: [], total: 0, total_alerts: 0 };
    const data = await res.json();
    return {
      markets: data.markets || [],
      total: data.total || 0,
      total_alerts: data.total_alerts || 0,
    };
  } catch {
    return { markets: [], total: 0, total_alerts: 0 };
  }
}

export async function generateMetadata({ params, searchParams }) {
  const { slug } = await params;
  const page = Math.max(1, parseInt((await searchParams)?.page) || 1);
  const tag = tagFromSlug(slug);
  const display = tagDisplayName(tag);

  const allTags = await getAllTags();
  const tagDesc = await getTagDescription(allTags, tag);
  const title =
    page > 1
      ? `${display} Prediction Market Smart Money Alerts (Page ${page})`
      : `${display} Prediction Markets — Smart Money Signals`;
  const description = tagDesc || `Track smart money signals and whale trades on ${display} prediction markets. See notable bets from sharp bettors on Polymarket.`;
  const canonical =
    page > 1
      ? `/tag/${tagSlug(tag)}?page=${page}`
      : `/tag/${tagSlug(tag)}`;

  return {
    title,
    description,
    alternates: {
      canonical,
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

export default async function TagPage({ params, searchParams }) {
  const { slug } = await params;
  const page = Math.max(1, parseInt((await searchParams)?.page) || 1);
  const tag = tagFromSlug(slug);
  const display = tagDisplayName(tag);

  const [tagData, allTags, walletsRes] = await Promise.all([
    getTagData(tag, page),
    getAllTags(),
    fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } })
      .then((r) => (r.ok ? r.json() : { wallets: [] }))
      .catch(() => ({ wallets: [] })),
  ]);

  const { markets, total, total_alerts } = tagData;
  const topWallets = walletsRes?.wallets || [];
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const tagUrl = `${siteUrl}/tag/${tagSlug(tag)}`;

  const tagDesc = await getTagDescription(allTags, tag);

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const collectionLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${display} — Polymarket Smart Money Trades`,
    description:
      tagDesc ||
      `Notable trades for ${display} markets on Polymarket.`,
    url: tagUrl,
    isPartOf: {
      "@type": "WebSite",
      name: "PolySpotter",
      url: siteUrl,
    },
  };

  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `${display} Markets with Smart Money Signals`,
    numberOfItems: markets.length,
    itemListElement: markets.map((m, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: m.market_title,
      url: `${siteUrl}/market/${marketSlug(m.market_title, m.condition_id)}`,
    })),
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
        name: display,
        item: tagUrl,
      },
    ],
  };

  return (
    <>
      {page > 1 && (
        <link
          rel="prev"
          href={`/tag/${tagSlug(tag)}${page > 2 ? `?page=${page - 1}` : ""}`}
        />
      )}
      {page < totalPages && (
        <link rel="next" href={`/tag/${tagSlug(tag)}?page=${page + 1}`} />
      )}
      <main className="mx-auto max-w-6xl px-4 py-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(collectionLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      {/* Header with search + topic nav */}
      <TagPageHeader
        allTags={allTags}
        relatedTags={extractRelatedTags(markets, tag)}
        topWallets={topWallets}
        currentTag={tag}
        display={display}
        totalAlerts={total_alerts}
        totalMarkets={total}
        page={page}
        totalPages={totalPages}
        tagDesc={tagDesc}
      />

      {/* Server-rendered market list for crawlers */}
      {markets.length > 0 && (
        <div className="seo-content">
          <section>
            <h2>{display} Markets with Smart Money Signals</h2>
            <ol>
              {markets.map((m) => (
                <li key={m.condition_id}>
                  <a
                    href={`/market/${marketSlug(m.market_title, m.condition_id)}`}
                  >
                    {m.market_title}
                  </a>{" "}
                  — {m.alert_count} signal{m.alert_count !== 1 ? "s" : ""},{" "}
                  {usdFmt.format(m.total_usd)} tracked
                  {m.alerts?.[0]?.llm_headline && (
                    <>. Latest: {m.alerts[0].llm_headline}</>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}

      {/* Trades */}
      {markets.length > 0 ? (
        <section aria-label="Notable trades">
          <TagPageClient
            markets={markets}
            page={page}
            totalPages={totalPages}
            slug={tagSlug(tag)}
          />
        </section>
      ) : (
        <div
          className="rounded-xl border p-12 text-center"
          style={{
            borderColor: "var(--border)",
            background: "var(--surface-card)",
            color: "var(--text-muted)",
          }}
        >
          No signals found for &ldquo;{display}&rdquo;.
        </div>
      )}
    </main>
    </>
  );
}
