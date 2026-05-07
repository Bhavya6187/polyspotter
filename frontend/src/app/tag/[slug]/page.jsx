import Link from "next/link";
import TagPageClient from "./tag-page-client";
import TagPageHeader from "./tag-page-header";
import Ticker from "../../../components/Ticker";
import TagFilters from "../../../components/TagFilters";
import { marketSlug } from "../../../lib/slugify";

const VALID_RESOLVES = new Set(["6h", "24h", "7d"]);
const VALID_SEVERITIES = new Set(["6", "10", "15"]);

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

async function getTagEvents(tag) {
  // Multi-market events for this tag — shown as a strip above the markets
  // list so users can jump to the event hub instead of clicking through
  // each child market individually. Only first page; the markets list
  // below carries the long tail.
  try {
    const qs = new URLSearchParams({
      page: "1",
      per_page: "12",
      min_markets: "2",
      include_resolved: "true",
      tag,
    });
    const res = await fetch(`${API_URL}/api/events?${qs.toString()}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.events || [];
  } catch {
    return [];
  }
}

async function getTagData(tag, page = 1, resolves = "", severity = "") {
  try {
    const qs = new URLSearchParams({
      page: String(page),
      per_page: String(PER_PAGE),
      tag,
      // Smart-group: events with 2+ child markets render as one card, so the
      // tag list shows "Bayern–PSG" once instead of three near-identical rows.
      group_events: "true",
    });
    // When filtering by resolution window the user wants upcoming markets, so
    // drop include_resolved (which otherwise leaks past-resolved markets into
    // the window filter because the SQL only caps end_date upper-bound).
    if (resolves) qs.set("resolves_within", resolves);
    else qs.set("include_resolved", "true");
    if (severity) qs.set("min_score", severity);

    const res = await fetch(`${API_URL}/api/alerts/by-market?${qs.toString()}`, {
      next: { revalidate: 60 },
    });
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
  const sp = (await searchParams) || {};
  const page = Math.max(1, parseInt(sp.page) || 1);
  const resolves = VALID_RESOLVES.has(sp.resolves) ? sp.resolves : "";
  const severity = VALID_SEVERITIES.has(sp.severity) ? sp.severity : "";
  const tag = tagFromSlug(slug);
  const display = tagDisplayName(tag);

  // Only show the events strip on page 1 — paginated views are deeper into
  // a long tail where jumping back up to events feels disorienting.
  const showEventsStrip = page === 1;

  const [tagData, allTags, walletsRes, tagEvents] = await Promise.all([
    getTagData(tag, page, resolves, severity),
    getAllTags(),
    fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } })
      .then((r) => (r.ok ? r.json() : { wallets: [] }))
      .catch(() => ({ wallets: [] })),
    showEventsStrip ? getTagEvents(tag) : Promise.resolve([]),
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
    itemListElement: markets.map((m, i) => {
      const hasEventCtx = !!(m.event_title && m.event_slug);
      return {
        "@type": "ListItem",
        position: i + 1,
        name: hasEventCtx ? m.event_title : m.market_title,
        url: hasEventCtx
          ? `${siteUrl}/event/${encodeURIComponent(m.event_slug)}`
          : `${siteUrl}/market/${marketSlug(m.market_title, m.condition_id)}`,
      };
    }),
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

  const buildPageHref = (p) => {
    const qs = new URLSearchParams();
    if (p > 1) qs.set("page", String(p));
    if (resolves) qs.set("resolves", resolves);
    if (severity) qs.set("severity", severity);
    const q = qs.toString();
    return q ? `/tag/${tagSlug(tag)}?${q}` : `/tag/${tagSlug(tag)}`;
  };

  return (
    <>
      {page > 1 && <link rel="prev" href={buildPageHref(page - 1)} />}
      {page < totalPages && <link rel="next" href={buildPageHref(page + 1)} />}
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

      {/* Live ticker — hidden on mobile, duplicates feed */}
      <section aria-label="Live ticker" className="hidden sm:block mb-5 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
        <Ticker tag={tag} />
      </section>

      {/* Filters */}
      <section aria-label="Filters" className="mb-5">
        <TagFilters slug={tagSlug(tag)} resolves={resolves} severity={severity} />
      </section>

      {/* Multi-market events strip — only on page 1, hidden on deep pagination */}
      {tagEvents.length > 0 && (
        <section aria-label="Multi-market events" className="mb-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
            Multi-market events
          </h2>
          <div
            className="flex gap-3 overflow-x-auto pb-2"
            style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
          >
            {tagEvents.map((e) => {
              const titleText = e.title || e.slug;
              return (
                <a
                  key={e.slug}
                  href={`/event/${encodeURIComponent(e.slug)}`}
                  className="shrink-0 w-64 rounded-xl border p-4 transition-colors hover:opacity-90"
                  style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
                >
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    Event · {e.n_markets} market{e.n_markets !== 1 ? "s" : ""}
                  </div>
                  <div className="mt-1 line-clamp-2 font-medium" style={{ color: "var(--text-primary)" }}>
                    {titleText}
                  </div>
                  <div className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
                    {e.n_alerts} signal{e.n_alerts !== 1 ? "s" : ""}
                    {e.total_usd > 0 && ` · ${usdFmt.format(e.total_usd)} tracked`}
                  </div>
                </a>
              );
            })}
          </div>
        </section>
      )}

      {/* Server-rendered market list for crawlers */}
      {markets.length > 0 && (
        <div className="seo-content">
          <section>
            <h2>{display} Markets with Smart Money Signals</h2>
            <ol>
              {markets.map((m) => {
                const hasEventCtx = !!(m.event_title && m.event_slug);
                const href = hasEventCtx
                  ? `/event/${encodeURIComponent(m.event_slug)}`
                  : `/market/${marketSlug(m.market_title, m.condition_id)}`;
                const title = hasEventCtx ? m.event_title : m.market_title;
                const key = `${m.is_event ? "e" : "m"}:${m.is_event ? m.event_slug : m.condition_id}`;
                return (
                <li key={key}>
                  <a href={href}>
                    {title}
                  </a>{" "}
                  — {m.alert_count} signal{m.alert_count !== 1 ? "s" : ""},{" "}
                  {usdFmt.format(m.total_usd)} tracked
                  {m.alerts?.[0]?.llm_headline && (
                    <>. Latest: {m.alerts[0].llm_headline}</>
                  )}
                </li>
                );
              })}
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
            resolves={resolves}
            severity={severity}
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
