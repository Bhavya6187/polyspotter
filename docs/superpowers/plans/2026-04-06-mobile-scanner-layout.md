# Mobile Scanner Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase mobile information density 2-3x and add native quick-share — all mobile-only, desktop untouched.

**Architecture:** Modify 7 existing frontend components. All changes scoped to `< sm` (640px) breakpoint using Tailwind responsive classes. No new files, no backend changes, no new dependencies. Engagement via localStorage and Web Share API (no auth).

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind CSS 4, Web Share API, localStorage

**Spec:** `docs/superpowers/specs/2026-04-06-mobile-scanner-layout-design.md`

---

### Task 1: Hero Compression — Hide Ticker on Mobile

**Files:**
- Modify: `frontend/src/app/home-client.jsx:160-162`

- [ ] **Step 1: Hide the ticker section on mobile**

In `frontend/src/app/home-client.jsx`, change the ticker section wrapper from:

```jsx
      {/* Live ticker */}
      <section aria-label="Live ticker" className="mb-5 -mx-4 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
        <Ticker />
      </section>
```

to:

```jsx
      {/* Live ticker — hidden on mobile, duplicates feed */}
      <section aria-label="Live ticker" className="hidden sm:block mb-5 sm:mx-0 sm:rounded-xl sm:overflow-hidden">
        <Ticker />
      </section>
```

- [ ] **Step 2: Verify in browser**

Run: `cd frontend && npm run dev`

Open http://localhost:3000 at 375px width — ticker should be gone.
Open at 640px+ — ticker should appear as before.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/home-client.jsx
git commit -m "feat: hide ticker on mobile to save vertical space"
```

---

### Task 2: Hero Compression — Compact HeroSpotlight on Mobile

**Files:**
- Modify: `frontend/src/components/HeroSpotlight.jsx:21-60`

- [ ] **Step 1: Compact the SpotlightSlide padding and hide sparkline/label on mobile**

In `frontend/src/components/HeroSpotlight.jsx`, replace the `SpotlightSlide` component's return JSX (lines 21-61):

```jsx
  return (
    <Link href={href} className="block flex flex-col gap-2 sm:gap-3 px-4 py-3 sm:px-5 sm:py-5 rounded-xl transition-shadow hover:shadow-md"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="hidden sm:block text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Biggest move right now
          </p>
          <div className="flex items-center gap-2.5 mt-0 sm:mt-1">
            {alert.market_image && (
              <Image
                src={alert.market_image}
                alt=""
                width={32}
                height={32}
                className="h-8 w-8 rounded-lg object-cover shrink-0"
              />
            )}
            <h2 className="text-base sm:text-lg font-bold truncate" style={{ color: "var(--text-primary)" }}>
              {alert.market_title}
            </h2>
          </div>
          <p className="text-sm mt-1" style={{ color: "var(--accent)" }}>
            {usdFmt.format(alert.total_usd)} in smart money flow
            {alert.wallet_count > 1 ? ` \u00b7 ${alert.wallet_count} sharp wallets aligned` : ""}
          </p>
        </div>
        {alert.candles?.length > 0 && (
          <div className="hidden sm:block shrink-0">
            <Sparkline candles={alert.candles} entryPrice={entryPrice} width={140} height={48} />
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        {alert.best_win_rate != null && (
          <span>{"\ud83c\udfaf"} {Math.round(alert.best_win_rate * 100)}% win rate wallet</span>
        )}
        <span>{"\u23f1\ufe0f"} Resolves in {countdown.label}</span>
      </div>
    </Link>
  );
```

Key changes:
- Padding: `px-4 py-3 sm:px-5 sm:py-5`
- Gap: `gap-2 sm:gap-3`
- "Biggest move right now" label: `hidden sm:block`
- Sparkline container: `hidden sm:block`
- Title: `text-base sm:text-lg`
- Top margin on title row: `mt-0 sm:mt-1`

- [ ] **Step 2: Verify in browser**

At 375px: Hero card should be shorter — no "Biggest move" label, no sparkline chart, tighter padding.
At 640px+: No visual change from current.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HeroSpotlight.jsx
git commit -m "feat: compact HeroSpotlight on mobile — hide label and sparkline"
```

---

### Task 3: Hero Compression — Compact ResolvingSoonStrip on Mobile

**Files:**
- Modify: `frontend/src/components/ResolvingSoonStrip.jsx:17-55`

- [ ] **Step 1: Compact the ResolvingCard padding and font on mobile**

In `frontend/src/components/ResolvingSoonStrip.jsx`, replace the `ResolvingCard` component's return JSX:

```jsx
  return (
    <Link href={`/market/${slug}`} className="shrink-0">
      <div
        className={`rounded-lg px-3 py-2 sm:px-4 sm:py-3 transition-all ${urgent ? "animate-urgency" : ""}`}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderLeftWidth: 3,
          borderLeftColor: urgent ? "var(--bearish)" : "var(--warning)",
          minWidth: 160,
          maxWidth: 260,
        }}
      >
        <div className="flex items-center gap-2 mb-0.5">
          {alert.market_image && (
            <Image
              src={alert.market_image}
              alt=""
              width={20}
              height={20}
              className="h-5 w-5 rounded object-cover shrink-0"
            />
          )}
          <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
            {alert.market_title}
          </p>
        </div>
        <p
          className="text-sm sm:text-lg font-bold mt-0.5"
          style={{ color: urgent ? "var(--bearish)" : "var(--warning)", fontFamily: "var(--font-display)" }}
        >
          {countdown.label}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {usdFmt.format(alert.total_usd)} smart money
          {alert.dominant_side ? ` on ${alert.dominant_side}` : ""}
        </p>
      </div>
    </Link>
  );
```

Key changes:
- Padding: `px-3 py-2 sm:px-4 sm:py-3`
- Countdown font: `text-sm sm:text-lg`
- `minWidth`: 200 → 160

- [ ] **Step 2: Verify in browser**

At 375px: Resolving soon cards should be smaller with compact countdown text.
At 640px+: No visual change.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ResolvingSoonStrip.jsx
git commit -m "feat: compact ResolvingSoonStrip cards on mobile"
```

---

### Task 4: Enhanced ShareButton — Native Share API + iconOnly

**Files:**
- Modify: `frontend/src/components/ShareButton.jsx`

- [ ] **Step 1: Rewrite ShareButton with native share support and iconOnly prop**

Replace the entire contents of `frontend/src/components/ShareButton.jsx`:

```jsx
"use client";

import { useState } from "react";

export default function ShareButton({ url, title, text, compact = false, iconOnly = false }) {
  const [copied, setCopied] = useState(false);

  async function handleShare(e) {
    e.stopPropagation();

    // Try native share API first (mobile browsers)
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({
          title: title || "PolySpotter",
          text: text || "",
          url,
        });
        return;
      } catch (err) {
        // AbortError = user dismissed, fall through to clipboard
        if (err.name !== "AbortError") {
          // Fall through to clipboard
        }
      }
    }

    // Clipboard fallback
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const shareIcon = (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13" />
    </svg>
  );

  return (
    <button
      onClick={handleShare}
      className="inline-flex items-center gap-1.5 rounded-lg text-xs transition-colors"
      style={{
        padding: iconOnly ? "4px" : compact ? "4px 8px" : "6px 14px",
        background: iconOnly ? "transparent" : "var(--surface-1)",
        color: copied ? "var(--accent)" : "var(--text-muted)",
        border: iconOnly ? "none" : "1px solid var(--border-subtle)",
      }}
      aria-label="Share"
    >
      {iconOnly ? (
        shareIcon
      ) : (
        <>
          {copied ? "\u2713 Copied" : shareIcon}
          {!copied && <span className="hidden sm:inline">Share</span>}
        </>
      )}
    </button>
  );
}
```

Key changes:
- New props: `title`, `text`, `iconOnly`
- Tries `navigator.share()` first, catches `AbortError` silently
- Falls back to clipboard copy (existing behavior)
- `iconOnly` mode: just the icon, no background/border, for compact cards
- Non-iconOnly mode: hides "Share" text on mobile (`hidden sm:inline`), shows icon always
- `e.stopPropagation()` on click to prevent card expansion

- [ ] **Step 2: Verify in browser**

Test on desktop: clicking Share should copy URL, show "Copied".
The `navigator.share` path is only testable on mobile devices/emulators.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ShareButton.jsx
git commit -m "feat: ShareButton with native Web Share API and iconOnly mode"
```

---

### Task 5: Compact Alert Cards — Expand/Collapse on Mobile

**Files:**
- Modify: `frontend/src/components/AlertList.jsx:182-302`

- [ ] **Step 1: Add expand/collapse state and compact view to MarketGroupCard**

In `frontend/src/components/AlertList.jsx`, replace the `MarketGroupCard` component (lines 182-303) with:

```jsx
/** A market group card with signal-based visual hierarchy. */
function MarketGroupCard({ market, liveData, index }) {
  const alert = pickBestAlert(market.alerts);
  if (!alert) return null;
  const tags = market.tags || [];
  const rating = scoreToRating(alert.composite_score);
  const isStrong = rating >= 4;
  const isHero = index === 0 && rating >= 3;

  const resolution = timeToResolution(market.end_date);
  const resolutionMs = market.end_date ? new Date(market.end_date).getTime() - Date.now() : null;
  const isResolved = resolutionMs != null && resolutionMs <= 0;
  const isUrgent = resolutionMs != null && resolutionMs > 0 && resolutionMs < 3600000;
  const isSoon = resolutionMs != null && resolutionMs > 0 && resolutionMs < 86400000;

  const marketUrl = market.market_url || alert.market_url;

  // Mobile: collapsed by default. Desktop: always expanded. Hero card: always expanded.
  const [expanded, setExpanded] = useState(isHero);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 640px)");
    setIsDesktop(mq.matches);
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const showExpanded = isDesktop || expanded;

  // Compact summary data
  const copyAction = alert.llm_copy_action;
  let compactBet = usdFmt.format(alert.total_usd);
  if (copyAction?.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    compactBet = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  }
  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;
  const liveMarket = liveData[alert.condition_id];
  const liveOutcome = liveMarket?.outcomes?.find((o) => o.name === alertOutcome);
  const currentPrice = liveOutcome?.price ?? null;

  // Card border/glow style based on signal strength
  const cardStyle = {
    borderColor: isStrong ? 'rgba(0, 194, 106, 0.3)' : 'var(--border)',
    background: isHero ? 'var(--surface-card)' : 'var(--surface-card)',
    boxShadow: isStrong ? 'var(--glow-medium)' : 'none',
  };

  return (
    <div
      className={`rounded-xl border card-hover animate-fade-up ${isStrong && !isResolved ? 'animate-glow-border' : ''} ${isUrgent ? 'animate-urgency' : ''}`}
      style={{ ...cardStyle, opacity: isResolved ? 0.6 : 1, animationDelay: `${index * 60}ms` }}
    >
      {/* Market header */}
      <Link
        href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
        className="group/header flex items-start justify-between gap-3 px-5 py-4 rounded-t-xl transition-all hover:bg-[var(--accent-subtle)]"
      >
        <div className="flex items-center gap-3 min-w-0">
          {market.market_image && (
            <Image
              src={market.market_image}
              alt=""
              width={32}
              height={32}
              className="h-6 w-6 sm:h-8 sm:w-8 rounded-lg object-cover shrink-0"
            />
          )}
          <StrengthMeter maxScore={alert.composite_score} />
          <span
            className="text-sm font-semibold leading-snug truncate transition-colors group-hover/header:text-[var(--accent)]"
            style={{ color: 'var(--text-primary)' }}
          >
            {market.market_title ?? "\u2014"}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isResolved ? (
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium" style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
              Resolved
            </span>
          ) : resolution && (
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              isUrgent
                ? 'text-red-600 dark:text-red-400'
                : isSoon
                  ? 'text-amber-600 dark:text-amber-400'
                  : ''
            }`} style={{
              background: isUrgent ? 'rgba(239, 68, 68, 0.1)' : isSoon ? 'rgba(245, 158, 11, 0.1)' : 'var(--surface-card)',
              color: !isUrgent && !isSoon ? 'var(--text-muted)' : undefined
            }}>
              {isUrgent && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                </span>
              )}
              {resolution}
            </span>
          )}
          <span className="text-xs" style={{ color: 'var(--text-muted)' }} suppressHydrationWarning>
            {relativeTime(alert.created_at)}
          </span>
          <svg className="h-4 w-4 shrink-0 opacity-30 group-hover/header:opacity-70 group-hover/header:translate-x-0.5 transition-all duration-200" style={{ color: 'var(--text-muted)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </Link>

      {/* Alert content */}
      <div className="px-5 pb-4">
        {showExpanded ? (
          /* Full expanded view — identical to current */
          <AlertEntry alert={alert} liveData={liveData} />
        ) : (
          /* Compact view — mobile only */
          <div
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => setExpanded(true)}
          >
            {alert.wallet && alert.win_rate != null && (
              <WalletBadge
                wallet={alert.wallet}
                winRate={alert.win_rate}
                totalPnl={alert.total_pnl}
                totalInvested={alert.total_invested}
                compact
              />
            )}
            <span
              className="text-sm font-semibold truncate flex-1"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}
            >
              {compactBet}
            </span>
            {alertPrice > 0 && currentPrice > 0 && (
              <PriceMovement alertPrice={alertPrice} currentPrice={currentPrice} outcome={alertOutcome} compact />
            )}
            <ShareButton
              url={`${typeof window !== 'undefined' ? window.location.origin : ''}/alert/${alert.id}`}
              title={`PolySpotter: ${market.market_title}`}
              text={`Sharp money alert: ${compactBet}`}
              iconOnly
            />
            <svg
              className="h-4 w-4 shrink-0 transition-transform"
              style={{ color: 'var(--text-muted)' }}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        )}
      </div>

      {/* Collapse button when expanded on mobile */}
      {showExpanded && !isDesktop && expanded && (
        <button
          onClick={() => setExpanded(false)}
          className="w-full border-t py-2 text-xs font-medium transition-colors"
          style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}
        >
          Show less
        </button>
      )}

      {/* Footer: tags (desktop only) + view market */}
      <div className="flex flex-wrap items-center gap-3 border-t px-5 py-3" style={{ borderColor: 'var(--border-subtle)' }}>
        {tags.length > 0 && (
          <div className="hidden sm:flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <Link
                key={t}
                href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}
                className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
              >
                {t}
              </Link>
            ))}
          </div>
        )}
        {marketUrl && (
          <Link
            href={`/market/${marketSlug(market.market_title, market.condition_id)}`}
            className="inline-flex items-center gap-1 text-xs font-medium transition-colors ml-auto"
            style={{ color: 'var(--text-muted)' }}
          >
            View market
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add missing imports to AlertList.jsx**

At the top of `AlertList.jsx`, ensure these are imported (add `useEffect` to the existing React import):

```jsx
import { useState, useEffect, Fragment } from "react";
```

`useEffect` is needed for the media query listener in `MarketGroupCard`.

- [ ] **Step 3: Verify in browser**

At 375px: Cards should show compact 2-line view. Tapping expands. First strong card auto-expanded. Tags hidden in footer.
At 640px+: All cards fully expanded, tags visible — identical to current.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AlertList.jsx
git commit -m "feat: compact alert cards on mobile with expand/collapse"
```

---

### Task 6: Collapsible Filters with localStorage Memory

**Files:**
- Modify: `frontend/src/components/Filters.jsx`
- Modify: `frontend/src/app/home-client.jsx`

- [ ] **Step 1: Add localStorage persistence to home-client.jsx**

In `frontend/src/app/home-client.jsx`, replace the `filters` state initialization and add a persistence effect. Change:

```jsx
  const [filters, setFilters] = useState({
    tag: "",
    resolvesIn: "",
    minScore: "",
  });
```

to:

```jsx
  const [filters, setFilters] = useState({
    tag: "",
    resolvesIn: "",
    minScore: "",
  });

  // Load saved filters from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem("polyspotter_filters");
      if (saved) {
        const parsed = JSON.parse(saved);
        setFilters((prev) => ({ ...prev, ...parsed }));
        setHasInteracted(true);
      }
    } catch {}
  }, []);

  // Persist filters to localStorage on change
  useEffect(() => {
    if (!hasInteracted) return;
    try {
      localStorage.setItem("polyspotter_filters", JSON.stringify(filters));
    } catch {}
  }, [filters, hasInteracted]);
```

- [ ] **Step 2: Make Filters collapsible on mobile**

Replace the entire contents of `frontend/src/components/Filters.jsx`:

```jsx
"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

const RESOLVE_OPTIONS = [
  { label: "Any", value: "" },
  { label: "< 6h", value: "6h" },
  { label: "< 24h", value: "24h" },
  { label: "< 7d", value: "7d" },
];

const SEVERITY_OPTIONS = [
  { label: "All", value: "" },
  { label: "Medium+", value: "6" },
  { label: "Strong+", value: "10" },
  { label: "Very Strong", value: "15" },
];

const SEVERITY_LABELS = { "6": "Medium+", "10": "Strong+", "15": "Very Strong" };
const RESOLVE_LABELS = { "6h": "< 6h", "24h": "< 24h", "7d": "< 7d" };

function Pill({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
      style={{
        background: active ? 'var(--accent)' : 'var(--surface-card)',
        color: active ? '#fff' : 'var(--text-secondary)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        boxShadow: active ? 'var(--glow-medium)' : 'none',
      }}
    >
      {label}
    </button>
  );
}

function TagPill({ label, active, href }) {
  return (
    <Link
      href={href}
      className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all"
      style={{
        background: active ? 'var(--accent)' : 'var(--surface-card)',
        color: active ? '#fff' : 'var(--text-secondary)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        boxShadow: active ? 'var(--glow-medium)' : 'none',
      }}
    >
      {label}
    </Link>
  );
}

export default function Filters({ tags, filters, onFilterChange }) {
  const [collapsed, setCollapsed] = useState(true);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 640px)");
    setIsDesktop(mq.matches);
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const sorted = [...tags]
    .sort((a, b) => {
      const ca = typeof a === "object" ? a.alert_count || 0 : 0;
      const cb = typeof b === "object" ? b.alert_count || 0 : 0;
      return cb - ca;
    })
    .slice(0, 10);

  // Count active filters
  const activeCount = [filters.tag, filters.resolvesIn, filters.minScore].filter(Boolean).length;

  // Build summary pills for collapsed state
  const summaryParts = [];
  if (filters.resolvesIn && RESOLVE_LABELS[filters.resolvesIn]) {
    summaryParts.push(RESOLVE_LABELS[filters.resolvesIn]);
  }
  if (filters.minScore && SEVERITY_LABELS[filters.minScore]) {
    summaryParts.push(SEVERITY_LABELS[filters.minScore]);
  }
  if (filters.tag) {
    summaryParts.push(filters.tag);
  }

  const showExpanded = isDesktop || !collapsed;

  const filterRows = (
    <div className="flex flex-col gap-3">
      {/* Row 1: Resolution window */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Resolves
        </span>
        {RESOLVE_OPTIONS.map((opt) => (
          <Pill
            key={opt.value}
            label={opt.label}
            active={filters.resolvesIn === opt.value}
            onClick={() => onFilterChange({ ...filters, resolvesIn: opt.value })}
          />
        ))}
      </div>

      {/* Row 2: Severity */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Severity
        </span>
        {SEVERITY_OPTIONS.map((opt) => (
          <Pill
            key={opt.value}
            label={opt.label}
            active={(filters.minScore || "") === opt.value}
            onClick={() => onFilterChange({ ...filters, minScore: opt.value })}
          />
        ))}
      </div>

      {/* Row 3: Tags */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest mr-1" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-muted)', fontSize: '0.6rem' }}>
          Topic
        </span>
        <Pill
          label="All"
          active={!filters.tag}
          onClick={() => onFilterChange({ ...filters, tag: "" })}
        />
        {sorted.map((t) => {
          const name = typeof t === "string" ? t : t.tag;
          const count = typeof t === "object" && t.alert_count ? t.alert_count : null;
          const slug = encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
          return (
            <TagPill
              key={name}
              label={count ? `${name} (${count})` : name}
              active={filters.tag === name}
              href={`/tag/${slug}`}
            />
          );
        })}
      </div>
    </div>
  );

  // Desktop: always show filter rows
  if (isDesktop) {
    return filterRows;
  }

  // Mobile: collapsible
  return (
    <div>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all"
        style={{
          background: activeCount > 0 ? 'var(--accent)' : 'var(--surface-card)',
          color: activeCount > 0 ? '#fff' : 'var(--text-secondary)',
          border: `1px solid ${activeCount > 0 ? 'var(--accent)' : 'var(--border)'}`,
        }}
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
        </svg>
        Filters{activeCount > 0 ? ` (${activeCount})` : ""}
        <svg
          className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-180"}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Active filter summary when collapsed */}
      {collapsed && summaryParts.length > 0 && (
        <button
          onClick={() => setCollapsed(false)}
          className="mt-1.5 flex flex-wrap gap-1.5"
        >
          {summaryParts.map((part) => (
            <span
              key={part}
              className="rounded-full px-2 py-0.5 text-xs font-medium"
              style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
            >
              {part}
            </span>
          ))}
        </button>
      )}

      {/* Expanded filter panel */}
      {showExpanded && (
        <div className="mt-3">
          {filterRows}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify in browser**

At 375px:
- Filters should show a single "Filters" button by default.
- Tapping expands the full filter panel.
- Selecting a filter and reloading the page should restore the selection.
- Active filter summary pills should appear when collapsed with active filters.

At 640px+: Filter rows always visible, no collapse button — identical to current.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Filters.jsx frontend/src/app/home-client.jsx
git commit -m "feat: collapsible filters on mobile with localStorage persistence"
```

---

### Task 7: Market Detail — Compact Header + Sticky Outcome Bar

**Files:**
- Modify: `frontend/src/app/market/[id]/market-page-client.jsx`

- [ ] **Step 1: Add sticky outcome bar, compact thumbnail, compact outcome pills, and chart reorder**

Replace the entire contents of `frontend/src/app/market/[id]/market-page-client.jsx`:

```jsx
"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import AlertRow from "../../../components/AlertRow";
import PriceMovement from "../../../components/PriceMovement";
import PriceChart from "../../../components/PriceChart";
import MarketStats from "../../../components/MarketStats";
import HoldersLeaderboard from "../../../components/HoldersLeaderboard";
import MarketPulse from "../../../components/MarketPulse";
import MarketTheses from "../../../components/MarketTheses";
import useLiveMarket from "../../../hooks/useLiveMarket";
import ThemeToggle from "../../../components/ThemeToggle";
import ShareButton from "../../../components/ShareButton";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return "Resolved";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

export default function MarketPageClient({
  conditionId,
  initialLive,
  initialAlerts,
  priceHistory,
  holders,
  theses,
}) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];
  const [descExpanded, setDescExpanded] = useState(false);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const isUrgent = endDate && new Date(endDate).getTime() - Date.now() < 3600000 && new Date(endDate).getTime() - Date.now() > 0;
  const isSoon = endDate && new Date(endDate).getTime() - Date.now() < 86400000 && new Date(endDate).getTime() - Date.now() > 0;

  const outcomes = live?.outcomes || [];
  const description = alerts?.[0]?.market_description || live?.description;

  // Sticky bar: show when header scrolls out of view
  const headerRef = useRef(null);
  const [showStickyBar, setShowStickyBar] = useState(false);

  useEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    const observer = new IntersectionObserver(
      ([entry]) => setShowStickyBar(!entry.isIntersecting),
      { threshold: 0 }
    );
    observer.observe(header);
    return () => observer.disconnect();
  }, []);

  // Share text for this market
  const shareText = outcomes.length > 0
    ? outcomes.map((o) => `${o.name} ${Math.round((o.price || 0) * 100)}\u00a2`).join(" / ") + ` \u2014 ${alerts.length} signal${alerts.length !== 1 ? "s" : ""}`
    : `${alerts.length} signal${alerts.length !== 1 ? "s" : ""}`;

  return (
    <main className="mx-auto max-w-5xl px-4 py-4">
      {/* Sticky outcome bar — mobile only */}
      {showStickyBar && (
        <div
          className="sm:hidden fixed top-0 left-0 right-0 z-20 flex items-center justify-between px-4 py-2 border-b"
          style={{ background: 'var(--surface-0)', borderColor: 'var(--border)' }}
        >
          <span className="text-sm font-semibold truncate flex-1" style={{ color: 'var(--text-primary)' }}>
            {title}
          </span>
          <div className="flex items-center gap-2 shrink-0 ml-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              return (
                <span key={o.name} className="text-xs font-medium" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-secondary)' }}>
                  {o.name} {pct}&cent;
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Nav */}
      <nav className="mb-4 flex items-center justify-between" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: 'var(--text-muted)' }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <div className="flex items-center gap-2">
          <ShareButton
            url={typeof window !== 'undefined' ? window.location.href : ''}
            title={`PolySpotter: ${title}`}
            text={shareText}
            iconOnly
          />
          <ThemeToggle />
        </div>
      </nav>

      {/* Compact header */}
      <header className="mb-4" ref={headerRef}>
        <div className="flex gap-3 sm:gap-4 items-start">
          {/* Thumbnail — smaller on mobile */}
          {alerts?.[0]?.market_image && (
            <div
              className="relative shrink-0 rounded-lg overflow-hidden w-[48px] h-[48px] sm:w-[72px] sm:h-[72px]"
              style={{ border: "1px solid var(--border)" }}
            >
              <Image
                src={alerts[0].market_image}
                alt=""
                fill
                className="object-cover"
              />
            </div>
          )}

          {/* Title + meta */}
          <div className="flex-1 min-w-0">
            <h1
              className="text-lg font-bold leading-tight"
              style={{ color: 'var(--text-primary)' }}
            >
              {title}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
              {resolution && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"
                  style={{
                    background: isUrgent ? 'rgba(239, 68, 68, 0.1)' : isSoon ? 'rgba(245, 158, 11, 0.1)' : 'var(--surface-2)',
                    color: resolution === "Resolved"
                      ? 'var(--text-muted)'
                      : isUrgent
                        ? 'var(--bearish)'
                        : isSoon
                          ? 'var(--warning)'
                          : 'var(--text-secondary)',
                    fontSize: '0.65rem',
                  }}
                >
                  {isUrgent && (
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                    </span>
                  )}
                  {resolution}
                </span>
              )}
              {totalUsd > 0 && (
                <span style={{ fontFamily: 'var(--font-display)' }}>
                  {usdFmt.format(totalUsd)} tracked
                </span>
              )}
              <span>{alerts.length} signal{alerts.length !== 1 ? "s" : ""}</span>
              {tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full px-1.5 py-0.5"
                  style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', fontSize: '0.6rem' }}
                >
                  {t}
                </span>
              ))}
            </div>
          </div>

          {/* Inline outcome pills — desktop only */}
          {outcomes.length > 0 && (
            <div className="hidden sm:flex items-center gap-2 shrink-0">
              {outcomes.map((o) => {
                const pct = Math.round((o.price || 0) * 100);
                const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
                const isLeading = pct === maxPct && pct > 50;
                return (
                  <div
                    key={o.name}
                    className="rounded-lg border px-3 py-1.5 text-center"
                    style={{
                      borderColor: isLeading ? 'rgba(0, 194, 106, 0.3)' : 'var(--border)',
                      background: 'var(--surface-card)',
                      boxShadow: isLeading ? 'var(--glow-medium)' : 'none',
                      minWidth: '72px',
                    }}
                  >
                    <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
                      {o.name}
                    </div>
                    <div
                      className="text-lg font-bold tabular-nums leading-tight"
                      style={{
                        fontFamily: 'var(--font-display)',
                        color: isLeading ? 'var(--accent)' : 'var(--text-primary)',
                      }}
                    >
                      {pct}&cent;
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Mobile-only outcome row — compact */}
        {outcomes.length > 0 && (
          <div className="sm:hidden mt-3 flex gap-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
              const isLeading = pct === maxPct && pct > 50;
              return (
                <div
                  key={o.name}
                  className="flex-1 rounded-lg border px-3 py-1 text-center"
                  style={{
                    borderColor: isLeading ? 'rgba(0, 194, 106, 0.3)' : 'var(--border)',
                    background: 'var(--surface-card)',
                    boxShadow: isLeading ? 'var(--glow-medium)' : 'none',
                  }}
                >
                  <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
                    {o.name}
                  </div>
                  <div
                    className="text-base font-bold tabular-nums leading-tight"
                    style={{
                      fontFamily: 'var(--font-display)',
                      color: isLeading ? 'var(--accent)' : 'var(--text-primary)',
                    }}
                  >
                    {pct}&cent;
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Collapsible description */}
        {description && (
          <div className="mt-2">
            <p
              className="text-xs leading-relaxed"
              style={{
                color: 'var(--text-muted)',
                display: '-webkit-box',
                WebkitLineClamp: descExpanded ? 'unset' : 2,
                WebkitBoxOrient: 'vertical',
                overflow: descExpanded ? 'visible' : 'hidden',
              }}
            >
              {description}
            </p>
            {description.length > 140 && (
              <button
                onClick={() => setDescExpanded(!descExpanded)}
                className="mt-0.5 text-xs font-medium cursor-pointer"
                style={{ color: 'var(--accent)', background: 'none', border: 'none', padding: 0 }}
              >
                {descExpanded ? "Less" : "More"}
              </button>
            )}
          </div>
        )}
      </header>

      {/* Mobile: Price chart before alerts */}
      {priceHistory && priceHistory.history?.length > 1 && (
        <div className="lg:hidden mb-4">
          <PriceChart
            history={priceHistory.history}
            outcome={priceHistory.outcome}
            alerts={alerts}
            conditionId={conditionId}
          />
        </div>
      )}

      {/* Two-column: Trades (primary) + Sidebar (chart, stats, holders) */}
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        {/* Left: Notable Trades */}
        <section>
          {alerts.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2
                className="text-xs font-semibold uppercase tracking-widest"
                style={{
                  fontFamily: 'var(--font-display)',
                  color: 'var(--text-muted)',
                  fontSize: '0.6rem',
                }}
              >
                Notable Trades
              </h2>
              {alerts.map((alert) => (
                <AlertRow
                  key={alert.id}
                  alert={alert}
                  autoExpand
                  activeTag=""
                  onTagClick={() => {}}
                  liveMarket={live}
                />
              ))}
            </div>
          ) : (
            <div
              className="rounded-xl border p-12 text-center"
              style={{
                borderColor: 'var(--border)',
                background: 'var(--surface-card)',
                color: 'var(--text-muted)',
              }}
            >
              No signals found for this market.
            </div>
          )}
        </section>

        {/* Right sidebar: Chart (desktop only) + Stats + Holders + Pulse */}
        <aside className="flex flex-col gap-4">
          {/* Price Chart — desktop only (mobile shown above) */}
          {priceHistory && priceHistory.history?.length > 1 && (
            <div className="hidden lg:block">
              <PriceChart
                history={priceHistory.history}
                outcome={priceHistory.outcome}
                alerts={alerts}
                conditionId={conditionId}
              />
            </div>
          )}

          {/* Market Stats */}
          <MarketStats
            volume24h={live?.volume_24h}
            liquidity={live?.liquidity}
            spread={live?.spread}
            alerts={alerts}
          />

          {/* Holders + Pulse */}
          {(holders?.length > 0 || alerts.length > 0) && (
            <>
              <HoldersLeaderboard holders={holders} />
              <MarketPulse alerts={alerts} volume24h={live?.volume_24h} />
            </>
          )}
        </aside>
      </div>

      {/* Related Theses */}
      {theses?.length > 0 && (
        <div className="mt-8">
          <MarketTheses theses={theses} />
        </div>
      )}
    </main>
  );
}
```

Key changes:
- Sticky outcome bar with IntersectionObserver (mobile only, `sm:hidden`)
- ShareButton in nav bar (between back link and ThemeToggle)
- Thumbnail: `w-[48px] h-[48px] sm:w-[72px] sm:h-[72px]`
- Mobile outcome pills: `py-1` (was `py-1.5`), `text-base` (was `text-lg`)
- PriceChart rendered above alerts on mobile (`lg:hidden`), in sidebar on desktop (`hidden lg:block`)
- Added `useRef` and `useEffect` imports, `ShareButton` import

- [ ] **Step 2: Verify in browser**

Navigate to a market detail page at 375px:
- Thumbnail should be smaller (48px)
- Outcome pills should use smaller text
- Price chart should appear above "Notable Trades"
- Scrolling down should show sticky bar with title + prices
- Share icon should appear in the nav bar

At 640px+: No visual change except the share icon in nav (intentional on all sizes).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/market/[id]/market-page-client.jsx
git commit -m "feat: compact market detail header, sticky outcome bar, chart reorder, share button"
```

---

### Task 8: Update AlertEntry Share Props

**Files:**
- Modify: `frontend/src/components/AlertList.jsx:151-153`

- [ ] **Step 1: Pass title and text to ShareButton in AlertEntry**

In `frontend/src/components/AlertList.jsx`, inside the `AlertEntry` component, find the existing `ShareButton` usage:

```jsx
        <ShareButton
          url={`${typeof window !== 'undefined' ? window.location.origin : ''}/alert/${alert.id}`}
          compact
        />
```

Replace with:

```jsx
        <ShareButton
          url={`${typeof window !== 'undefined' ? window.location.origin : ''}/alert/${alert.id}`}
          title={`PolySpotter: ${alert.market_title || "Notable trade"}`}
          text={`Sharp money alert: ${betSummary}`}
          compact
        />
```

- [ ] **Step 2: Verify in browser**

Expand an alert card at 375px. The Share button in the expanded view should trigger native share sheet on mobile with the market title and bet summary pre-filled.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlertList.jsx
git commit -m "feat: pass share title and text to AlertEntry ShareButton"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Full mobile check**

Run: `cd frontend && npm run dev`

At 375px width, verify:
1. No ticker visible
2. Hero spotlight is compact (no label, no sparkline)
3. Resolving soon cards are smaller
4. Filters collapsed with "Filters" button
5. Alert cards show compact 2-line view, tap to expand
6. First strong card auto-expanded
7. Tags hidden in card footer
8. Share icon-only buttons work (native share on mobile)
9. Navigate to market detail: smaller thumbnail, compact outcome pills, chart above alerts, sticky bar on scroll, share in nav

- [ ] **Step 2: Full desktop check**

At 1024px+ width, verify:
1. Ticker visible
2. Hero spotlight unchanged (label, sparkline, full padding)
3. Resolving soon cards unchanged
4. Filters always visible (no collapse)
5. Alert cards fully expanded (no compact view)
6. Tags visible in card footer
7. Market detail: 72px thumbnail, text-lg outcomes, chart in sidebar, no sticky bar
8. Share "Share" label visible on desktop

- [ ] **Step 3: localStorage check**

1. Select "Sports" tag + "Strong+" severity
2. Reload page — filters should persist
3. Open incognito/private — should not crash (graceful fallback)

- [ ] **Step 4: Build check**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 5: Lint check**

Run: `cd frontend && npm run lint`
Expected: No new lint errors.

- [ ] **Step 6: Commit any final fixes if needed**
