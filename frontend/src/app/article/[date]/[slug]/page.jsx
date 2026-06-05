import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

const MONO = { fontFamily: "var(--font-display)" };

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

async function getArticleIndex() {
  try {
    const res = await fetch(`${API_URL}/api/articles`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    return await res.json();
  } catch {
    return [];
  }
}

function coverUrlFor(runId) {
  return `${API_URL}/api/articles/${encodeURIComponent(runId)}/cover.png`;
}

function readingTimeMinutes(markdown) {
  if (!markdown) return 1;
  const words = markdown.trim().split(/\s+/).length;
  return Math.max(1, Math.round(words / 220));
}

function formatLongDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatShortDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
  });
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

function Crosshair({ className = "", flipX = false, flipY = false, style }) {
  const tx = flipX ? "scaleX(-1)" : "";
  const ty = flipY ? "scaleY(-1)" : "";
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={className}
      style={{ ...style, transform: `${tx} ${ty}`.trim() || undefined }}
    >
      <path
        d="M0 1 H10 M1 0 V10"
        stroke="currentColor"
        strokeWidth="1"
        fill="none"
      />
    </svg>
  );
}

function MarkdownLink({ href, children, ...props }) {
  if (!href) return <a {...props}>{children}</a>;
  const isInternal = href.startsWith("/") || href.startsWith(SITE_URL);
  if (isInternal) {
    const path = href.startsWith(SITE_URL) ? href.slice(SITE_URL.length) : href;
    return (
      <Link href={path} className="dispatch-prose-link">
        {children}
      </Link>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener nofollow"
      className="dispatch-prose-link"
    >
      {children}
    </a>
  );
}

const markdownComponents = {
  a: MarkdownLink,
  h1: ({ children }) => <h1 className="dispatch-h1">{children}</h1>,
  h2: ({ children }) => <h2 className="dispatch-h2">{children}</h2>,
  h3: ({ children }) => <h3 className="dispatch-h3">{children}</h3>,
  p: ({ children }) => <p>{children}</p>,
  ul: ({ children }) => <ul className="dispatch-list">{children}</ul>,
  ol: ({ children }) => <ol className="dispatch-list dispatch-list-ordered">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="dispatch-pullquote">{children}</blockquote>
  ),
  hr: () => <hr className="dispatch-rule" />,
  strong: ({ children }) => <strong>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  code: ({ children }) => <code className="dispatch-code">{children}</code>,
  pre: ({ children }) => <pre className="dispatch-pre">{children}</pre>,
  img: ({ src, alt }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt || ""} className="dispatch-inline-img" />
  ),
};

export default async function ArticlePage({ params }) {
  const { date, slug } = await params;
  const [article, articleIndex] = await Promise.all([
    getArticle(date, slug),
    getArticleIndex(),
  ]);
  if (!article) notFound();

  const coverUrl = article.has_cover ? coverUrlFor(article.run_id) : null;
  const url = `${SITE_URL}/article/${date}/${slug}`;
  const minutes = readingTimeMinutes(article.body_markdown);

  const total = articleIndex.length;
  const idxInList = articleIndex.findIndex(
    (a) => a.event_slug === slug && a.published_date === date,
  );
  const dispatchNo =
    idxInList >= 0 ? String(total - idxInList).padStart(4, "0") : null;

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
    <main
      className="min-h-screen"
      style={{ background: "var(--surface-0)", color: "var(--text-primary)" }}
    >
      <ArticlePageStyles />

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <div className="dispatch-page-bg relative">
        {/* Top wire bar */}
        <div className="border-b" style={{ borderColor: "var(--border)" }}>
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <Link
              href="/articles"
              className="dispatch-back inline-flex items-center gap-2 text-[11px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.28em",
                color: "var(--text-secondary)",
              }}
            >
              <span aria-hidden>←</span>
              <span>Back to wire</span>
            </Link>
            <div
              className="hidden items-center gap-3 text-[10px] uppercase md:flex"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-muted)",
              }}
            >
              <span>Wire / Dispatch</span>
              <span aria-hidden style={{ opacity: 0.5 }}>{"////"}</span>
              <span>{formatLongDate(article.published_date)}</span>
            </div>
          </div>
        </div>

        {/* Masthead */}
        <header className="relative mx-auto max-w-6xl px-6 pb-10 pt-16 md:pb-14 md:pt-20">
          <Crosshair
            className="absolute left-4 top-4 size-4"
            style={{ color: "var(--text-muted)" }}
          />
          <Crosshair
            flipX
            className="absolute right-4 top-4 size-4"
            style={{ color: "var(--text-muted)" }}
          />

          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px] uppercase"
            style={{
              ...MONO,
              letterSpacing: "0.3em",
              color: "var(--text-muted)",
            }}
          >
            <span
              className="size-1.5 rounded-full animate-pulse-live"
              style={{ background: "var(--accent)" }}
            />
            <span style={{ color: "var(--accent)" }}>Filed dispatch</span>
            {dispatchNo && (
              <>
                <span style={{ opacity: 0.4 }}>·</span>
                <span>№ {dispatchNo}</span>
              </>
            )}
            <span style={{ opacity: 0.4 }}>·</span>
            <time
              dateTime={article.published_date}
              style={{ color: "var(--text-secondary)" }}
            >
              {formatLongDate(article.published_date)}
            </time>
            <span style={{ opacity: 0.4 }}>·</span>
            <span>{minutes} min read</span>
          </div>

          <h1
            className="mt-7 text-balance font-semibold leading-[1.02] tracking-tight"
            style={{
              color: "var(--text-primary)",
              fontSize: "clamp(2.25rem, 6vw, 4.5rem)",
              fontFamily: "var(--font-body)",
            }}
          >
            {article.headline}
          </h1>

          {article.subhead && (
            <p
              className="mt-6 max-w-3xl text-pretty text-xl leading-relaxed md:text-2xl"
              style={{ color: "var(--text-secondary)" }}
            >
              {article.subhead}
            </p>
          )}

          <dl
            className="mt-10 grid grid-cols-2 gap-4 border-t pt-5 md:grid-cols-4"
            style={{ ...MONO, borderColor: "var(--border)" }}
          >
            {[
              {
                label: "Filed",
                value: formatShortDate(article.published_date),
              },
              {
                label: "Dispatch",
                value: dispatchNo ? `№ ${dispatchNo}` : "—",
              },
              { label: "Length", value: `${minutes} min` },
              {
                label: "Bureau",
                value: "Polyspotter",
              },
            ].map((s) => (
              <div key={s.label}>
                <dt
                  className="text-[10px] uppercase"
                  style={{
                    letterSpacing: "0.3em",
                    color: "var(--text-muted)",
                  }}
                >
                  {s.label}
                </dt>
                <dd
                  className="mt-1.5 text-base tracking-[0.06em] md:text-lg"
                  style={{ color: "var(--text-primary)" }}
                >
                  {s.value}
                </dd>
              </div>
            ))}
          </dl>
        </header>

        {/* Cover image — framed */}
        {coverUrl && (
          <section className="mx-auto max-w-6xl px-6 pb-12">
            <figure className="relative">
              <Crosshair
                className="dispatch-frame-mark absolute -left-1 -top-1 size-3.5"
                style={{ color: "var(--accent)" }}
              />
              <Crosshair
                flipX
                className="dispatch-frame-mark absolute -right-1 -top-1 size-3.5"
                style={{ color: "var(--accent)" }}
              />
              <Crosshair
                flipY
                className="dispatch-frame-mark absolute -bottom-1 -left-1 size-3.5"
                style={{ color: "var(--accent)" }}
              />
              <Crosshair
                flipX
                flipY
                className="dispatch-frame-mark absolute -bottom-1 -right-1 size-3.5"
                style={{ color: "var(--accent)" }}
              />
              <div
                className="overflow-hidden border"
                style={{ borderColor: "var(--border)" }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={coverUrl}
                  alt={article.cover_alt_text || article.headline}
                  className="w-full"
                />
              </div>
              <figcaption
                className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[10px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.3em",
                  color: "var(--text-muted)",
                }}
              >
                <span style={{ color: "var(--text-secondary)" }}>
                  Plate / Visual evidence
                </span>
                <span className="font-normal normal-case tracking-normal" style={{ fontFamily: "var(--font-body)", color: "var(--text-muted)" }}>
                  {article.cover_alt_text || "Generated cover."}
                </span>
              </figcaption>
            </figure>
          </section>
        )}

        {/* Body */}
        <section className="mx-auto max-w-6xl px-6">
          <div className="grid grid-cols-12 gap-x-6 md:gap-x-12">
            {/* Side rail */}
            <aside className="hidden md:col-span-3 md:block">
              <div className="sticky top-8 space-y-6">
                <div
                  className="border-l pl-5"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div
                    className="text-[10px] uppercase"
                    style={{
                      ...MONO,
                      letterSpacing: "0.32em",
                      color: "var(--text-muted)",
                    }}
                  >
                    From the wire
                  </div>
                  <p
                    className="mt-3 text-sm leading-relaxed"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    A daily dispatch on notable Polymarket trades. Sharp
                    bettors, coordinated flow, and the prediction-market
                    signals worth a second look.
                  </p>
                </div>

                {Array.isArray(article.alert_ids) &&
                  article.alert_ids.length > 0 && (
                    <div
                      className="border-l pl-5"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <div
                        className="text-[10px] uppercase"
                        style={{
                          ...MONO,
                          letterSpacing: "0.32em",
                          color: "var(--text-muted)",
                        }}
                      >
                        Source signals
                      </div>
                      <p
                        className="mt-2 text-sm"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {article.alert_ids.length}{" "}
                        {article.alert_ids.length === 1
                          ? "alert referenced"
                          : "alerts referenced"}
                      </p>
                      <div
                        className="mt-3 flex flex-wrap gap-1.5 text-[10px]"
                        style={{ ...MONO, color: "var(--text-muted)" }}
                      >
                        {article.alert_ids.slice(0, 8).map((id) => (
                          <Link
                            key={id}
                            href={`/alert/${id}`}
                            className="dispatch-chip border px-1.5 py-0.5 tracking-[0.12em]"
                            style={{
                              borderColor: "var(--border-subtle)",
                              color: "var(--text-secondary)",
                            }}
                          >
                            #{id}
                          </Link>
                        ))}
                        {article.alert_ids.length > 8 && (
                          <span
                            className="px-1.5 py-0.5 tracking-[0.12em]"
                            style={{ color: "var(--text-muted)" }}
                          >
                            +{article.alert_ids.length - 8} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
              </div>
            </aside>

            {/* Article */}
            <article className="col-span-12 md:col-span-9">
              <div className="dispatch-prose">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {article.body_markdown}
                </ReactMarkdown>
              </div>

              {/* End-of-dispatch */}
              <div
                className="mt-16 flex flex-wrap items-center justify-between gap-4 border-t pt-8"
                style={{ borderColor: "var(--border)" }}
              >
                <span
                  className="text-[10px] uppercase"
                  style={{
                    ...MONO,
                    letterSpacing: "0.32em",
                    color: "var(--text-muted)",
                  }}
                >
                  — End of dispatch{dispatchNo ? ` · № ${dispatchNo}` : ""} —
                </span>
                {article.posted_url && (
                  <a
                    href={article.posted_url}
                    target="_blank"
                    rel="noopener nofollow"
                    className="dispatch-cta group inline-flex items-center gap-3 self-start text-xs uppercase"
                    style={{
                      ...MONO,
                      letterSpacing: "0.3em",
                      color: "var(--text-primary)",
                    }}
                  >
                    <span className="dispatch-cta-rule" aria-hidden />
                    <span>Discuss on X</span>
                    <span className="dispatch-arrow inline-block">↗</span>
                  </a>
                )}
              </div>
            </article>
          </div>
        </section>

        {/* Footer */}
        <footer
          className="mt-20 border-t"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-6">
            <Link
              href="/articles"
              className="dispatch-back inline-flex items-center gap-2 text-[10px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-secondary)",
              }}
            >
              <span aria-hidden>←</span>
              <span>The archive</span>
            </Link>
            <Link
              href="/"
              className="dispatch-back inline-flex items-center gap-2 text-[10px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-secondary)",
              }}
            >
              <span>Return to PolySpotter</span>
              <span aria-hidden>↗</span>
            </Link>
          </div>
        </footer>
      </div>
    </main>
  );
}

function ArticlePageStyles() {
  const css = `
    .dispatch-page-bg {
      background-image:
        linear-gradient(to right, color-mix(in srgb, var(--border-subtle) 60%, transparent) 1px, transparent 1px),
        linear-gradient(to bottom, color-mix(in srgb, var(--border-subtle) 60%, transparent) 1px, transparent 1px);
      background-size: 96px 96px;
      background-position: -1px -1px;
    }
    .dispatch-page-bg::before {
      content: "";
      position: absolute;
      inset: 0 0 auto 0;
      height: 520px;
      pointer-events: none;
      background:
        radial-gradient(60% 70% at 50% 0%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 75%);
    }

    /* ── Frame mark on cover image ── */
    .dispatch-frame-mark {
      filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 35%, transparent));
    }

    /* ── Prose container ── */
    .dispatch-prose {
      font-family: var(--font-body);
      font-size: 1.1875rem;
      line-height: 1.78;
      color: var(--text-secondary);
      max-width: 70ch;
      counter-reset: dispatch-section;
    }
    .dispatch-prose > * + * { margin-top: 1.4em; }
    .dispatch-prose strong { color: var(--text-primary); font-weight: 600; }
    .dispatch-prose em { font-style: italic; color: var(--text-primary); }

    /* ── Drop cap on first paragraph ── */
    .dispatch-prose > p:first-of-type::first-letter {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 4.4em;
      line-height: 0.85;
      float: left;
      padding: 0.08em 0.12em 0 0;
      margin-right: 0.06em;
      color: var(--accent);
      text-shadow:
        0 0 24px color-mix(in srgb, var(--accent) 35%, transparent),
        0 0 1px color-mix(in srgb, var(--accent) 50%, transparent);
    }

    /* ── Headings ── */
    .dispatch-h1 {
      font-family: var(--font-body);
      font-weight: 600;
      font-size: 2rem;
      line-height: 1.1;
      letter-spacing: -0.01em;
      color: var(--text-primary);
      margin-top: 2.4em;
      margin-bottom: 0.6em;
    }

    .dispatch-h2 {
      counter-increment: dispatch-section;
      position: relative;
      font-family: var(--font-body);
      font-weight: 600;
      font-size: 1.65rem;
      line-height: 1.18;
      letter-spacing: -0.012em;
      color: var(--text-primary);
      margin-top: 2.6em;
      margin-bottom: 0.7em;
      padding-top: 1.4em;
      border-top: 1px solid var(--border-subtle);
    }
    .dispatch-h2::before {
      content: "§ " counter(dispatch-section, decimal-leading-zero);
      position: absolute;
      top: 1.4em;
      left: 0;
      transform: translateY(-1.7em);
      font-family: var(--font-display);
      font-weight: 500;
      font-size: 0.7rem;
      letter-spacing: 0.32em;
      text-transform: uppercase;
      color: var(--accent);
    }

    .dispatch-h3 {
      font-family: var(--font-body);
      font-weight: 600;
      font-size: 1.25rem;
      line-height: 1.25;
      letter-spacing: -0.005em;
      color: var(--text-primary);
      margin-top: 2em;
      margin-bottom: 0.5em;
    }

    /* ── Lists ── */
    .dispatch-list {
      list-style: none;
      padding-left: 0;
      margin-left: 0;
    }
    .dispatch-list > li {
      position: relative;
      padding-left: 1.6rem;
      margin-top: 0.55em;
    }
    .dispatch-list > li::before {
      content: "";
      position: absolute;
      left: 0.1rem;
      top: 0.78em;
      width: 0.55rem;
      height: 1px;
      background: var(--accent);
    }
    .dispatch-list-ordered {
      counter-reset: dispatch-list;
    }
    .dispatch-list-ordered > li {
      counter-increment: dispatch-list;
    }
    .dispatch-list-ordered > li::before {
      content: counter(dispatch-list, decimal-leading-zero);
      background: transparent;
      width: auto;
      height: auto;
      top: 0.05em;
      left: 0;
      font-family: var(--font-display);
      font-size: 0.78em;
      letter-spacing: 0.18em;
      color: var(--accent);
    }

    /* ── Pull quote (blockquote) ── */
    .dispatch-pullquote {
      position: relative;
      margin: 2.4em 0 2.4em -0.5rem;
      padding: 0.4em 0 0.4em 1.6rem;
      border-left: 2px solid var(--accent);
      font-family: var(--font-body);
      font-style: normal;
      font-weight: 500;
      font-size: 1.45rem;
      line-height: 1.4;
      letter-spacing: -0.01em;
      color: var(--text-primary);
    }
    .dispatch-pullquote::before {
      content: "“";
      position: absolute;
      left: -0.05rem;
      top: -1.05rem;
      font-family: var(--font-body);
      font-size: 3.4rem;
      line-height: 1;
      color: color-mix(in srgb, var(--accent) 50%, transparent);
      pointer-events: none;
    }
    .dispatch-pullquote p { margin: 0; }
    .dispatch-pullquote p + p { margin-top: 0.6em; }

    /* ── Inline link ── */
    .dispatch-prose-link {
      color: var(--text-primary);
      text-decoration: none;
      background-image: linear-gradient(var(--accent), var(--accent));
      background-size: 100% 1px;
      background-repeat: no-repeat;
      background-position: 0 100%;
      transition: color 0.2s ease, background-size 0.3s ease;
      padding-bottom: 1px;
    }
    .dispatch-prose-link:hover {
      color: var(--accent);
      background-size: 100% 2px;
    }

    /* ── Rule ── */
    .dispatch-rule {
      border: 0;
      height: 1px;
      background: var(--border);
      margin: 2.4em 0;
      position: relative;
    }
    .dispatch-rule::after {
      content: "✦";
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      background: var(--surface-0);
      padding: 0 0.75rem;
      font-family: var(--font-display);
      font-size: 0.7rem;
      letter-spacing: 0.3em;
      color: var(--accent);
    }

    /* ── Code ── */
    .dispatch-code {
      font-family: var(--font-display);
      font-size: 0.875em;
      padding: 0.12em 0.4em;
      border-radius: 3px;
      background: color-mix(in srgb, var(--accent) 10%, transparent);
      color: var(--text-primary);
    }
    .dispatch-pre {
      font-family: var(--font-display);
      font-size: 0.85rem;
      padding: 1rem 1.2rem;
      background: var(--surface-1);
      border: 1px solid var(--border);
      overflow-x: auto;
      line-height: 1.55;
    }

    /* ── Inline image ── */
    .dispatch-inline-img {
      width: 100%;
      margin: 1.6em 0;
      border: 1px solid var(--border);
    }

    /* ── Side-rail chip ── */
    .dispatch-chip {
      transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
    }
    .dispatch-chip:hover {
      color: var(--accent) !important;
      border-color: color-mix(in srgb, var(--accent) 50%, transparent) !important;
      background: color-mix(in srgb, var(--accent) 6%, transparent);
    }

    /* ── Reused (matches index page) ── */
    .dispatch-cta {
      position: relative;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
      transition: border-color 0.25s ease, color 0.25s ease;
    }
    .dispatch-cta:hover {
      border-color: var(--accent);
      color: var(--accent) !important;
    }
    .dispatch-cta .dispatch-cta-rule {
      width: 18px;
      height: 1px;
      background: currentColor;
      opacity: 0.5;
      transition: width 0.3s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.25s ease;
    }
    .dispatch-cta:hover .dispatch-cta-rule {
      width: 32px;
      opacity: 1;
    }
    .dispatch-arrow {
      transition: transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .dispatch-cta:hover .dispatch-arrow {
      transform: translate(3px, -2px);
    }
    .dispatch-back { transition: color 0.2s ease; }
    .dispatch-back:hover { color: var(--accent) !important; }

    /* ── Mobile adjustments ── */
    @media (max-width: 768px) {
      .dispatch-prose { font-size: 1.0625rem; line-height: 1.72; }
      .dispatch-prose > p:first-of-type::first-letter { font-size: 3.6em; }
      .dispatch-h2 { font-size: 1.4rem; }
      .dispatch-h3 { font-size: 1.1rem; }
      .dispatch-pullquote { font-size: 1.2rem; padding-left: 1.1rem; }
    }

    @media (prefers-reduced-motion: reduce) {
      .dispatch-cta,
      .dispatch-cta-rule,
      .dispatch-arrow,
      .dispatch-prose-link,
      .dispatch-back,
      .dispatch-chip {
        transition: none !important;
      }
    }
  `;
  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}
