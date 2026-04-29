import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

async function getArticle(date, slug) {
  try {
    const res = await fetch(
      `${API_URL}/api/articles/by-slug/${encodeURIComponent(date)}/${encodeURIComponent(slug)}`,
      { next: { revalidate: 60 } },
    );
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function coverUrlFor(runId) {
  return `${API_URL}/api/articles/${encodeURIComponent(runId)}/cover.png`;
}

export async function generateMetadata({ params }) {
  const { date, slug } = await params;
  const article = await getArticle(date, slug);
  if (!article) return {};

  const url = `${SITE_URL}/article/${date}/${slug}`;
  const coverUrl = article.has_cover ? coverUrlFor(article.run_id) : null;
  const images = coverUrl
    ? [{ url: coverUrl, alt: article.cover_alt_text || article.headline }]
    : [];

  return {
    title: `${article.headline} · PolySpotter`,
    description: article.subhead,
    alternates: { canonical: url },
    openGraph: {
      type: "article",
      title: article.headline,
      description: article.subhead,
      url,
      publishedTime: article.published_date,
      images,
    },
    twitter: {
      card: "summary_large_image",
      title: article.headline,
      description: article.subhead,
      images: coverUrl ? [coverUrl] : [],
    },
  };
}

function MarkdownLink({ href, children, ...props }) {
  if (!href) return <a {...props}>{children}</a>;
  const isInternal =
    href.startsWith("/") || href.startsWith(SITE_URL);
  if (isInternal) {
    const path = href.startsWith(SITE_URL) ? href.slice(SITE_URL.length) : href;
    return (
      <Link href={path} className="text-indigo-400 hover:text-indigo-300 underline">
        {children}
      </Link>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener nofollow"
      className="text-indigo-400 hover:text-indigo-300 underline"
    >
      {children}
    </a>
  );
}

export default async function ArticlePage({ params }) {
  const { date, slug } = await params;
  const article = await getArticle(date, slug);
  if (!article) notFound();

  const coverUrl = article.has_cover ? coverUrlFor(article.run_id) : null;
  const url = `${SITE_URL}/article/${date}/${slug}`;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: article.headline,
    datePublished: article.published_date,
    description: article.subhead,
    image: coverUrl ? [coverUrl] : undefined,
    author: { "@type": "Organization", name: "PolySpotter" },
    publisher: {
      "@type": "Organization",
      name: "PolySpotter",
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/logo.png`,
      },
    },
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
  };

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <header className="mb-10">
        <p className="text-sm text-zinc-500">
          <time dateTime={article.published_date}>
            {new Date(article.published_date).toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </time>
        </p>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">
          {article.headline}
        </h1>
        <p className="mt-4 text-xl text-zinc-300">{article.subhead}</p>
      </header>

      {coverUrl && (
        <div className="mb-10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={coverUrl}
            alt={article.cover_alt_text || article.headline}
            className="w-full rounded-lg"
          />
        </div>
      )}

      <article className="prose prose-invert max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{ a: MarkdownLink }}
        >
          {article.body_markdown}
        </ReactMarkdown>
      </article>

      {article.posted_url && (
        <footer className="mt-12 border-t border-zinc-800 pt-6 text-sm text-zinc-500">
          <a
            href={article.posted_url}
            target="_blank"
            rel="noopener nofollow"
            className="hover:text-zinc-300"
          >
            Discuss this on X →
          </a>
        </footer>
      )}
    </main>
  );
}
