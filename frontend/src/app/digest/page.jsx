import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

export const metadata = {
  title: "Daily Digest",
  description:
    "PolySpotter daily digest — markets resolving today and the top smart-money plays this week on Polymarket.",
  alternates: { canonical: "/digest" },
  openGraph: {
    title: "Daily Digest · PolySpotter",
    description:
      "Markets resolving today and the top smart-money plays this week on Polymarket.",
    url: `${SITE_URL}/digest`,
    type: "website",
  },
};

async function getDigests() {
  try {
    const res = await fetch(`${API_URL}/api/digests`, { next: { revalidate: 60 } });
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return [];
  }
}

function formatLongDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function DigestIndexPage() {
  const digests = await getDigests();

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          Daily Digest
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
          Filed each morning — what resolves today and the top plays this week.
        </p>
      </header>

      {digests.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No digests yet — check back soon.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {digests.map((d) => (
            <li key={d.digest_date}>
              <Link
                href={`/digest/${d.digest_date}`}
                className="block rounded-xl p-4 transition-colors"
                style={{
                  background: "var(--surface-card)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {formatLongDate(d.digest_date)}
                </div>
                <div className="mt-1 font-semibold" style={{ color: "var(--text-primary)" }}>
                  {d.subject}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
