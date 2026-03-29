import Link from "next/link";
import { marketSlug } from "../../../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAlert(id) {
  try {
    const res = await fetch(`${API_URL}/api/alerts/${id}`, {
      next: { revalidate: 60 },
    });
    if (res.ok) return res.json();
  } catch {}
  return null;
}


export async function generateMetadata({ params }) {
  const { id } = await params;
  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";
  const alert = await getAlert(id);

  if (!alert) {
    return { title: "Alert Not Found", robots: { index: false } };
  }

  const title =
    alert.llm_headline || `Smart Money Alert: ${alert.market_title}`;
  const description =
    alert.llm_summary ||
    `$${(alert.total_usd || 0).toLocaleString()} smart money signal on ${alert.market_title}.`;

  return {
    title,
    description,
    robots: { index: false, follow: true },
    alternates: { canonical: `/alert/${id}` },
    openGraph: {
      title,
      description,
      url: `${siteUrl}/alert/${id}`,
      type: "article",
      images: [
        { url: `${siteUrl}/api/og/${id}`, width: 1200, height: 630 },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [`${siteUrl}/api/og/${id}`],
    },
  };
}

export default async function AlertPage({ params }) {
  const { id } = await params;
  const alert = await getAlert(id);

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  if (!alert) {
    return (
      <main
        className="mx-auto max-w-4xl px-4 py-12 text-center"
        style={{ color: "var(--text-primary)" }}
      >
        <h1 className="text-2xl font-bold mb-4">Alert Not Found</h1>
        <p style={{ color: "var(--text-muted)" }}>
          This alert may have expired or been removed.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block text-sm font-medium"
          style={{ color: "var(--accent)" }}
        >
          Back to PolySpotter
        </Link>
      </main>
    );
  }

  const title =
    alert.llm_headline || `Smart Money Alert: ${alert.market_title}`;
  const conditionId = alert.condition_id;
  const marketLink = conditionId
    ? `/market/${marketSlug(alert.market_title || "", conditionId)}`
    : "/";

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: title,
    description: alert.llm_summary || "",
    datePublished: alert.scanned_at || alert.created_at,
    image: `${siteUrl}/api/og/${id}`,
    author: {
      "@type": "Organization",
      name: "PolySpotter",
      url: siteUrl,
    },
    publisher: {
      "@type": "Organization",
      name: "PolySpotter",
      url: siteUrl,
    },
    about: {
      "@type": "Thing",
      name: alert.market_title,
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
        name: alert.market_title || "Market",
        item: `${siteUrl}${marketLink}`,
      },
      {
        "@type": "ListItem",
        position: 3,
        name: "Alert",
        item: `${siteUrl}/alert/${id}`,
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

      {/* Breadcrumb */}
      <nav className="mb-6" aria-label="Breadcrumb">
        <Link
          href="/"
          className="text-sm font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          PolySpotter
        </Link>
        <span className="mx-1.5 text-sm" style={{ color: "var(--text-muted)" }}>
          /
        </span>
        <Link
          href={marketLink}
          className="text-sm font-medium"
          style={{ color: "var(--text-muted)" }}
        >
          {alert.market_title || "Market"}
        </Link>
      </nav>

      {/* Alert type badge */}
      <div className="mb-2">
        <span
          className="inline-block rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
          style={{
            background:
              alert.alert_type === "cluster"
                ? "rgba(139,92,246,0.15)"
                : "rgba(34,197,94,0.15)",
            color:
              alert.alert_type === "cluster" ? "#8b5cf6" : "#22c55e",
          }}
        >
          {alert.alert_type === "cluster"
            ? "Coordinated Flow"
            : "Smart Money Signal"}
        </span>
        {alert.composite_score != null && (
          <span
            className="ml-2 text-xs font-medium"
            style={{ color: "var(--text-muted)" }}
          >
            Score: {alert.composite_score.toFixed(1)}
          </span>
        )}
      </div>

      {/* Headline */}
      <h1
        className="text-2xl font-bold mb-4"
        style={{ color: "var(--text-primary)" }}
      >
        {title}
      </h1>

      {/* Market image + description */}
      {(alert.market_image || alert.market_description) && (
        <div
          className="rounded-xl overflow-hidden mb-6"
          style={{
            background: "var(--surface-card)",
            border: "1px solid var(--border)",
          }}
        >
          {alert.market_image && (
            <div className="relative w-full" style={{ aspectRatio: "16/9" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={alert.market_image}
                alt={alert.market_title || "Market"}
                className="w-full h-full object-cover"
              />
            </div>
          )}
          {alert.market_description && (
            <div className="px-4 py-3">
              <p
                className="text-sm leading-relaxed"
                style={{ color: "var(--text-secondary)" }}
              >
                {alert.market_description}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Summary */}
      {alert.llm_summary && (
        <p
          className="text-base leading-relaxed mb-4"
          style={{ color: "var(--text-secondary)" }}
        >
          {alert.llm_summary}
        </p>
      )}

      {/* Key metrics */}
      <div
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6 rounded-xl p-4"
        style={{
          background: "var(--surface-card)",
          border: "1px solid var(--border)",
        }}
      >
        <div>
          <p
            className="text-[10px] uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Total
          </p>
          <p
            className="text-lg font-bold"
            style={{
              color: "var(--accent)",
              fontFamily: "var(--font-display)",
            }}
          >
            {usdFmt.format(alert.total_usd || 0)}
          </p>
        </div>
        <div>
          <p
            className="text-[10px] uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Trades
          </p>
          <p
            className="text-lg font-bold"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            {alert.trade_count || 1}
          </p>
        </div>
        {alert.win_rate != null && (
          <div>
            <p
              className="text-[10px] uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Win Rate
            </p>
            <p
              className="text-lg font-bold"
              style={{
                color: "var(--text-primary)",
                fontFamily: "var(--font-display)",
              }}
            >
              {Math.round(alert.win_rate * 100)}%
            </p>
          </div>
        )}
        {alert.total_pnl != null && (
          <div>
            <p
              className="text-[10px] uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Wallet P&amp;L
            </p>
            <p
              className="text-lg font-bold"
              style={{
                color: alert.total_pnl >= 0 ? "#22c55e" : "#ef4444",
                fontFamily: "var(--font-display)",
              }}
            >
              {alert.total_pnl >= 0 ? "+" : ""}
              {usdFmt.format(alert.total_pnl)}
            </p>
          </div>
        )}
      </div>

      {/* Analysis bullets */}
      {alert.llm_bullets?.length > 0 && (
        <section className="mb-6">
          <h2
            className="text-sm font-bold mb-2"
            style={{ color: "var(--text-secondary)" }}
          >
            Analysis
          </h2>
          <ul className="space-y-1.5">
            {alert.llm_bullets.map((b, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                <span
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: "var(--accent)" }}
                />
                {b}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Copy trade action */}
      {alert.llm_copy_action?.outcome && (
        <div
          className="rounded-xl p-4 mb-6"
          style={{
            background: "var(--surface-1)",
            border: "1px solid var(--border)",
          }}
        >
          <p
            className="text-[10px] uppercase tracking-wider mb-1"
            style={{ color: "var(--text-muted)" }}
          >
            Copy Trade
          </p>
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <strong>
              Buy {alert.llm_copy_action.outcome}
            </strong>{" "}
            at {Math.round((alert.llm_copy_action.entry_price || 0) * 100)}
            &cent;
          </p>
        </div>
      )}

      {/* Tags */}
      {alert.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-6">
          {alert.tags.map((tag) => (
            <Link
              key={tag}
              href={`/tag/${encodeURIComponent(tag.toLowerCase().replace(/\s+/g, "-"))}`}
              className="rounded-full px-2.5 py-0.5 text-[10px] font-medium"
              style={{
                background: "var(--surface-1)",
                color: "var(--text-muted)",
                border: "1px solid var(--border)",
              }}
            >
              {tag}
            </Link>
          ))}
        </div>
      )}

      {/* Link to full market page */}
      <div
        className="rounded-xl p-4 text-center"
        style={{
          background: "var(--surface-card)",
          border: "1px solid var(--border)",
        }}
      >
        <Link
          href={marketLink}
          className="text-sm font-medium"
          style={{ color: "var(--accent)" }}
        >
          View all alerts for {alert.market_title || "this market"} &rarr;
        </Link>
      </div>

      {/* Timestamp */}
      {alert.scanned_at && (
        <p className="mt-4 text-xs" style={{ color: "var(--text-muted)" }}>
          Detected{" "}
          {new Date(alert.scanned_at).toLocaleDateString("en-US", {
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
          })}
        </p>
      )}
    </main>
  );
}
