import { notFound } from "next/navigation";
import WalletPageClient from "./wallet-page-client";
import { computeTier } from "../../../lib/tiers";
import { walletPseudonym } from "../../../lib/pseudonym";

export const revalidate = 60;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getWalletData(address) {
  try {
    const res = await fetch(`${API_URL}/api/wallets/${address}`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { address: rawAddress } = await params;
  const address = rawAddress.toLowerCase();
  const data = await getWalletData(address);

  const tier = data ? computeTier(data.win_rate, data.total_invested) : null;
  const pseudonym = data ? walletPseudonym(address, tier) : `${address.slice(0, 6)}...${address.slice(-4)}`;

  const descParts = [`Polymarket trader ${pseudonym}`];
  if (data?.win_rate != null) descParts.push(`with a ${Math.round(data.win_rate * 100)}% win rate`);
  if (data?.total_pnl != null) {
    const pnl = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(data.total_pnl);
    descParts.push(`and ${pnl} P&L`);
  }
  descParts.push("— view positions and alerts on PolySpotter.");
  const description = descParts.join(" ");

  const title = `${pseudonym} — Polymarket Trader`;

  return {
    title,
    description,
    alternates: { canonical: `/wallet/${address}` },
    openGraph: { title, description, url: `/wallet/${address}`, type: "profile" },
    twitter: { card: "summary", title, description },
  };
}

export default async function WalletPage({ params }) {
  const { address: rawAddress } = await params;
  const address = rawAddress.toLowerCase();
  const data = await getWalletData(address);

  if (!data) notFound();

  return <WalletPageClient wallet={data} address={address} />;
}
