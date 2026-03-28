import WalletPageClient from "./wallet-page-client";

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
  const { address } = await params;
  return { title: `Wallet ${address.slice(0, 8)}... | PolySpotter` };
}

export default async function WalletPage({ params }) {
  const { address } = await params;
  const data = await getWalletData(address);

  if (!data) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12 text-center" style={{ color: "var(--text-muted)" }}>
        Wallet not found
      </div>
    );
  }

  return <WalletPageClient wallet={data} address={address} />;
}
