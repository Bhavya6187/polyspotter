import Link from "next/link";
import TagPageClient from "./tag-page-client";
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

const TAG_DESCRIPTIONS = {
  sports:
    "Track smart money flowing into sports prediction markets on Polymarket. PolySpotter surfaces large bets from sharp bettors across NFL, NBA, MLB, soccer, tennis, and more — highlighting coordinated flow, whale positions, and high-conviction wagers.",
  politics:
    "Monitor sharp bettor activity in political prediction markets. From elections to policy decisions, see where informed money is positioning on Polymarket's political events.",
  geopolitics:
    "Follow whale trades in geopolitical prediction markets on Polymarket. Track sharp bettors wagering on international diplomacy, conflicts, treaties, and global power shifts.",
  crypto:
    "Follow whale trades in crypto prediction markets on Polymarket. Track sharp bettors wagering on Bitcoin price targets, Ethereum milestones, DeFi outcomes, and regulatory decisions.",
  culture:
    "Track smart money in culture and entertainment prediction markets on Polymarket — from awards shows to viral moments and media events.",
  finance:
    "Monitor sharp bettor activity in finance prediction markets on Polymarket. Track whale trades on interest rates, economic indicators, and market events.",
  weather:
    "Follow smart money signals in weather prediction markets on Polymarket — hurricane paths, temperature records, and climate events.",
  soccer:
    "Track whale trades in soccer prediction markets on Polymarket. Sharp bettors positioning on Premier League, Champions League, La Liga, and international matches.",
};

async function getTagData(tag, page = 1) {
  try {
    const res = await fetch(
      `${API_URL}/api/alerts/by-market?page=${page}&per_page=${PER_PAGE}&tag=${encodeURIComponent(tag)}`,
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

  const title =
    page > 1
      ? `${display} Prediction Market Smart Money Alerts (Page ${page})`
      : `${display} — Polymarket Smart Money Trades & Whale Alerts`;
  const description =
    TAG_DESCRIPTIONS[tag.toLowerCase()] ||
    `Notable trades and smart money alerts for ${display} markets on Polymarket. Track large bets, sharp bettors, and coordinated flow.`;
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
  const { markets, total, total_alerts } = await getTagData(tag, page);
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const tagUrl = `${siteUrl}/tag/${tagSlug(tag)}`;

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
      TAG_DESCRIPTIONS[tag.toLowerCase()] ||
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

  const tagDesc = TAG_DESCRIPTIONS[tag.toLowerCase()];

  return (
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

      {/* Nav */}
      <nav className="mb-6" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: "var(--text-muted)" }}
        >
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15 19l-7-7 7-7"
            />
          </svg>
          All markets
        </Link>
      </nav>

      {/* Header */}
      <header className="mb-6">
        <h1
          className="text-2xl font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          {display}
        </h1>
        <p
          className="mt-1 text-sm"
          style={{ color: "var(--text-secondary)" }}
        >
          {total_alerts} signal{total_alerts !== 1 ? "s" : ""} across{" "}
          {total} market{total !== 1 ? "s" : ""}
          {page > 1 && ` — Page ${page} of ${totalPages}`}
        </p>
        {tagDesc && (
          <p
            className="mt-2 text-sm leading-relaxed"
            style={{ color: "var(--text-muted)" }}
          >
            {tagDesc}
          </p>
        )}
      </header>

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
  );
}
