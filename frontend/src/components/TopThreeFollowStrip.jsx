"use client";

export default function TopThreeFollowStrip() {
  return (
    <a
      href="https://x.com/polyspotter"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Follow PolySpotter on X"
      className="mb-5 flex items-center justify-between gap-3 rounded-xl px-4 py-2.5 text-xs transition-colors"
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border)",
        color: "var(--text-secondary)",
      }}
    >
      <span className="flex min-w-0 items-center gap-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="h-3.5 w-3.5 shrink-0"
          style={{ color: "var(--text-primary)" }}
          aria-hidden="true"
        >
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
        </svg>
        <span className="truncate">
          We post today&rsquo;s top alerts at{" "}
          <span style={{ color: "var(--text-primary)" }}>@polyspotter</span>
        </span>
      </span>
      <span
        className="shrink-0 whitespace-nowrap font-medium"
        style={{ color: "var(--text-primary)" }}
      >
        Follow →
      </span>
    </a>
  );
}
