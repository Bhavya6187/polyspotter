export default function TopBar() {
  return (
    <div
      className="w-full"
      style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface-0)' }}
    >
      <div className="mx-auto max-w-6xl px-4 py-2 flex items-center justify-end gap-3 text-xs">
        <a
          href="mailto:feedback@polyspotter.com"
          className="transition-colors hover:underline"
          style={{ color: 'var(--text-muted)' }}
        >
          Send feedback
        </a>
        <a
          href="https://x.com/polyspotter"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Follow PolySpotter on X"
          className="inline-flex items-center justify-center rounded-md p-1 transition-colors hover:opacity-80"
          style={{ color: 'var(--text-muted)' }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="h-3.5 w-3.5"
            aria-hidden="true"
          >
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
          </svg>
        </a>
      </div>
    </div>
  );
}
