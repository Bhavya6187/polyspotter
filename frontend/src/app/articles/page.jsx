import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export const revalidate = 60;

export const metadata = {
  title: "Articles",
  description:
    "All PolySpotter articles — daily writeups on notable Polymarket trades, sharp bettors, and prediction-market signals.",
  alternates: { canonical: "/articles" },
  openGraph: {
    title: "Articles · PolySpotter",
    description:
      "All PolySpotter articles — daily writeups on notable Polymarket trades.",
    url: `${SITE_URL}/articles`,
    type: "website",
  },
};

async function getArticles() {
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

function monthKey(iso) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthParts(iso) {
  const d = new Date(iso + "T00:00:00");
  return {
    month: d.toLocaleDateString("en-US", { month: "short" }).toUpperCase(),
    year: String(d.getFullYear()).slice(-2),
    fullYear: d.getFullYear(),
    fullMonth: d.toLocaleDateString("en-US", { month: "long" }),
  };
}

function hueFromId(id) {
  const str = String(id || "");
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

function dispatchNumber(idx, total) {
  return String(total - idx).padStart(4, "0");
}

const MONO = { fontFamily: "var(--font-display)" };

function Crosshair({ className = "", flipX = false, flipY = false }) {
  const tx = flipX ? "scaleX(-1)" : "";
  const ty = flipY ? "scaleY(-1)" : "";
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={className}
      style={{ transform: `${tx} ${ty}`.trim() || undefined }}
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

function ProceduralCover({ runId }) {
  const hue = hueFromId(runId);
  const hue2 = (hue + 64) % 360;
  return (
    <div
      className="dispatch-cover absolute inset-0"
      style={{
        background: `
          radial-gradient(60% 80% at 28% 18%, hsl(${hue} 78% 58% / 0.42), transparent 65%),
          radial-gradient(45% 60% at 82% 78%, hsl(${hue2} 80% 55% / 0.32), transparent 70%),
          linear-gradient(135deg, var(--surface-1), var(--surface-2))
        `,
      }}
    >
      <div className="dispatch-cover-grid absolute inset-0" />
      <div className="dispatch-cover-noise absolute inset-0" />
    </div>
  );
}

function FeaturedDispatch({ article, total }) {
  const href = `/article/${article.published_date}/${article.event_slug}`;
  return (
    <section
      className="relative border-y"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="mx-auto grid max-w-6xl grid-cols-1 lg:grid-cols-12">
        <div
          className="relative aspect-[5/4] overflow-hidden border-b lg:col-span-5 lg:aspect-auto lg:min-h-[440px] lg:border-b-0 lg:border-r"
          style={{ borderColor: "var(--border)" }}
        >
          <ProceduralCover runId={article.run_id} />

          <div className="relative flex h-full flex-col justify-between p-6 lg:p-8">
            <div className="flex items-start justify-between gap-4">
              <span
                className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[10px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.22em",
                  background: "var(--surface-card)",
                  color: "var(--accent)",
                  borderColor:
                    "color-mix(in srgb, var(--accent) 35%, transparent)",
                }}
              >
                <span
                  className="size-1.5 rounded-full animate-pulse-live"
                  style={{ background: "var(--accent)" }}
                />
                Latest dispatch
              </span>
              <span
                className="text-[10px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.25em",
                  color: "var(--text-muted)",
                }}
              >
                Polyspotter // wire
              </span>
            </div>

            <div
              className="flex items-end justify-between gap-4 text-[10px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.25em",
                color: "var(--text-secondary)",
              }}
            >
              <div className="flex flex-col gap-1">
                <span style={{ color: "var(--text-muted)" }}>Dispatch №</span>
                <span
                  className="text-2xl tracking-[0.08em]"
                  style={{ color: "var(--text-primary)" }}
                >
                  {String(total).padStart(4, "0")}
                </span>
              </div>
              <div className="flex flex-col gap-1 text-right">
                <span style={{ color: "var(--text-muted)" }}>Filed</span>
                <time
                  dateTime={article.published_date}
                  className="tracking-[0.18em]"
                  style={{ color: "var(--text-primary)" }}
                >
                  {formatLongDate(article.published_date)}
                </time>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-10 p-8 lg:col-span-7 lg:p-12">
          <div>
            <div
              className="flex items-center gap-3 text-[11px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.25em",
                color: "var(--text-muted)",
              }}
            >
              <span
                className="size-1 rounded-full"
                style={{ background: "var(--accent)" }}
              />
              <span>Featured</span>
              <span style={{ opacity: 0.5 }}>/</span>
              <span>{formatShortDate(article.published_date)}</span>
              <span style={{ opacity: 0.5 }}>/</span>
              <span>3 min read</span>
            </div>

            <h2
              className="mt-7 text-balance text-3xl font-semibold leading-[1.05] tracking-tight md:text-[2.85rem]"
              style={{ color: "var(--text-primary)" }}
            >
              <Link href={href} className="dispatch-headline">
                {article.headline}
              </Link>
            </h2>
          </div>

          <Link
            href={href}
            className="dispatch-cta group inline-flex items-center gap-3 self-start text-xs uppercase"
            style={{
              ...MONO,
              letterSpacing: "0.3em",
              color: "var(--text-primary)",
            }}
          >
            <span className="dispatch-cta-rule" aria-hidden />
            <span>Read dispatch</span>
            <span className="dispatch-arrow inline-block">→</span>
          </Link>
        </div>
      </div>
    </section>
  );
}

function DispatchRow({ article, dispatchNo }) {
  const href = `/article/${article.published_date}/${article.event_slug}`;
  return (
    <Link
      href={href}
      className="dispatch-row group block border-t"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="grid grid-cols-12 items-baseline gap-x-4 gap-y-3 py-7 md:gap-x-8">
        <span
          className="col-span-3 text-[11px] uppercase md:col-span-2"
          style={{
            ...MONO,
            letterSpacing: "0.22em",
            color: "var(--text-muted)",
          }}
        >
          № {dispatchNo}
        </span>
        <time
          dateTime={article.published_date}
          className="col-span-9 text-[11px] uppercase md:col-span-2"
          style={{
            ...MONO,
            letterSpacing: "0.22em",
            color: "var(--text-secondary)",
          }}
        >
          {formatShortDate(article.published_date)}
        </time>
        <h3
          className="col-span-12 text-balance text-xl font-medium leading-snug tracking-tight md:col-span-7 md:text-2xl"
          style={{ color: "var(--text-primary)" }}
        >
          {article.headline}
        </h3>
        <span
          className="col-span-12 inline-flex items-center justify-end gap-2 text-[11px] uppercase md:col-span-1"
          style={{
            ...MONO,
            letterSpacing: "0.25em",
            color: "var(--text-muted)",
          }}
        >
          <span className="dispatch-row-cta">Read</span>
          <span className="dispatch-arrow inline-block">→</span>
        </span>
      </div>
    </Link>
  );
}

export default async function ArticlesIndexPage() {
  const articles = await getArticles();
  const total = articles.length;
  const featured = articles[0];
  const archive = articles.slice(1);

  const groups = [];
  let currentKey = null;
  archive.forEach((a, i) => {
    const key = monthKey(a.published_date);
    if (key !== currentKey) {
      groups.push({ key, parts: monthParts(a.published_date), items: [] });
      currentKey = key;
    }
    groups[groups.length - 1].items.push({ article: a, indexInArchive: i });
  });

  return (
    <main
      className="min-h-screen"
      style={{ background: "var(--surface-0)", color: "var(--text-primary)" }}
    >
      <ArticlesPageStyles />

      <div className="dispatch-page-bg relative">
        {/* Top wire bar */}
        <div
          className="border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <Link
              href="/"
              className="dispatch-back inline-flex items-center gap-2 text-[11px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.28em",
                color: "var(--text-secondary)",
              }}
            >
              <span aria-hidden>←</span>
              <span>PolySpotter</span>
            </Link>
            <div
              className="hidden items-center gap-3 text-[10px] uppercase md:flex"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-muted)",
              }}
            >
              <span>Wire / Archive</span>
              <span aria-hidden style={{ opacity: 0.5 }}>
                {"////"}
              </span>
              <span>{new Date().toUTCString().split(" ").slice(1, 5).join(" ")}</span>
            </div>
          </div>
        </div>

        {/* Masthead */}
        <header className="relative mx-auto max-w-6xl px-6 pb-16 pt-20 md:pb-24 md:pt-28">
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
            className="flex items-center gap-3 text-[11px] uppercase"
            style={{
              ...MONO,
              letterSpacing: "0.32em",
              color: "var(--text-muted)",
            }}
          >
            <span
              className="size-1.5 rounded-full"
              style={{ background: "var(--accent)" }}
            />
            <span>Dispatch Log</span>
            <span style={{ opacity: 0.4 }}>·</span>
            <span>Vol. 01</span>
          </div>

          <h1
            className="mt-6 text-balance text-[clamp(3rem,9vw,7rem)] font-semibold leading-[0.95] tracking-tight"
            style={{ color: "var(--text-primary)" }}
          >
            Articles
            <span
              className="dispatch-period"
              style={{ color: "var(--accent)" }}
            >
              .
            </span>
          </h1>

          <div className="mt-10 grid grid-cols-1 gap-10 md:grid-cols-12">
            <p
              className="max-w-xl text-lg leading-relaxed md:col-span-7"
              style={{ color: "var(--text-secondary)" }}
            >
              Daily writeups on notable Polymarket trades — sharp bettors,
              coordinated flow, and the prediction-market signals worth a
              second look. Filed each morning, archived in full below.
            </p>

            <dl
              className="grid grid-cols-3 gap-4 self-end md:col-span-5"
              style={MONO}
            >
              {[
                { label: "Dispatches", value: String(total).padStart(3, "0") },
                {
                  label: "Latest",
                  value: featured
                    ? formatShortDate(featured.published_date)
                    : "—",
                },
                { label: "Cadence", value: "Daily" },
              ].map((s) => (
                <div
                  key={s.label}
                  className="border-t pt-3"
                  style={{ borderColor: "var(--border)" }}
                >
                  <dt
                    className="text-[10px] uppercase"
                    style={{
                      letterSpacing: "0.28em",
                      color: "var(--text-muted)",
                    }}
                  >
                    {s.label}
                  </dt>
                  <dd
                    className="mt-1 text-2xl tracking-[0.04em]"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {s.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </header>

        {total === 0 ? (
          <section
            className="border-y"
            style={{ borderColor: "var(--border)" }}
          >
            <div className="mx-auto max-w-6xl px-6 py-24 text-center">
              <p
                className="text-[11px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.3em",
                  color: "var(--text-muted)",
                }}
              >
                No transmissions yet
              </p>
              <p
                className="mx-auto mt-4 max-w-md text-lg"
                style={{ color: "var(--text-secondary)" }}
              >
                The wire is quiet. The first dispatch will appear here once
                published.
              </p>
            </div>
          </section>
        ) : (
          <FeaturedDispatch article={featured} total={total} />
        )}

        {archive.length > 0 && (
          <section className="mx-auto max-w-6xl px-6 pb-24 pt-20">
            <div
              className="mb-12 flex items-baseline justify-between gap-4 border-b pb-4"
              style={{ borderColor: "var(--border)" }}
            >
              <h2
                className="text-[11px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.3em",
                  color: "var(--text-muted)",
                }}
              >
                {"// The archive"}
              </h2>
              <span
                className="text-[10px] uppercase"
                style={{
                  ...MONO,
                  letterSpacing: "0.3em",
                  color: "var(--text-muted)",
                }}
              >
                {archive.length} {archive.length === 1 ? "entry" : "entries"}
              </span>
            </div>

            <div className="space-y-16">
              {groups.map((group) => (
                <div
                  key={group.key}
                  className="grid grid-cols-12 gap-x-6 gap-y-6 md:gap-x-10"
                >
                  <div className="col-span-12 md:col-span-3">
                    <div className="md:sticky md:top-8">
                      <div
                        className="flex items-baseline gap-3 md:flex-col md:items-start md:gap-1"
                        style={MONO}
                      >
                        <span
                          className="text-[10px] uppercase"
                          style={{
                            letterSpacing: "0.32em",
                            color: "var(--text-muted)",
                          }}
                        >
                          {group.parts.fullYear}
                        </span>
                        <span
                          className="text-4xl font-semibold tracking-[0.04em] md:text-5xl"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {group.parts.month}
                          <span style={{ color: "var(--accent)" }}> /</span>
                          <span style={{ color: "var(--text-secondary)" }}>
                            {group.parts.year}
                          </span>
                        </span>
                        <span
                          className="text-[10px] uppercase"
                          style={{
                            letterSpacing: "0.28em",
                            color: "var(--text-muted)",
                          }}
                        >
                          {group.items.length}{" "}
                          {group.items.length === 1
                            ? "dispatch"
                            : "dispatches"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="col-span-12 md:col-span-9">
                    {group.items.map(({ article, indexInArchive }) => (
                      <DispatchRow
                        key={article.run_id}
                        article={article}
                        // dispatch numbers count down from total-1 (featured got total)
                        dispatchNo={dispatchNumber(indexInArchive + 1, total)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Footer marker */}
        <footer
          className="border-t"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-6">
            <span
              className="text-[10px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-muted)",
              }}
            >
              — End of transmission —
            </span>
            <Link
              href="/"
              className="dispatch-back inline-flex items-center gap-2 text-[10px] uppercase"
              style={{
                ...MONO,
                letterSpacing: "0.3em",
                color: "var(--text-secondary)",
              }}
            >
              <span>Return to wire</span>
              <span aria-hidden>↗</span>
            </Link>
          </div>
        </footer>
      </div>
    </main>
  );
}

function ArticlesPageStyles() {
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
      inset: 0;
      pointer-events: none;
      background:
        radial-gradient(80% 50% at 50% 0%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 70%);
      mix-blend-mode: normal;
    }

    .dispatch-cover-grid {
      background-image:
        linear-gradient(to right, color-mix(in srgb, var(--text-primary) 8%, transparent) 1px, transparent 1px),
        linear-gradient(to bottom, color-mix(in srgb, var(--text-primary) 8%, transparent) 1px, transparent 1px);
      background-size: 32px 32px;
      mask-image: radial-gradient(120% 80% at 50% 50%, black, transparent 80%);
    }
    .dispatch-cover-noise {
      opacity: 0.35;
      background-image:
        repeating-linear-gradient(
          0deg,
          color-mix(in srgb, var(--text-primary) 4%, transparent) 0,
          color-mix(in srgb, var(--text-primary) 4%, transparent) 1px,
          transparent 1px,
          transparent 3px
        );
      mix-blend-mode: overlay;
    }

    .dispatch-period {
      display: inline-block;
      transform: translateY(-0.04em);
    }

    .dispatch-headline {
      background-image: linear-gradient(var(--accent), var(--accent));
      background-size: 0% 1px;
      background-repeat: no-repeat;
      background-position: 0 100%;
      transition: background-size 0.45s cubic-bezier(0.2, 0.8, 0.2, 1), color 0.2s ease;
    }
    .dispatch-headline:hover {
      background-size: 100% 1px;
    }

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
    .dispatch-cta:hover .dispatch-arrow,
    .dispatch-row:hover .dispatch-arrow {
      transform: translateX(4px);
    }

    .dispatch-row {
      transition: background 0.25s ease;
    }
    .dispatch-row:hover {
      background: color-mix(in srgb, var(--accent) 4%, transparent);
    }
    .dispatch-row h3 {
      transition: color 0.2s ease, transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .dispatch-row:hover h3 {
      color: var(--accent);
    }
    @media (min-width: 768px) {
      .dispatch-row:hover h3 {
        transform: translateX(4px);
      }
    }
    .dispatch-row-cta {
      opacity: 0.6;
      transition: opacity 0.25s ease;
    }
    .dispatch-row:hover .dispatch-row-cta {
      opacity: 1;
    }

    .dispatch-back {
      transition: color 0.2s ease;
    }
    .dispatch-back:hover {
      color: var(--accent) !important;
    }

    @media (prefers-reduced-motion: reduce) {
      .dispatch-headline,
      .dispatch-cta,
      .dispatch-cta-rule,
      .dispatch-arrow,
      .dispatch-row,
      .dispatch-row h3 {
        transition: none !important;
      }
    }
  `;
  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}
