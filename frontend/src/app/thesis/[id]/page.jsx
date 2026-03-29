import { notFound } from "next/navigation";
import Link from "next/link";
import WalletBadge from "../../../components/WalletBadge";
import { marketSlug } from "../../../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getThesis(id) {
  try {
    const res = await fetch(`${API_URL}/api/theses/${id}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { id } = await params;
  const thesis = await getThesis(id);

  if (!thesis) {
    return { title: "Thesis Not Found" };
  }

  const title = thesis.thesis_headline || "Cross-Market Thesis";
  const marketCount = thesis.markets?.length || 0;
  const totalUsd = Math.round(thesis.total_usd || 0);
  const walletShort = thesis.wallet?.slice(0, 8) || "Unknown";

  const description = `"${title}" — ${walletShort}... is betting $${totalUsd.toLocaleString()} across ${marketCount} Polymarket markets on this cross-market thesis. View positions, entry prices, and wallet performance on PolySpotter.`;

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const thesisUrl = `${siteUrl}/thesis/${id}`;

  return {
    title,
    description,
    alternates: {
      canonical: `/thesis/${id}`,
    },
    openGraph: {
      title,
      description,
      type: "article",
      url: thesisUrl,
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function ThesisPage({ params }) {
  const { id } = await params;
  const thesis = await getThesis(id);

  if (!thesis) {
    notFound();
  }

  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const thesisUrl = `${siteUrl}/thesis/${id}`;
  const title = thesis.thesis_headline || "Cross-Market Thesis";
  const marketCount = thesis.markets?.length || 0;
  const totalUsd = thesis.total_usd || 0;

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: title,
    description: `${thesis.wallet?.slice(0, 8)}... is betting ${usdFmt.format(totalUsd)} across ${marketCount} markets.`,
    url: thesisUrl,
    mainEntityOfPage: { "@type": "WebPage", "@id": thesisUrl },
    author: {
      "@type": "Person",
      name: `Wallet ${thesis.wallet?.slice(0, 8)}...`,
      url: `${siteUrl}/wallet/${thesis.wallet}`,
    },
    publisher: {
      "@type": "Organization",
      name: "PolySpotter",
      url: siteUrl,
    },
    about: (thesis.markets || []).map((m) => ({
      "@type": "Thing",
      name: m.market_title,
      url: `${siteUrl}/market/${marketSlug(m.market_title, m.condition_id)}`,
    })),
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
        item: thesisUrl,
      },
    ],
  };

  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      {/* Breadcrumb nav */}
      <nav className="mb-6" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: "var(--text-muted)" }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
      </nav>

      {/* Header */}
      <header className="mb-6">
        <p
          className="text-[10px] uppercase tracking-wider font-bold mb-1"
          style={{ color: "#8b5cf6" }}
        >
          Cross-Market Thesis
        </p>
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          &ldquo;{title}&rdquo;
        </h1>
      </header>

      {/* Thesis explanation */}
      <p
        className="mb-6 text-sm leading-relaxed"
        style={{ color: "var(--text-secondary)" }}
      >
        This trader is expressing a view that{" "}
        {(thesis.markets || [])
          .slice(0, 3)
          .map((m) => m.market_title)
          .join(", ")}
        {marketCount > 3 ? `, and ${marketCount - 3} more` : ""}{" "}
        are correlated outcomes, committing {usdFmt.format(totalUsd)} to
        this thesis across {marketCount} prediction market
        {marketCount !== 1 ? "s" : ""} on Polymarket.
      </p>

      {/* Wallet + Stats */}
      <div
        className="rounded-xl p-4 mb-6"
        style={{
          background: "var(--surface-card)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="flex items-center justify-between flex-wrap gap-4">
          <WalletBadge
            wallet={thesis.wallet}
            winRate={thesis.win_rate}
            totalPnl={thesis.total_pnl}
            totalInvested={thesis.total_invested}
          />
          <div className="flex items-center gap-6">
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Total
              </p>
              <p
                className="text-lg font-bold"
                style={{ color: "var(--accent)", fontFamily: "var(--font-display)" }}
              >
                {usdFmt.format(totalUsd)}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Markets
              </p>
              <p
                className="text-lg font-bold"
                style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
              >
                {marketCount}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Market positions */}
      <section aria-label="Market positions">
        <h2 className="text-sm font-bold mb-3" style={{ color: "var(--text-secondary)" }}>
          Positions
        </h2>
        <ol className="flex flex-col gap-2">
          {(thesis.markets || []).map((m, i) => (
            <li key={m.condition_id || i}>
              <Link
                href={`/market/${marketSlug(m.market_title, m.condition_id)}`}
                className="flex items-center justify-between rounded-xl px-4 py-3 transition-colors"
                style={{
                  background: "var(--surface-1)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="flex items-center gap-3 min-w-0 mr-3">
                  <span
                    className="shrink-0 flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold"
                    style={{
                      background: "rgba(139,92,246,0.12)",
                      color: "#8b5cf6",
                    }}
                  >
                    {i + 1}
                  </span>
                  <span className="truncate text-sm" style={{ color: m.market_title ? "var(--text-primary)" : "var(--text-muted)" }}>
                    {m.market_title || `${m.condition_id.slice(0, 10)}…`}
                  </span>
                </div>
                <span
                  className="shrink-0 text-sm font-medium"
                  style={{ color: "var(--accent)", fontFamily: "var(--font-display)", whiteSpace: "nowrap" }}
                >
                  {usdFmt.format(m.usd_value)} @ {Math.round(m.entry_price * 100)}&cent;
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
