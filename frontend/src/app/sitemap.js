// Regenerate at most hourly — avoids hammering the API on every crawler hit
// while keeping the sitemap fresh enough for Google's typical crawl cadence.
export const revalidate = 3600;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const FETCH_OPTS = { next: { revalidate: 3600 } };

// Market pages live in a dedicated /sitemap-markets.xml route. They're the
// largest section (~19k URLs) and paging them through the heavy by-market
// endpoint here was timing out the build's static-generation step, so they
// moved to a force-dynamic route backed by the slim /api/markets/sitemap
// endpoint — same split as wallets (/sitemap-wallets.xml). Keeping them out
// of this build-prerendered sitemap is what keeps the build fast.

async function getArticleEntries() {
  try {
    const res = await fetch(`${API_URL}/api/articles`, FETCH_OPTS);
    if (!res.ok) return [];
    const articles = await res.json();
    return articles.map((a) => ({
      url: `${SITE_URL}/article/${a.published_date}/${a.event_slug}`,
      lastModified: new Date(a.published_date),
      changeFrequency: "weekly",
      priority: 0.8,
    }));
  } catch {
    return [];
  }
}

async function getEventEntries() {
  // Only emit URLs for events with 2+ child markets — single-market events
  // are folded to /market via canonical, so indexing them as /event would
  // be a duplicate-content signal. Sports games and election-style events
  // (which always have spread/total/winner-per-candidate variants) make
  // up the bulk of the multi-market backlog and are the strongest SEO bets.
  try {
    const allEvents = [];
    let page = 1;
    let totalPages = 1;
    while (page <= totalPages) {
      const res = await fetch(
        `${API_URL}/api/events?per_page=200&page=${page}&min_markets=2&include_resolved=true`,
        FETCH_OPTS
      );
      if (!res.ok) break;
      const data = await res.json();
      allEvents.push(...(data.events || []));
      const total = data.total || 0;
      totalPages = Math.ceil(total / 200);
      page++;
      // Hard cap to prevent runaway loops; 5000 events is more than we
      // can realistically index and well above current scale.
      if (page > 25) break;
    }
    return allEvents.map((e) => {
      const isResolved =
        e.end_date && new Date(e.end_date) <= new Date();
      return {
        url: `${SITE_URL}/event/${encodeURIComponent(e.slug)}`,
        lastModified: e.last_alert_at
          ? new Date(e.last_alert_at)
          : (e.end_date ? new Date(e.end_date) : new Date()),
        changeFrequency: isResolved ? "monthly" : "hourly",
        priority: isResolved ? 0.5 : 0.7,
      };
    });
  } catch {
    return [];
  }
}

async function getTagEntries() {
  try {
    const res = await fetch(`${API_URL}/api/tags`, FETCH_OPTS);
    if (!res.ok) return [];
    const data = await res.json();
    const tags = data?.tags || data || [];
    return tags.map((t) => {
      const tag = typeof t === "string" ? t : t.tag;
      const slug = tag.toLowerCase().replace(/\s+/g, "-");
      return {
        url: `${SITE_URL}/tag/${encodeURIComponent(slug)}`,
        lastModified: new Date(),
        changeFrequency: "daily",
        priority: 0.7,
      };
    });
  } catch {
    return [];
  }
}

// Theses are intentionally excluded from the sitemap. As of 2026-04-19 the DB
// has ~17k thesis rows but 0 of them have thesis_headline populated, so every
// thesis page renders as the generic "Cross-Market Thesis" title — pure thin/
// duplicate content. Indexing them would dilute site authority. Additionally,
// paginating through all theses (backend caps per_page=50 → 340 sequential
// pages) was causing the /sitemap.xml static-generation step to time out.
//
// When the LLM starts writing thesis_headline values, restore this section
// and filter on `t.thesis_headline && t.markets?.length > 0`.

// Wallets are served from a separate sitemap at /sitemap-wallets.xml.
// They're unbounded in count and updated on a different cadence than content
// pages, so isolating them keeps this main sitemap small and fast.

export default async function sitemap() {
  const staticPages = [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: "hourly",
      priority: 1.0,
    },
  ];

  // Run all sections in parallel. Each section is self-contained with its own
  // try/catch so one failing upstream (e.g. a /api/theses timeout) degrades
  // only that section instead of collapsing the entire sitemap to the homepage.
  const [tags, articles, events] = await Promise.all([
    getTagEntries(),
    getArticleEntries(),
    getEventEntries(),
  ]);

  return [...staticPages, ...articles, ...events, ...tags];
}
