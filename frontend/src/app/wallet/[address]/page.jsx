import { notFound } from "next/navigation";
import WalletPageClient from "./wallet-page-client";
import { computeTier } from "../../../lib/tiers";
import { walletPseudonym } from "../../../lib/pseudonym";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getWalletData(address) {
  try {
    const res = await fetch(`${API_URL}/api/wallets/${address}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function generateProfileSummary(data, pseudonym, tier) {
  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const parts = [`${pseudonym} is a`];
  if (tier) parts.push(`${tier.name}-tier`);
  parts.push("Polymarket trader");

  if (data.total_pnl != null) {
    const pnlStr = usdFmt.format(Math.abs(data.total_pnl));
    parts.push(
      `who has generated ${data.total_pnl >= 0 ? "+" : "-"}${pnlStr} in ${data.total_pnl >= 0 ? "profit" : "losses"}`
    );
  }

  if (data.win_rate != null) {
    parts.push(`with a ${Math.round(data.win_rate * 100)}% win rate`);
  }

  if (data.total_invested != null) {
    parts.push(`across ${usdFmt.format(data.total_invested)} invested on Polymarket`);
  }

  return parts.join(" ") + ".";
}

export async function generateMetadata({ params }) {
  const { address: rawAddress } = await params;
  const address = rawAddress.toLowerCase();
  const data = await getWalletData(address);

  const tier = data ? computeTier(data.win_rate, data.total_invested) : null;
  const pseudonym = data
    ? walletPseudonym(address, tier)
    : `${address.slice(0, 6)}...${address.slice(-4)}`;

  const descParts = [`Polymarket trader ${pseudonym}`];
  if (data?.win_rate != null)
    descParts.push(
      `with a ${Math.round(data.win_rate * 100)}% win rate`
    );
  if (data?.total_pnl != null) {
    const pnl = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(data.total_pnl);
    descParts.push(`and ${pnl} P&L`);
  }
  descParts.push(
    "— view positions and alerts on PolySpotter."
  );
  const description = descParts.join(" ");

  const title = tier
    ? `${pseudonym} — ${tier.name} Polymarket Trader`
    : `${pseudonym} — Polymarket Trader`;

  return {
    title,
    description,
    alternates: { canonical: `/wallet/${address}` },
    openGraph: {
      title,
      description,
      url: `/wallet/${address}`,
      type: "profile",
    },
    twitter: { card: "summary", title, description },
  };
}

export default async function WalletPage({ params }) {
  const { address: rawAddress } = await params;
  const address = rawAddress.toLowerCase();
  const data = await getWalletData(address);

  if (!data) notFound();

  const tier = computeTier(data.win_rate, data.total_invested);
  const pseudonym = walletPseudonym(address, tier);
  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const profileLd = {
    "@context": "https://schema.org",
    "@type": "ProfilePage",
    name: pseudonym,
    description: generateProfileSummary(data, pseudonym, tier),
    url: `${siteUrl}/wallet/${address}`,
    mainEntity: {
      "@type": "Person",
      name: pseudonym,
      identifier: address,
      url: `${siteUrl}/wallet/${address}`,
      description: tier
        ? `${tier.name}-tier Polymarket trader`
        : "Polymarket trader",
      sameAs: [`https://polygonscan.com/address/${address}`],
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
        name: pseudonym,
        item: `${siteUrl}/wallet/${address}`,
      },
    ],
  };

  const profileSummary = generateProfileSummary(data, pseudonym, tier);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(profileLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      {/* Server-rendered SEO content */}
      <div className="seo-content">
        <article>
          <nav aria-label="Breadcrumb">
            <a href="/">PolySpotter</a> &gt; <span>{pseudonym}</span>
          </nav>

          <h1>
            {pseudonym} — {tier ? `${tier.name} ` : ""}Polymarket Trader
          </h1>
          <p>{profileSummary}</p>

          <section>
            <h2>Trading Performance</h2>
            <dl>
              {data.win_rate != null && (
                <>
                  <dt>Win Rate</dt>
                  <dd>{Math.round(data.win_rate * 100)}%</dd>
                </>
              )}
              {data.total_pnl != null && (
                <>
                  <dt>Total P&amp;L</dt>
                  <dd>
                    {data.total_pnl >= 0 ? "+" : ""}
                    {usdFmt.format(data.total_pnl)}
                  </dd>
                </>
              )}
              {data.total_invested != null && (
                <>
                  <dt>Total Invested</dt>
                  <dd>{usdFmt.format(data.total_invested)}</dd>
                </>
              )}
              {tier && (
                <>
                  <dt>Tier</dt>
                  <dd>{tier.name}</dd>
                </>
              )}
            </dl>
          </section>
        </article>
      </div>

      <WalletPageClient wallet={data} address={address} />
    </>
  );
}
