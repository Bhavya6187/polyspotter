"use client";

import { useEffect, useRef } from "react";

function buildSearchQuery(title) {
  if (!title) return "polymarket";
  // Extract meaningful keywords from the market title
  const stopWords = new Set([
    "will", "the", "a", "an", "be", "to", "in", "on", "at", "of", "or",
    "and", "is", "by", "for", "with", "this", "that", "it", "as", "do",
    "does", "than", "before", "after", "from", "into", "yes", "no",
  ]);
  const keywords = title
    .replace(/[?!.,()]/g, "")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !stopWords.has(w.toLowerCase()))
    .slice(0, 5)
    .join(" ");
  return keywords || "polymarket";
}

export default function TwitterFeed({ title }) {
  const containerRef = useRef(null);
  const query = buildSearchQuery(title);
  const searchUrl = `https://x.com/search?q=${encodeURIComponent(query)}&f=live`;

  useEffect(() => {
    // Load Twitter widgets.js if not already loaded
    if (!window.twttr) {
      const script = document.createElement("script");
      script.src = "https://platform.twitter.com/widgets.js";
      script.async = true;
      script.charset = "utf-8";
      document.head.appendChild(script);
      script.onload = () => {
        window.twttr?.widgets?.load(containerRef.current);
      };
    } else {
      window.twttr.widgets.load(containerRef.current);
    }
  }, [query]);

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        borderColor: "var(--border)",
        background: "var(--surface-card)",
      }}
    >
      <div
        className="px-3 py-2 border-b flex items-center gap-2"
        style={{ borderColor: "var(--border)" }}
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" style={{ color: "var(--text-muted)" }}>
          <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
        </svg>
        <h3
          className="text-xs font-semibold uppercase tracking-widest"
          style={{
            fontFamily: "var(--font-display)",
            color: "var(--text-muted)",
            fontSize: "0.6rem",
          }}
        >
          Related on X
        </h3>
        <a
          href={searchUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-xs"
          style={{ color: "var(--accent)" }}
        >
          View all
        </a>
      </div>
      <div ref={containerRef} className="max-h-[400px] overflow-y-auto">
        <a
          className="twitter-timeline"
          data-theme="dark"
          data-chrome="noheader nofooter noborders transparent"
          data-height="400"
          data-tweet-limit="5"
          href={`https://twitter.com/search?q=${encodeURIComponent(query)}`}
        >
          Loading posts about {query}...
        </a>
      </div>
    </div>
  );
}
