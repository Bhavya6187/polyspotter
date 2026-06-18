/**
 * Compact row of secondary header links: Send feedback + X/Twitter.
 * Previously lived in the site-wide TopBar; inlined here so headers can
 * render them next to the main search/actions instead of in a separate strip.
 *
 * Variants:
 *   - default: "Send feedback" text + X icon (used on pages with room)
 *   - compact: icons only (used on dense nav rows like market/wallet pages)
 */
export default function HeaderActions({ variant = "default" }) {
  const compact = variant === "compact";

  return (
    <div className="flex items-center gap-1">
      <a
        href="/blog"
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
        aria-label="Blog"
        title="Blog"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-3.5 w-3.5"
          aria-hidden="true"
        >
          <path d="M4 4h12a2 2 0 0 1 2 2v13a1 1 0 0 0 1 1 1 1 0 0 0 1-1V8" />
          <path d="M4 4v15a1 1 0 0 0 1 1h15" />
          <path d="M8 8h6M8 12h6M8 16h4" />
        </svg>
        {!compact && <span className="hidden md:inline">Blog</span>}
      </a>
      <a
        href="/digest"
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
        aria-label="Daily Digest"
        title="Daily Digest"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-3.5 w-3.5"
          aria-hidden="true"
        >
          <rect x="3" y="4" width="18" height="17" rx="2" />
          <path d="M3 9h18M8 2v4M16 2v4M7 13h6M7 17h4" />
        </svg>
        {!compact && <span className="hidden md:inline">Digest</span>}
      </a>
      <a
        href="mailto:feedback@polyspotter.com"
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
        aria-label="Send feedback"
        title="Send feedback"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-3.5 w-3.5"
          aria-hidden="true"
        >
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
        {!compact && <span className="hidden md:inline">Feedback</span>}
      </a>
      <a
        href="https://x.com/polyspotter"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Follow PolySpotter on X"
        title="Follow on X"
        className="inline-flex items-center justify-center rounded-md p-1.5 transition-colors hover:opacity-80"
        style={{ color: "var(--text-muted)" }}
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
  );
}
