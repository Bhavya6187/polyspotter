import Link from "next/link";
import { notFound } from "next/navigation";
import { API_URL } from "../../../lib/apiBase";
import { fetchJsonOr404 } from "../../../lib/fetchJson";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

// null only on a backend 404 (-> notFound()); other failures throw.
function getDigest(date) {
  return fetchJsonOr404(`${API_URL}/api/digest/${encodeURIComponent(date)}`, {
    next: { revalidate: 60 },
  });
}

function formatLongDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export async function generateMetadata({ params }) {
  const { date } = await params;
  const digest = await getDigest(date);
  if (!digest) return { title: "Digest not found" };
  return {
    title: digest.subject,
    description: digest.intro || "PolySpotter daily digest.",
    alternates: { canonical: `/digest/${date}` },
    openGraph: {
      title: digest.subject,
      description: digest.intro || "PolySpotter daily digest.",
      url: `${SITE_URL}/digest/${date}`,
      type: "article",
    },
  };
}

export default async function DigestDetailPage({ params }) {
  const { date } = await params;
  const digest = await getDigest(date);
  if (!digest) notFound();

  const sections = digest.content_json?.sections || [];

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <Link
        href="/digest"
        className="text-sm font-semibold"
        style={{ color: "var(--accent)" }}
      >
        ← All digests
      </Link>

      <header className="mb-8 mt-4">
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {formatLongDate(digest.digest_date)}
        </div>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          {digest.subject}
        </h1>
        {digest.intro ? (
          <p className="mt-3 text-base" style={{ color: "var(--text-secondary)" }}>
            {digest.intro}
          </p>
        ) : null}
      </header>

      {sections.map((section) => (
        <section key={section.key} className="mb-10">
          <h2
            className="mb-4 text-sm font-bold uppercase tracking-wide"
            style={{ color: "var(--text-muted)" }}
          >
            {section.title}
          </h2>
          <div className="flex flex-col gap-4">
            {section.items.map((item) => (
              <article
                key={item.event_slug}
                className="rounded-xl p-4"
                style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
              >
                <h3 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                  {item.headline}
                </h3>
                <div
                  className="mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-bold"
                  style={{ background: "var(--surface-1)", color: "var(--accent)" }}
                >
                  Leaning: {item.leaning}
                </div>
                <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {item.blurb}
                </p>
                {item.url ? (
                  <a
                    href={item.url}
                    className="mt-2 inline-block text-sm font-semibold"
                    style={{ color: "var(--accent)" }}
                  >
                    View market →
                  </a>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
