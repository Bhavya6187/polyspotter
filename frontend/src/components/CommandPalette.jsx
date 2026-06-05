"use client";

import { useState, useEffect, useRef, useCallback, Fragment } from "react";
import { useRouter } from "next/navigation";
import { fetchMarketAlerts } from "../lib/api";

// Tag icons — maps tag names to emoji for visual distinction
const TAG_ICONS = {
  sports: "🏟️",
  politics: "🏛️",
  geopolitics: "🌍",
  crypto: "₿",
  economy: "📊",
  culture: "🎭",
  tech: "💻",
  science: "🔬",
  blackout: "🔒",
};

function getTagIcon(tag) {
  const key = tag.toLowerCase();
  for (const [k, v] of Object.entries(TAG_ICONS)) {
    if (key.includes(k)) return v;
  }
  return "📌";
}

function formatEndDate(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  if (diffMs <= 0) return "Resolved";
  const diffH = Math.floor(diffMs / 3600000);
  if (diffH < 1) return `${Math.floor(diffMs / 60000)}m left`;
  if (diffH < 24) return `${diffH}h left`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 7) return `${diffD}d left`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function tagSlug(name) {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

/**
 * Score and re-rank markets by relevance to the query.
 * The API sorts by total_usd which ignores text relevance entirely.
 */
function rankByRelevance(markets, query) {
  const q = query.toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);

  return [...markets]
    .map((m) => {
      const title = (m.market_title || "").toLowerCase();
      const tags = (m.tags || []).map((t) => (t || "").toLowerCase());
      let score = 0;

      // Exact full query appears in title
      if (title.includes(q)) score += 50;

      // Title starts with query
      if (title.startsWith(q)) score += 30;

      // Per-word matching: each query word found in title adds score
      const wordHits = words.filter((w) => title.includes(w)).length;
      score += (wordHits / words.length) * 40;

      // All query words present (bonus for full match)
      if (wordHits === words.length) score += 25;

      // Tag match: query exactly equals a tag (strong) or appears in one (weaker).
      // Sits below a strong title match but above fuzzy/partial ones.
      if (tags.some((t) => t === q)) score += 35;
      else if (tags.some((t) => t.includes(q) || q.includes(t))) score += 20;

      // Words appear close together (adjacency bonus)
      if (words.length > 1) {
        const positions = words
          .map((w) => title.indexOf(w))
          .filter((p) => p >= 0)
          .sort((a, b) => a - b);
        if (positions.length >= 2) {
          const span = positions[positions.length - 1] - positions[0];
          // Shorter span = words are closer together = higher score
          if (span < 30) score += 20;
          else if (span < 60) score += 10;
        }
      }

      // Light boost for higher signal strength (so among equally relevant
      // results, the ones with more smart money surface first)
      score += Math.min((m.total_usd || 0) / 100000, 5);

      return { ...m, _relevance: score };
    })
    .sort((a, b) => b._relevance - a._relevance);
}

function highlightMatch(text, query) {
  if (!query.trim() || !text) return text;
  const idx = text.toLowerCase().indexOf(query.trim().toLowerCase());
  if (idx === -1) return text;
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + query.trim().length);
  const after = text.slice(idx + query.trim().length);
  return (
    <>
      {before}
      <span style={{ color: "var(--accent)", fontWeight: 700 }}>{match}</span>
      {after}
    </>
  );
}

export default function CommandPalette({ tags = [], topWallets = [] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [resolvesIn, setResolvesIn] = useState("");
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const router = useRouter();

  // Build flat item list for keyboard nav
  const items = buildItems(query, results, tags, topWallets, loading);

  // Search — fetch more than needed, re-rank by relevance, show top 8
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    const id = setTimeout(() => {
      fetchMarketAlerts({
        page: 1,
        perPage: 20,
        q: query.trim(),
        resolvesWithin: resolvesIn || undefined,
      })
        .then((data) => {
          const ranked = rankByRelevance(data.markets || [], query.trim());
          setResults(ranked.slice(0, 8));
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(id);
  }, [query, resolvesIn]);

  // Reset active index when items change
  useEffect(() => {
    setActiveIndex(0);
  }, [query, results.length]);

  // Cmd+K to open, Escape to close
  useEffect(() => {
    function handleKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery("");
      setResults([]);
      setActiveIndex(0);
      setResolvesIn("");
    }
  }, [open]);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const navigate = useCallback((item) => {
    if (!item || item.type === "heading") return;
    setOpen(false);
    if (item.href) {
      router.push(item.href);
    }
  }, [router]);

  const handleKeyDown = useCallback((e) => {
    const navigableItems = items.filter((i) => i.type !== "heading");
    const currentNavIdx = (() => {
      let count = -1;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type !== "heading") count++;
        if (i === activeIndex) return count;
      }
      return 0;
    })();

    if (e.key === "ArrowDown") {
      e.preventDefault();
      // Find next non-heading item
      let next = activeIndex + 1;
      while (next < items.length && items[next].type === "heading") next++;
      if (next < items.length) setActiveIndex(next);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      let prev = activeIndex - 1;
      while (prev >= 0 && items[prev].type === "heading") prev--;
      if (prev >= 0) setActiveIndex(prev);
    } else if (e.key === "Enter") {
      e.preventDefault();
      navigate(items[activeIndex]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  }, [activeIndex, items, navigate]);

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${activeIndex}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const sortedTags = [...tags]
    .filter((t) => {
      const name = typeof t === "string" ? t : t.tag;
      return name && name !== "Hide From New";
    })
    .sort((a, b) => {
      const ca = typeof a === "object" ? a.alert_count || 0 : 0;
      const cb = typeof b === "object" ? b.alert_count || 0 : 0;
      return cb - ca;
    });

  return (
    <>
      {/* Trigger button — prominent, fluid: fills the flex container it sits in */}
      <button
        onClick={() => setOpen(true)}
        className="group flex w-full items-center gap-3 rounded-xl border px-4 h-11 text-sm transition-all hover:border-[var(--accent)] focus:outline-none focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-subtle)]"
        style={{
          background: "var(--surface-card)",
          borderColor: "var(--border)",
          color: "var(--text-muted)",
        }}
        aria-label="Open search"
      >
        <svg
          className="h-4 w-4 shrink-0 transition-colors group-hover:text-[var(--accent)]"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <span className="flex-1 text-left truncate">
          Search markets, topics, wallets<span className="hidden sm:inline">…</span>
        </span>
        <kbd
          className="hidden sm:inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold tracking-wide"
          style={{
            color: "var(--text-muted)",
            borderColor: "var(--border)",
            background: "var(--surface-0)",
            fontFamily: "var(--font-display)",
          }}
        >
          ⌘K
        </kbd>
      </button>

      {/* Modal */}
      {open && (
        <div className="fixed inset-0 z-[100] flex items-start justify-center" onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
          {/* Backdrop */}
          <div
            className="absolute inset-0"
            onClick={() => setOpen(false)}
            style={{
              background: "rgba(0, 0, 0, 0.6)",
              backdropFilter: "blur(8px)",
              WebkitBackdropFilter: "blur(8px)",
            }}
          />

          {/* Palette */}
          <div
            className="relative w-full max-w-xl mt-[10vh] sm:mt-[15vh] mx-4 rounded-2xl border overflow-hidden"
            style={{
              background: "var(--surface-card)",
              borderColor: "var(--border)",
              boxShadow: "0 25px 60px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.05) inset",
              maxHeight: "min(520px, 70vh)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Search input */}
            <div
              className="flex items-center gap-3 px-4 py-3 border-b"
              style={{ borderColor: "var(--border)" }}
            >
              <svg className="h-5 w-5 shrink-0" style={{ color: "var(--text-muted)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Search markets, topics, wallets..."
                className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--text-muted)]"
                style={{ color: "var(--text-primary)" }}
              />
              {query && (
                <button onClick={() => setQuery("")} className="p-1 rounded-md hover:bg-[var(--surface-1)]">
                  <svg className="h-4 w-4" style={{ color: "var(--text-muted)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
              <kbd
                className="hidden sm:inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium"
                style={{ color: "var(--text-muted)", borderColor: "var(--border)", background: "var(--surface-0)" }}
              >
                esc
              </kbd>
            </div>

            {/* Resolution filter pills */}
            {query.trim() && (
              <div
                className="flex items-center gap-1.5 px-4 py-2 border-b"
                style={{ borderColor: "var(--border)" }}
              >
                <span className="text-[10px] font-medium uppercase tracking-wider mr-1" style={{ color: "var(--text-muted)" }}>
                  Resolves
                </span>
                {[
                  { label: "Any", value: "" },
                  { label: "< 1d", value: "24h" },
                  { label: "< 7d", value: "7d" },
                  { label: "< 30d", value: "30d" },
                ].map((opt) => {
                  const active = resolvesIn === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => setResolvesIn(opt.value)}
                      className="rounded-md px-2 py-1 text-[11px] font-medium transition-all"
                      style={{
                        background: active ? "var(--accent)" : "var(--surface-1)",
                        color: active ? "#fff" : "var(--text-muted)",
                        border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
                      }}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Results / Browse */}
            <div ref={listRef} className="overflow-y-auto flex-1 py-2" style={{ scrollbarWidth: "thin" }}>
              {items.map((item, i) => {
                if (item.type === "heading") {
                  return (
                    <div
                      key={item.key}
                      className="px-4 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {item.label}
                    </div>
                  );
                }

                const isActive = i === activeIndex;
                return (
                  <button
                    key={item.key}
                    data-idx={i}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors"
                    style={{
                      background: isActive ? "var(--surface-1)" : "transparent",
                      borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                    }}
                    onClick={() => navigate(item)}
                    onMouseEnter={() => setActiveIndex(i)}
                  >
                    {/* Icon */}
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg text-sm shrink-0"
                      style={{
                        background: item.iconBg || "var(--surface-2)",
                        fontSize: item.iconIsEmoji ? "16px" : "12px",
                      }}
                    >
                      {item.icon}
                    </span>

                    {/* Label + meta */}
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-medium truncate" style={{ color: "var(--text-primary)" }}>
                        {item.highlight ? highlightMatch(item.label, query) : item.label}
                      </p>
                      {item.meta && (
                        <p className="text-[11px] truncate mt-0.5" style={{ color: "var(--text-muted)" }}>
                          {item.meta}
                        </p>
                      )}
                    </div>

                    {/* Right badge */}
                    {item.badge && (
                      <span
                        className="text-[10px] font-medium rounded-full px-2 py-0.5 shrink-0"
                        style={{
                          background: item.badgeBg || "var(--surface-2)",
                          color: item.badgeColor || "var(--text-muted)",
                        }}
                      >
                        {item.badge}
                      </span>
                    )}

                    {/* Arrow */}
                    <svg
                      className="h-3.5 w-3.5 shrink-0 transition-opacity"
                      style={{ color: "var(--text-muted)", opacity: isActive ? 0.5 : 0 }}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                );
              })}

              {/* Loading state for search */}
              {loading && query.trim() && (
                <div className="flex items-center justify-center py-8 gap-2">
                  <div className="h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>Searching...</span>
                </div>
              )}

              {/* No results */}
              {!loading && query.trim() && results.length === 0 && (
                <div className="px-4 py-8 text-center">
                  <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                    No markets found for &quot;{query}&quot;
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--text-muted)", opacity: 0.6 }}>
                    Try a different search term
                  </p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div
              className="flex items-center justify-between px-4 py-2 border-t text-[10px]"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              <div className="flex items-center gap-3">
                <span className="flex items-center gap-1">
                  <kbd className="rounded border px-1 py-px" style={{ borderColor: "var(--border)", background: "var(--surface-0)" }}>↑</kbd>
                  <kbd className="rounded border px-1 py-px" style={{ borderColor: "var(--border)", background: "var(--surface-0)" }}>↓</kbd>
                  navigate
                </span>
                <span className="flex items-center gap-1">
                  <kbd className="rounded border px-1 py-px" style={{ borderColor: "var(--border)", background: "var(--surface-0)" }}>↵</kbd>
                  open
                </span>
              </div>
              <span style={{ opacity: 0.6 }}>
                {query.trim() ? `${results.length} result${results.length !== 1 ? "s" : ""}` : "Browse or search"}
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** Build a flat list of items (headings + navigable items) */
function buildItems(query, results, tags, topWallets, loading) {
  const items = [];

  if (query.trim()) {
    // Merge top-level tags (from /api/tags) with tags on the returned markets
    // so tag pages for less-common tags (e.g. "NFL") still appear in search.
    const q = query.toLowerCase();
    const tagCounts = new Map(); // name -> { name, count, isPromoted }
    for (const t of tags) {
      const name = typeof t === "string" ? t : t.tag;
      if (!name || name === "Hide From New") continue;
      tagCounts.set(name, {
        name,
        count: typeof t === "object" ? t.alert_count || 0 : 0,
        isPromoted: true,
      });
    }
    for (const m of results) {
      for (const name of m.tags || []) {
        if (!name || name === "Hide From New") continue;
        if (!tagCounts.has(name)) {
          tagCounts.set(name, { name, count: 0, isPromoted: false });
        }
      }
    }

    const matchingTags = [...tagCounts.values()]
      .filter((t) => t.name.toLowerCase().includes(q))
      .sort((a, b) => {
        // Exact match first, then prefix, then by signal count
        const an = a.name.toLowerCase();
        const bn = b.name.toLowerCase();
        const aExact = an === q ? 0 : an.startsWith(q) ? 1 : 2;
        const bExact = bn === q ? 0 : bn.startsWith(q) ? 1 : 2;
        if (aExact !== bExact) return aExact - bExact;
        return (b.count || 0) - (a.count || 0);
      })
      .slice(0, 3);

    if (matchingTags.length > 0) {
      items.push({ type: "heading", label: "Topics", key: "h-topics" });
      matchingTags.forEach(({ name, count }) => {
        items.push({
          type: "tag",
          key: `tag-${name}`,
          label: name,
          meta: count ? `${count} signals` : null,
          icon: getTagIcon(name),
          iconIsEmoji: true,
          iconBg: "var(--accent-subtle)",
          href: `/tag/${tagSlug(name)}`,
          badge: null,
          highlight: true,
        });
      });
    }

    // Market results
    if (results.length > 0) {
      items.push({ type: "heading", label: "Markets", key: "h-markets" });
      results.forEach((m) => {
        items.push({
          type: "market",
          key: `market-${m.condition_id}`,
          label: m.market_title,
          meta: `$${Math.round(m.total_usd).toLocaleString()} tracked · ${m.alert_count} signal${m.alert_count !== 1 ? "s" : ""}${m.end_date ? ` · ${formatEndDate(m.end_date)}` : ""}`,
          icon: m.market_image
            ? <img src={m.market_image} alt="" className="h-full w-full rounded-lg object-cover" />
            : <svg className="h-4 w-4" style={{ color: "var(--text-muted)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2 12l5-5 4 4 4-6 7 7" /></svg>,
          iconBg: m.market_image ? "transparent" : "var(--surface-2)",
          href: `/market/${m.condition_id}`,
          highlight: true,
        });
      });
    }

    // Matching wallets
    const matchingWallets = topWallets.filter(
      (w) => w.wallet && w.wallet.toLowerCase().includes(query.toLowerCase())
    ).slice(0, 3);
    if (matchingWallets.length > 0) {
      items.push({ type: "heading", label: "Wallets", key: "h-wallets-search" });
      matchingWallets.forEach((w) => {
        items.push({
          type: "wallet",
          key: `wallet-${w.wallet}`,
          label: `${w.wallet.slice(0, 6)}...${w.wallet.slice(-4)}`,
          meta: `${w.alert_count} signals`,
          icon: "👤",
          iconIsEmoji: true,
          iconBg: "var(--surface-2)",
          href: `/wallet/${w.wallet}`,
          highlight: true,
        });
      });
    }

    return items;
  }

  // Browse mode (no query)
  const sortedTags = [...tags]
    .filter((t) => {
      const name = typeof t === "string" ? t : t.tag;
      return name && name !== "Hide From New";
    })
    .sort((a, b) => {
      const ca = typeof a === "object" ? a.alert_count || 0 : 0;
      const cb = typeof b === "object" ? b.alert_count || 0 : 0;
      return cb - ca;
    });

  // Topics section
  if (sortedTags.length > 0) {
    items.push({ type: "heading", label: "Browse by Topic", key: "h-topics" });
    sortedTags.forEach((t) => {
      const name = typeof t === "string" ? t : t.tag;
      const count = typeof t === "object" ? t.alert_count : 0;
      items.push({
        type: "tag",
        key: `tag-${name}`,
        label: name,
        meta: count ? `${count} signals` : null,
        icon: getTagIcon(name),
        iconIsEmoji: true,
        iconBg: "var(--accent-subtle)",
        href: `/tag/${tagSlug(name)}`,
        badge: count ? `${count}` : null,
        badgeBg: "var(--surface-2)",
        badgeColor: "var(--text-muted)",
      });
    });
  }

  // Top wallets section
  if (topWallets.length > 0) {
    items.push({ type: "heading", label: "Top Wallets", key: "h-wallets" });
    topWallets.slice(0, 5).forEach((w) => {
      items.push({
        type: "wallet",
        key: `wallet-${w.wallet}`,
        label: `${w.wallet.slice(0, 6)}...${w.wallet.slice(-4)}`,
        meta: `${w.alert_count} signal${w.alert_count !== 1 ? "s" : ""}`,
        icon: "👤",
        iconIsEmoji: true,
        iconBg: "var(--surface-2)",
        href: `/wallet/${w.wallet}`,
      });
    });
  }

  return items;
}
