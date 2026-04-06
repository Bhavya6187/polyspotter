import Link from "next/link";
import Image from "next/image";
import { useState, useEffect, Fragment } from "react";
import { fetchMarketLive } from "../lib/api";
import { marketSlug } from "../lib/slugify";
import PriceMovement from "./PriceMovement";
import StrengthMeter from "./StrengthMeter";
import { scoreToRating } from "./StrengthMeter";
import ThesisCard from "./ThesisCard";
import WalletBadge from "./WalletBadge";
import ShareButton from "./ShareButton";

function relativeTime(dateStr) {
  if (!dateStr) return "\u2014";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.floor((now - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return null;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d`;
}

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function priceToCents(price) {
  if (price == null || price <= 0) return null;
  return `${Math.round(price * 100)}\u00a2`;
}

/** A single alert entry within a market group card. */
function AlertEntry({ alert, liveData }) {
  const copyAction = alert.llm_copy_action;
  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;

  const liveMarket = liveData[alert.condition_id];
  const liveOutcome = liveMarket?.outcomes?.find((o) => o.name === alertOutcome);
  const currentPrice = liveOutcome?.price ?? null;

  let subtitle = alert.llm_headline || alert.cluster_headline;
  if (!subtitle && alert.win_rate != null) {
    const wr = `${Math.round(alert.win_rate * 100)}%`;
    const pnl =
      alert.total_pnl != null
        ? ` \u00b7 ${alert.total_pnl >= 0 ? "+" : ""}${usdFmt.format(alert.total_pnl)}`
        : "";
    subtitle = `${wr} win rate${pnl}`;
  }

  let betSummary = usdFmt.format(alert.total_usd);
  if (copyAction?.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    betSummary = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  }

  const bullets = alert.llm_bullets || [];
  const marketUrl = alert.market_url;

  let ctaLabel = "";
  if (copyAction?.outcome) {
    const side = copyAction.side === "SELL" ? "Sell" : "Buy";
    ctaLabel = `${side} ${copyAction.outcome}`;
  }

  // Payout math
  const effectivePrice = copyAction?.side === "SELL" && currentPrice > 0 ? 1 - currentPrice : currentPrice;
  const returnPct = effectivePrice > 0 && effectivePrice < 0.99 ? Math.round(((1 - effectivePrice) / effectivePrice) * 100) : 0;

  return (
    <div className="flex flex-col gap-2.5">
      {/* Subtitle */}
      {subtitle && (
        <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
          {subtitle}
        </p>
      )}

      {/* Wallet badge */}
      {alert.wallet && alert.win_rate != null && (
        <WalletBadge
          wallet={alert.wallet}
          winRate={alert.win_rate}
          totalPnl={alert.total_pnl}
          totalInvested={alert.total_invested}
          compact
        />
      )}

      {/* Bet summary + price movement */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}>
          {betSummary}
        </span>
        {alertPrice > 0 && currentPrice > 0 && (
          <PriceMovement alertPrice={alertPrice} currentPrice={currentPrice} outcome={alertOutcome} compact />
        )}
      </div>

      {/* Bullets */}
      {bullets.length > 0 && (
        <ul className="space-y-1.5">
          {bullets.map((bullet, i) => (
            <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--accent)' }} />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      )}

      {/* CTA + payout */}
      <div className="flex items-center gap-3 pt-1">
        {ctaLabel && marketUrl ? (
          <a
            href={marketUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: 'var(--accent)', boxShadow: 'var(--glow-medium)' }}
          >
            <span>Copy trade</span>
            <span style={{ opacity: 0.8 }}>→</span>
            <span>{ctaLabel}</span>
          </a>
        ) : ctaLabel ? (
          <span className="rounded-lg border px-4 py-2 text-sm font-medium" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            {ctaLabel}
          </span>
        ) : null}
        <ShareButton
          url={`${typeof window !== 'undefined' ? window.location.origin : ''}/alert/${alert.id}`}
          title={`PolySpotter: ${alert.market_title || "Notable trade"}`}
          text={`Sharp money alert: ${betSummary}`}
          compact
        />
        {effectivePrice > 0 && effectivePrice < 0.99 && returnPct > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {Math.round(effectivePrice * 100)}&cent; → $1.00
            <span className="ml-1 font-semibold" style={{ color: 'var(--bullish)' }}>
              +{returnPct}%
            </span>
          </span>
        )}
      </div>
    </div>
  );
}

/** Pick the best alert: most recent first, highest score as tiebreaker. */
function pickBestAlert(alerts) {
  if (!alerts || alerts.length === 0) return null;
  if (alerts.length === 1) return alerts[0];
  return alerts.reduce((best, a) => {
    const bestTime = best.created_at ? new Date(best.created_at).getTime() : 0;
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    if (aTime > bestTime) return a;
    if (aTime === bestTime && a.composite_score > best.composite_score) return a;
    return best;
  });
}

/** A market group card with signal-based visual hierarchy. */
function MarketGroupCard({ market, liveData, index }) {
  const alert = pickBestAlert(market.alerts);
  if (!alert) return null;
  const tags = market.tags || [];
  const rating = scoreToRating(alert.composite_score);
  const isStrong = rating >= 4;
  const isHero = index === 0 && rating >= 3;

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

  const resolution = timeToResolution(market.end_date);
  const resolutionMs = market.end_date ? new Date(market.end_date).getTime() - Date.now() : null;
  const isResolved = resolutionMs != null && resolutionMs <= 0;
  const isUrgent = resolutionMs != null && resolutionMs > 0 && resolutionMs < 3600000;
  const isSoon = resolutionMs != null && resolutionMs > 0 && resolutionMs < 86400000;

  const marketUrl = market.market_url || alert.market_url;

  // Compact row data
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
          <AlertEntry alert={alert} liveData={liveData} />
        ) : (
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
              className="flex-1 text-sm font-semibold truncate"
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
              className="h-3.5 w-3.5 shrink-0"
              style={{ color: 'var(--text-muted)' }}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        )}
      </div>

      {/* Collapse button on mobile when expanded */}
      {showExpanded && !isDesktop && expanded && (
        <button
          onClick={() => setExpanded(false)}
          className="w-full border-t text-xs py-2 transition-colors"
          style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}
        >
          Show less
        </button>
      )}

      {/* Footer: tags + view market */}
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

export default function AlertList({ markets, filters, loading, theses = [] }) {
  const [liveData, setLiveData] = useState({});

  useEffect(() => {
    if (!markets || markets.length === 0) return;
    const cids = markets.map((m) => m.condition_id).filter(Boolean);
    if (cids.length === 0) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      cids.forEach((cid) => {
        fetchMarketLive(cid)
          .then((data) => {
            if (!cancelled) {
              setLiveData((prev) => ({ ...prev, [cid]: data }));
            }
          })
          .catch(() => {});
      });
    }, 100);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [markets]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-xl border animate-pulse" style={{ borderColor: 'var(--border)', background: 'var(--surface-card)', height: '160px' }} />
        ))}
      </div>
    );
  }

  if (!markets || markets.length === 0) {
    return (
      <div className="rounded-xl border p-12 text-center" style={{ borderColor: 'var(--border)', background: 'var(--surface-card)', color: 'var(--text-muted)' }}>
        <svg className="mx-auto mb-3 h-8 w-8 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        No signals detected yet.
      </div>
    );
  }

  // Client-side resolve window filter
  const resolvesInMs = {
    "6h": 21600000,
    "24h": 86400000,
    "7d": 604800000,
  }[filters.resolvesIn] || null;

  const afterResolve = resolvesInMs
    ? markets.filter((m) => {
        if (!m.end_date) return false;
        const ms = new Date(m.end_date).getTime() - Date.now();
        return ms > 0 && ms <= resolvesInMs;
      })
    : markets;

  const filtered = [...afterResolve].sort((a, b) => {
    const aAlert = pickBestAlert(a.alerts);
    const bAlert = pickBestAlert(b.alerts);
    const aTime = aAlert?.created_at ? new Date(aAlert.created_at).getTime() : 0;
    const bTime = bAlert?.created_at ? new Date(bAlert.created_at).getTime() : 0;
    if (bTime !== aTime) return bTime - aTime;
    return (bAlert?.composite_score || 0) - (aAlert?.composite_score || 0);
  });

  if (filtered.length === 0) {
    return (
      <div className="rounded-xl border p-12 text-center" style={{ borderColor: 'var(--border)', background: 'var(--surface-card)', color: 'var(--text-muted)' }}>
        No signals match these filters.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {filtered.map((market, i) => (
        <Fragment key={market.condition_id}>
          <MarketGroupCard market={market} liveData={liveData} index={i} />
          {(i + 1) % 4 === 0 && theses[Math.floor(i / 4)] && (
            <ThesisCard thesis={theses[Math.floor(i / 4)]} />
          )}
        </Fragment>
      ))}
    </div>
  );
}
