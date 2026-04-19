"use client";

import Link from "next/link";
import { useRef, useState, useEffect } from "react";

const TOPICS = [
  "Sports",
  "NBA",
  "Soccer",
  "Esports",
  "Politics",
  "Geopolitics",
  "Elections",
  "Crypto",
  "Economy",
  "Culture",
];

function tagSlug(name) {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

export default function TopicNav() {
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    function check() {
      setCanScrollLeft(el.scrollLeft > 2);
      setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 2);
    }
    check();
    el.addEventListener("scroll", check, { passive: true });
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", check);
      ro.disconnect();
    };
  }, []);

  function scroll(dir) {
    scrollRef.current?.scrollBy({ left: dir * 200, behavior: "smooth" });
  }

  return (
    <nav
      className="relative mb-5"
      aria-label="Topics"
    >
      {/* Fade edges */}
      {canScrollLeft && (
        <div
          className="absolute left-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
          style={{
            background: "linear-gradient(to right, var(--surface-0), transparent)",
          }}
        />
      )}
      {canScrollRight && (
        <div
          className="absolute right-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
          style={{
            background: "linear-gradient(to left, var(--surface-0), transparent)",
          }}
        />
      )}

      {/* Scroll arrows (desktop only) */}
      {canScrollLeft && (
        <button
          onClick={() => scroll(-1)}
          className="absolute left-0 top-1/2 -translate-y-1/2 z-20 hidden sm:flex h-7 w-7 items-center justify-center rounded-full border"
          style={{
            background: "var(--surface-card)",
            borderColor: "var(--border)",
            color: "var(--text-muted)",
          }}
          aria-label="Scroll left"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      )}
      {canScrollRight && (
        <button
          onClick={() => scroll(1)}
          className="absolute right-0 top-1/2 -translate-y-1/2 z-20 hidden sm:flex h-7 w-7 items-center justify-center rounded-full border"
          style={{
            background: "var(--surface-card)",
            borderColor: "var(--border)",
            color: "var(--text-muted)",
          }}
          aria-label="Scroll right"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      )}

      {/* Scrollable strip */}
      <div
        ref={scrollRef}
        className="flex items-center gap-1.5 overflow-x-auto no-scrollbar"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
      >
        {TOPICS.map((name) => (
          <Link
            key={name}
            href={`/tag/${tagSlug(name)}`}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all hover:border-[var(--accent)] hover:shadow-[var(--glow-medium)]"
            style={{
              background: "var(--surface-card)",
              borderColor: "var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            {name}
          </Link>
        ))}
      </div>
    </nav>
  );
}
