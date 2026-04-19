"use client";

import Link from "next/link";
import { useRef, useState, useEffect, useCallback } from "react";
import { fetchAlerts } from "../lib/api";

const TOPICS = [
  { name: "Sports",      family: "sport",    glyph: "trophy",     anim: "glyph-pop" },
  { name: "NBA",         family: "sport",    glyph: "basketball", anim: "glyph-spin" },
  { name: "Soccer",      family: "sport",    glyph: "soccer",     anim: "glyph-kick" },
  { name: "Esports",     family: "sport",    glyph: "controller", anim: "glyph-wobble" },
  { name: "Politics",    family: "politics", glyph: "building",   anim: "glyph-rise" },
  { name: "Geopolitics", family: "politics", glyph: "globe",      anim: "glyph-tilt" },
  { name: "Elections",   family: "politics", glyph: "ballot",     anim: "glyph-check" },
  { name: "Crypto",      family: "market",   glyph: "coin",       anim: "glyph-flip" },
  { name: "Economy",     family: "market",   glyph: "chart",      anim: "glyph-grow" },
  { name: "Culture",     family: "culture",  glyph: "sparkles",   anim: "glyph-twinkle" },
];

const FAMILY_COLORS = {
  sport:    "#f59e0b",
  politics: "#6366f1",
  market:   "#06b6d4",
  culture:  "#ec4899",
};

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function tagSlug(name) {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

function pulseStateFor(latestIso) {
  if (!latestIso) return null;
  const ageMs = Date.now() - new Date(latestIso).getTime();
  if (ageMs < HOUR) return "live";
  if (ageMs < DAY) return "recent";
  return null;
}

function formatRecency(iso) {
  if (!iso) return null;
  const ageMs = Date.now() - new Date(iso).getTime();
  if (ageMs < 60_000) return "now";
  if (ageMs < HOUR) return `${Math.floor(ageMs / 60_000)}m`;
  if (ageMs < DAY) return `${Math.floor(ageMs / HOUR)}h`;
  if (ageMs < 7 * DAY) return `${Math.floor(ageMs / DAY)}d`;
  return null;
}

function formatCount(n) {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function formatUsd(n) {
  if (n == null) return null;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${Math.round(n)}`;
}

function Glyph({ kind, animClass }) {
  const props = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className: `topic-glyph ${animClass} h-[18px] w-[18px]`,
    "aria-hidden": true,
  };
  switch (kind) {
    case "trophy":
      return (
        <svg {...props}>
          <path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4zM7 7H4v2a3 3 0 0 0 3 3M17 7h3v2a3 3 0 0 1-3 3" />
        </svg>
      );
    case "basketball":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3v18M5.3 5.3c3.7 1.9 9.7 7.9 13.4 13.4M18.7 5.3c-3.7 1.9-9.7 7.9-13.4 13.4" />
        </svg>
      );
    case "soccer":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <polygon points="12,7 16,10 14.5,15 9.5,15 8,10" />
          <path d="M12 3v4M21 12l-5-2M3 12l5-2M16 21l-1.5-6M8 21l1.5-6" />
        </svg>
      );
    case "controller":
      return (
        <svg {...props}>
          <path d="M6 12h3M7.5 10.5v3M15 11h.01M17.5 13h.01" />
          <path d="M2 14a4 4 0 0 1 4-4h12a4 4 0 0 1 4 4v1.5a3 3 0 0 1-5.7 1.3L15 15H9l-1.3 1.8A3 3 0 0 1 2 15.5V14z" />
        </svg>
      );
    case "building":
      return (
        <svg {...props}>
          <path d="M3 21h18M3 11h18M12 3l9 8M12 3L3 11M5.5 21V11M9 21V11M15 21V11M18.5 21V11" />
        </svg>
      );
    case "globe":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
      );
    case "ballot":
      return (
        <svg {...props}>
          <rect x="4" y="6" width="16" height="14" rx="1.5" />
          <path d="M9 12l2.2 2.2L15 10" />
        </svg>
      );
    case "coin":
      return (
        <svg {...props} style={{ transformStyle: "preserve-3d" }}>
          <circle cx="12" cy="12" r="9" />
          <path d="M9.5 7.5v9M11 6v1.5M11 16.5V18M9.5 9.5h4.5a2 2 0 0 1 0 4H9.5M9.5 13.5h5a2 2 0 0 1 0 4h-5" />
        </svg>
      );
    case "chart":
      return (
        <svg {...props}>
          <path d="M3 17l5-5 4 4 8-8M14 8h7v7" />
        </svg>
      );
    case "sparkles":
      return (
        <svg {...props}>
          <path d="M12 4l1.4 4.6L18 10l-4.6 1.4L12 16l-1.4-4.6L6 10l4.6-1.4zM18.5 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7zM5 16l.5 1.5L7 18l-1.5.5L5 20l-.5-1.5L3 18l1.5-.5z" />
        </svg>
      );
    default:
      return null;
  }
}

function PulseDot({ state }) {
  const isLive = state === "live";
  return (
    <span
      aria-label={isLive ? "Active in last hour" : "Active in last 24h"}
      className={isLive ? "animate-pulse-live" : ""}
      style={{
        width: 5,
        height: 5,
        borderRadius: "50%",
        background: isLive ? "var(--bullish)" : "var(--warning)",
        boxShadow: isLive
          ? "0 0 6px var(--bullish), 0 0 1px var(--bullish)"
          : undefined,
        flexShrink: 0,
      }}
    />
  );
}

function HoverPreview({ alert, rect, familyColor }) {
  if (!alert || !rect) return null;
  const headline = alert.llm_headline || alert.market_title;
  const usd = formatUsd(alert.total_usd);
  const score = alert.composite_score
    ? Number(alert.composite_score).toFixed(1)
    : null;

  // Anchor below the pill, clamped to viewport.
  const width = 280;
  const margin = 12;
  const centerX = rect.left + rect.width / 2;
  const left = Math.max(
    margin + width / 2,
    Math.min(window.innerWidth - margin - width / 2, centerX),
  );
  const top = rect.bottom + 10;

  return (
    <div
      role="tooltip"
      className="topic-preview pointer-events-none fixed z-50 hidden md:block"
      style={{
        left,
        top,
        width,
        transform: "translateX(-50%)",
      }}
    >
      <div
        className="rounded-xl border p-3 backdrop-blur-sm"
        style={{
          background: "var(--surface-card)",
          borderColor: `color-mix(in srgb, ${familyColor} 35%, var(--border))`,
          boxShadow: `0 12px 40px -12px color-mix(in srgb, ${familyColor} 40%, transparent), 0 4px 12px rgba(0,0,0,0.08)`,
        }}
      >
        <div className="flex items-start gap-2.5">
          {alert.market_image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={alert.market_image}
              alt=""
              className="h-10 w-10 flex-shrink-0 rounded-md object-cover"
              style={{ background: "var(--surface-2)" }}
            />
          ) : (
            <div
              className="h-10 w-10 flex-shrink-0 rounded-md"
              style={{ background: `color-mix(in srgb, ${familyColor} 15%, var(--surface-2))` }}
            />
          )}
          <div className="min-w-0 flex-1">
            <div
              className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: familyColor, fontFamily: "var(--font-display)" }}
            >
              {score && <span>{score}★</span>}
              {score && usd && (
                <span style={{ color: "var(--text-muted)" }}>·</span>
              )}
              {usd && <span style={{ color: "var(--text-secondary)" }}>{usd}</span>}
            </div>
            <p
              className="text-xs leading-snug font-medium"
              style={{
                color: "var(--text-primary)",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {headline}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function TopicNav() {
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [topicData, setTopicData] = useState({});
  const [hovered, setHovered] = useState(null);

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

  // Fetch latest alert per topic in parallel for pulse + hover preview.
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      TOPICS.map(async (t) => {
        try {
          const res = await fetchAlerts({ tag: t.name, perPage: 1 });
          return [t.name, { latest: res.alerts?.[0] ?? null, total: res.total ?? 0 }];
        } catch {
          return [t.name, null];
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setTopicData(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function scroll(dir) {
    scrollRef.current?.scrollBy({ left: dir * 200, behavior: "smooth" });
  }

  const handleEnter = useCallback((name, e) => {
    setHovered({ name, rect: e.currentTarget.getBoundingClientRect() });
  }, []);
  const handleLeave = useCallback(() => setHovered(null), []);

  // Hide preview if the strip is scrolled while hovering (prevents stale anchor).
  useEffect(() => {
    if (!hovered) return;
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", handleLeave, { passive: true });
    return () => el.removeEventListener("scroll", handleLeave);
  }, [hovered, handleLeave]);

  const hoveredTopic = hovered ? TOPICS.find((t) => t.name === hovered.name) : null;
  const hoveredData = hovered ? topicData[hovered.name] : null;

  return (
    <nav className="relative mb-5" aria-label="Topics">
      {canScrollLeft && (
        <div
          className="absolute left-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
          style={{ background: "linear-gradient(to right, var(--surface-0), transparent)" }}
        />
      )}
      {canScrollRight && (
        <div
          className="absolute right-0 top-0 bottom-0 w-10 z-10 pointer-events-none"
          style={{ background: "linear-gradient(to left, var(--surface-0), transparent)" }}
        />
      )}

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

      <div
        ref={scrollRef}
        className="flex items-center gap-1.5 overflow-x-auto no-scrollbar"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
      >
        {TOPICS.map(({ name, family, glyph, anim }) => {
          const familyColor = FAMILY_COLORS[family];
          const data = topicData[name];
          const pulse = pulseStateFor(data?.latest?.created_at);
          const recency = formatRecency(data?.latest?.created_at);
          const count = data ? formatCount(data.total) : "—";
          return (
            <Link
              key={name}
              href={`/tag/${tagSlug(name)}`}
              onMouseEnter={(e) => handleEnter(name, e)}
              onMouseLeave={handleLeave}
              onFocus={(e) => handleEnter(name, e)}
              onBlur={handleLeave}
              className="topic-pill flex items-center gap-2.5 rounded-xl border px-3.5 py-2 whitespace-nowrap"
              style={{
                background: "var(--surface-card)",
                borderColor: "var(--border)",
                color: "var(--text-secondary)",
                "--family-color": familyColor,
              }}
            >
              <Glyph kind={glyph} animClass={anim} />
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-1.5 leading-none">
                  <span
                    className="text-[13px] font-semibold"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {name}
                  </span>
                  {pulse && <PulseDot state={pulse} />}
                </div>
                <div
                  className="flex items-center gap-1 text-[10px] leading-none"
                  style={{
                    fontFamily: "var(--font-display)",
                    color: "var(--text-muted)",
                    letterSpacing: "0.04em",
                  }}
                >
                  <span>{count}</span>
                  {recency && (
                    <>
                      <span style={{ opacity: 0.4 }}>·</span>
                      <span>{recency}</span>
                    </>
                  )}
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {hoveredData?.latest && hoveredTopic && (
        <HoverPreview
          alert={hoveredData.latest}
          rect={hovered.rect}
          familyColor={FAMILY_COLORS[hoveredTopic.family]}
        />
      )}
    </nav>
  );
}
