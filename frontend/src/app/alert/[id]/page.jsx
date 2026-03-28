import { redirect } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function generateMetadata({ params }) {
  const { id } = await params;
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  let alert = null;
  try {
    const res = await fetch(`${API_URL}/api/alerts/${id}`, { next: { revalidate: 60 } });
    if (res.ok) alert = await res.json();
  } catch {}

  const title = alert?.market_title || "Alert";
  const description = alert?.llm_summary || alert?.llm_headline || "Smart money signal detected on Polymarket.";

  return {
    title: `${title} | PolySpotter`,
    description,
    openGraph: {
      title: `${title} | PolySpotter`,
      description,
      images: [`${siteUrl}/api/og/${id}`],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | PolySpotter`,
      description,
    },
  };
}

export default async function AlertPage({ params }) {
  const { id } = await params;

  let conditionId = null;
  try {
    const res = await fetch(`${API_URL}/api/alerts/${id}`, { next: { revalidate: 60 } });
    if (res.ok) {
      const alert = await res.json();
      conditionId = alert.condition_id;
    }
  } catch {}

  if (conditionId) {
    redirect(`/market/${conditionId.slice(0, 7)}`);
  }

  redirect("/");
}
