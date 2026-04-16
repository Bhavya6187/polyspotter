import HomeClient from "./home-client";
import { marketSlug } from "../lib/slugify";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

async function getHomeData() {
  try {
    const [marketsRes, tagsRes, thesesRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/alerts/by-market?page=1&per_page=20`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/theses?page=1&per_page=5`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);

    const marketsData = marketsRes.ok ? await marketsRes.json() : null;
    const tagsData = tagsRes.ok ? await tagsRes.json() : null;
    const thesesData = thesesRes.ok ? await thesesRes.json() : null;
    const walletsData = walletsRes.ok ? await walletsRes.json() : null;

    return {
      markets: marketsData?.markets || [],
      total: marketsData?.total || 0,
      tags: tagsData?.tags || tagsData || [],
      theses: thesesData?.theses || thesesData || [],
      topWallets: walletsData?.wallets || [],
    };
  } catch {
    return { markets: [], total: 0, tags: [], theses: [], topWallets: [] };
  }
}

export default async function HomePage() {
  const { markets, total, tags, theses, topWallets } = await getHomeData();

  const visibleTags = (Array.isArray(tags) ? tags : []).filter((t) => {
    const name = typeof t === "string" ? t : t.tag;
    return name && name !== "Hide From New";
  });

  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Notable Polymarket Trades",
    description:
      "Large prediction market bets from sharp wallets, updated in real time.",
    numberOfItems: markets.length,
    itemListElement: markets.slice(0, 10).map((m, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: m.market_title,
      url: `${SITE_URL}/market/${marketSlug(m.market_title, m.condition_id)}`,
    })),
  };

  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: "What is PolySpotter?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "PolySpotter is a real-time tracker that surfaces notable trades on Polymarket prediction markets. It detects large bets ($3,000+) from sharp bettors, coordinated wallet flow, and high-conviction positioning across all active markets.",
        },
      },
      {
        "@type": "Question",
        name: "How does PolySpotter detect smart money?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "PolySpotter uses 9 detection strategies including wallet win-rate tracking, new-wallet large bets, timing relative to resolution, volume spike detection, wallet clustering, concentrated one-sided flow, price impact analysis, and correlated cross-market positioning.",
        },
      },
      {
        "@type": "Question",
        name: "What are prediction markets?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "Prediction markets are platforms where traders buy and sell shares on the outcomes of real-world events. Prices reflect the crowd's estimated probability of each outcome. Polymarket is the largest prediction market platform, covering politics, sports, crypto, and current events.",
        },
      },
      {
        "@type": "Question",
        name: "What makes a trade notable on PolySpotter?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "A trade is flagged as notable when it meets criteria such as: the bet is $3,000 or larger, the wallet has a high historical win rate, multiple wallets are placing coordinated bets, or the trade causes significant price movement. Each alert receives a composite score ranking its significance.",
        },
      },
      {
        "@type": "Question",
        name: "How often is PolySpotter data updated?",
        acceptedAnswer: {
          "@type": "Answer",
          text: "PolySpotter scans Polymarket trades continuously and updates alerts in near real-time. Market data is refreshed every 60 seconds.",
        },
      },
    ],
  };

  const navLd = {
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    name: "Main Navigation",
    hasPart: [
      { "@type": "WebPage", name: "Markets", url: `${SITE_URL}` },
      ...visibleTags.slice(0, 8).map((t) => {
        const name = typeof t === "string" ? t : t.tag;
        const slug = name.toLowerCase().replace(/\s+/g, "-");
        return { "@type": "WebPage", name, url: `${SITE_URL}/tag/${encodeURIComponent(slug)}` };
      }),
    ],
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "Home",
        item: SITE_URL,
      },
    ],
  };

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(navLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      {/* Server-rendered SEO content — visible to crawlers, hidden for JS users */}
      <div className="seo-content">
        <article>
          <h1>Polymarket Whale Trades &amp; Smart Money Alerts</h1>
          <p>
            PolySpotter tracks notable trades on Polymarket prediction markets in
            real time. We surface large bets ($3,000+) from sharp bettors,
            coordinated wallet flow, and high-conviction positioning — so you can
            follow the smart money. Currently tracking {total} markets with smart
            money signals across {visibleTags.length} categories.
          </p>

          <nav aria-label="Market categories">
            <h2>Browse by Category</h2>
            <ul>
              {visibleTags.map((t) => {
                const name = typeof t === "string" ? t : t.tag;
                const count = typeof t === "string" ? 0 : t.alert_count;
                const slug = name.toLowerCase().replace(/\s+/g, "-");
                return (
                  <li key={name}>
                    <a href={`/tag/${encodeURIComponent(slug)}`}>
                      {name} ({count} signals)
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>

          <section>
            <h2>Top Smart Money Markets</h2>
            <ol>
              {markets.slice(0, 10).map((m) => (
                <li key={m.condition_id}>
                  <a
                    href={`/market/${marketSlug(m.market_title, m.condition_id)}`}
                  >
                    {m.market_title}
                  </a>{" "}
                  — {m.alert_count} signal{m.alert_count !== 1 ? "s" : ""},{" "}
                  {usdFmt.format(m.total_usd)} tracked
                </li>
              ))}
            </ol>
          </section>

          {topWallets.length > 0 && (
            <section>
              <h2>Top Smart Money Wallets</h2>
              <ol>
                {topWallets.map((w) => (
                  <li key={w.wallet}>
                    <a href={`/wallet/${w.wallet}`}>
                      {w.wallet.slice(0, 6)}...{w.wallet.slice(-4)}
                    </a>{" "}
                    — {w.alert_count} signal{w.alert_count !== 1 ? "s" : ""}
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section>
            <h2>Frequently Asked Questions</h2>

            <h3>What is PolySpotter?</h3>
            <p>
              PolySpotter is a real-time tracker that surfaces notable trades on
              Polymarket prediction markets. It detects large bets ($3,000+) from
              sharp bettors, coordinated wallet flow, and high-conviction
              positioning across all active markets.
            </p>

            <h3>How does PolySpotter detect smart money?</h3>
            <p>
              PolySpotter uses 9 detection strategies including wallet win-rate
              tracking, new-wallet large bets, timing relative to resolution,
              volume spike detection, wallet clustering, concentrated one-sided
              flow, price impact analysis, and correlated cross-market
              positioning.
            </p>

            <h3>What are prediction markets?</h3>
            <p>
              Prediction markets are platforms where traders buy and sell shares
              on the outcomes of real-world events. Prices reflect the crowd's
              estimated probability of each outcome. Polymarket is the largest
              prediction market platform, covering politics, sports, crypto, and
              current events.
            </p>

            <h3>What makes a trade notable on PolySpotter?</h3>
            <p>
              A trade is flagged as notable when it meets criteria such as: the
              bet is $3,000 or larger, the wallet has a high historical win rate,
              multiple wallets are placing coordinated bets, or the trade causes
              significant price movement. Each alert receives a composite score
              ranking its significance.
            </p>

            <h3>How often is PolySpotter data updated?</h3>
            <p>
              PolySpotter scans Polymarket trades continuously and updates alerts
              in near real-time. Market data is refreshed every 60 seconds.
            </p>
          </section>
        </article>
      </div>

      <HomeClient
        initialMarkets={markets}
        initialTotal={total}
        tags={tags}
        initialTheses={theses}
        topWallets={topWallets}
      />
    </>
  );
}
