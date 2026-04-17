"use client";

import Link from "next/link";
import AlertList from "../../../components/AlertList";

export default function TagPageClient({ markets, page, totalPages, slug, resolves = "", severity = "" }) {
  const buildHref = (p) => {
    const qs = new URLSearchParams();
    if (p > 1) qs.set("page", String(p));
    if (resolves) qs.set("resolves", resolves);
    if (severity) qs.set("severity", severity);
    const q = qs.toString();
    return q ? `/tag/${slug}?${q}` : `/tag/${slug}`;
  };

  return (
    <>
      <AlertList
        markets={markets}
        filters={{ tag: "", resolvesIn: resolves }}
        loading={false}
      />
      {totalPages > 1 && (
        <nav aria-label="Pagination" className="flex items-center justify-center gap-4 py-6">
          {page > 1 ? (
            <Link
              href={buildHref(page - 1)}
              className="rounded-lg px-4 py-2 text-sm font-medium transition-all"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
            >
              &larr; Prev
            </Link>
          ) : (
            <span
              className="rounded-lg px-4 py-2 text-sm font-medium opacity-30"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
            >
              &larr; Prev
            </span>
          )}
          <span className="text-sm font-medium" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)' }}>
            {page} / {totalPages}
          </span>
          {page < totalPages ? (
            <Link
              href={buildHref(page + 1)}
              className="rounded-lg px-4 py-2 text-sm font-medium transition-all"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
            >
              Next &rarr;
            </Link>
          ) : (
            <span
              className="rounded-lg px-4 py-2 text-sm font-medium opacity-30"
              style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
            >
              Next &rarr;
            </span>
          )}
        </nav>
      )}
    </>
  );
}
