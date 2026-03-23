import Link from "next/link";
import TagPageClient from "./tag-page-client";

export const dynamic = "force-dynamic";

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
      `${API_URL}/api/alerts/by-market?page=1&per_page=50&tag=${encodeURIComponent(tag)}`,
      { cache: "no-store" }
    );
    if (!res.ok) return { markets: [], total: 0 };
    const data = await res.json();
    return {
      markets: data.markets || [],
      total: data.total || 0,
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
  const { markets, total } = await getTagData(tag);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${tag} — Polymarket Smart Money Trades`,
    description: `Notable trades for ${tag} markets on Polymarket.`,
    url: `${process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com"}/tag/${tagSlug(tag)}`,
    isPartOf: {
      "@type": "WebSite",
      name: "PolySpotter",
      url: process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com",
    },
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* Nav */}
      <nav className="mb-6" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to all markets
        </Link>
      </nav>

      {/* Header */}
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50">
          {tag}
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {total} market{total !== 1 ? "s" : ""} with notable smart money trades
        </p>
      </header>

      {/* Markets */}
      {markets.length > 0 ? (
        <section aria-label="Markets">
          <TagPageClient markets={markets} />
        </section>
      ) : (
        <div className="rounded-lg bg-white p-8 text-center text-gray-400 dark:bg-gray-900 dark:text-gray-500">
          No alerts found for &ldquo;{tag}&rdquo;.
        </div>
      )}
    </main>
  );
}
