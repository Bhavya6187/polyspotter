import { redirect } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function generateMetadata({ params }) {
  const { id } = await params;

  let thesis = null;
  try {
    const res = await fetch(`${API_URL}/api/theses/${id}`, { next: { revalidate: 60 } });
    if (res.ok) thesis = await res.json();
  } catch {}

  const title = thesis?.thesis_headline || "Cross-Market Thesis";
  const description = thesis
    ? `${thesis.wallet?.slice(0, 8)}... is betting $${Math.round(thesis.total_usd).toLocaleString()} across ${thesis.markets?.length || 0} markets.`
    : "A smart money thesis detected across multiple Polymarket markets.";

  return {
    title: `${title} | PolySpotter`,
    description,
    openGraph: {
      title: `${title} | PolySpotter`,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | PolySpotter`,
      description,
    },
  };
}

export default async function ThesisPage({ params }) {
  // Redirect to homepage — thesis cards are displayed in the feed
  redirect("/");
}
