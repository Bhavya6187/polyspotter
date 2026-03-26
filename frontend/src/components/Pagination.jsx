export default function Pagination({ page, totalPages, onPageChange }) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-4 py-6">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="rounded-lg px-4 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-30"
        style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
      >
        &larr; Prev
      </button>
      <span className="text-sm font-medium" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)' }}>
        {page} / {totalPages}
      </span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg px-4 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-30"
        style={{ border: '1px solid var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-card)' }}
      >
        Next &rarr;
      </button>
    </div>
  );
}
