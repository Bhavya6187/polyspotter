import Link from "next/link";
import TagPageClient from "./tag-page-client";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function tagFromSlug(slug) {
  return decodeURIComponent(slug).replace(/-/g, " ");
}

function tagSlug(tag) {
  return encodeURIComponent(tag.toLowerCase().replace(/\s+/g, "-"));
}

async function getTagData(tag) {
  try {
    const res = await fetch(
      `${API_URL}/api/alerts/by-market?page=1&per_page=20&tag=${encodeURIComponent(tag)}`,
      { next: { revalidate: 60 } }
    );
    if (!res.ok) return { markets: [], total: 0 };
    const data = await res.json();
    return {
      markets: data.markets || [],
      total: data.total || 0,
      total_alerts: data.total_alerts || 0,
    };
  } catch {
    return { markets: [], total: 0 };
  }
}

export async function generateMetadata({ params }) {
  const { slug } = await params;
  const tag = tagFromSlug(slug);
  const title = `${tag} — Polymarket Smart Money Trades`;
  const description = `Notable trades and smart money alerts for ${tag} markets on Polymarket. Track large bets, sharp bettors, and coordinated flow.`;

  return {
    title,
    description,
    alternates: {
      canonical: `/tag/${tagSlug(tag)}`,
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

export default async function TagPage({ params }) {
  const { slug } = await params;
  const tag = tagFromSlug(slug);
  const { markets, total, total_alerts } = await getTagData(tag);

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const tagUrl = `${siteUrl}/tag/${tagSlug(tag)}`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${tag} — Polymarket Smart Money Trades`,
    description: `Notable trades for ${tag} markets on Polymarket.`,
    url: tagUrl,
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
        name: tag,
        item: tagUrl,
      },
    ],
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
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
          style={{ color: 'var(--text-muted)' }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
      </nav>

      {/* Header */}
      <header className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
          {tag}
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {total_alerts} signal{total_alerts !== 1 ? "s" : ""} across {total} market{total !== 1 ? "s" : ""}
        </p>
      </header>

      {/* Trades */}
      {markets.length > 0 ? (
        <section aria-label="Notable trades">
          <TagPageClient initialMarkets={markets} initialTotal={total} initialTotalAlerts={total_alerts} tag={tag} />
        </section>
      ) : (
        <div className="rounded-xl border p-12 text-center" style={{ borderColor: 'var(--border)', background: 'var(--surface-card)', color: 'var(--text-muted)' }}>
          No signals found for &ldquo;{tag}&rdquo;.
        </div>
      )}
    </main>
  );
}
