import { redirect } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAlert(id) {
  try {
    const res = await fetch(`${API_URL}/api/alerts/${id}`, { next: { revalidate: 60 } });
    if (res.ok) return res.json();
  } catch {}
  return null;
}

export async function generateMetadata({ params }) {
  const { id } = await params;
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

  const alert = await getAlert(id);

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

  const alert = await getAlert(id);
  const conditionId = alert?.condition_id;

  if (conditionId) {
    redirect(`/market/${conditionId.slice(0, 7)}`);
  }

  redirect("/");
}
