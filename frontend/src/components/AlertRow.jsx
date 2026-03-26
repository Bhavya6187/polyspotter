import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAlertDetail } from "../lib/api";
import PriceMovement from "./PriceMovement";

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
  const now = Date.now();
  const end = new Date(dateStr).getTime();
  const diffMs = end - now;
  if (diffMs <= 0) return "Resolved";
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

function shortenWallet(w) {
  if (!w || w.length < 12) return w || "\u2014";
  return `${w.slice(0, 6)}\u2026${w.slice(-4)}`;
}

export default function AlertRow({ alert, autoExpand, activeTag, onTagClick, compact, liveMarket }) {
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showTrades, setShowTrades] = useState(false);

  const tags = alert.tags || [];
  const copyAction = alert.llm_copy_action;

  const alertOutcome = copyAction?.outcome;
  const alertPrice = copyAction?.entry_price;
  const liveOutcome = liveMarket?.outcomes?.find(
    (o) => o.name === alertOutcome
  );
  const currentPrice = liveOutcome?.price ?? null;
  const resolution = timeToResolution(alert.end_date);

  useEffect(() => {
    if (!autoExpand) return;
    let cancelled = false;
    setLoadingDetail(true);
    fetchAlertDetail(alert.id).then((data) => {
      if (!cancelled) {
        setDetail(data);
        setLoadingDetail(false);
      }
    }).catch(() => {
      if (!cancelled) setLoadingDetail(false);
    });
    return () => { cancelled = true; };
  }, [alert.id, autoExpand]);

  let betSummary = "";
  if (copyAction && copyAction.outcome) {
    const priceStr = priceToCents(copyAction.entry_price);
    betSummary = `${usdFmt.format(alert.total_usd)} on ${copyAction.outcome}${priceStr ? ` at ${priceStr}` : ""}`;
  } else {
    betSummary = `${usdFmt.format(alert.total_usd)}`;
  }

  let compactLabel = null;
  if (alert.llm_headline) {
    compactLabel = alert.llm_headline;
  } else if (alert.cluster_headline) {
    compactLabel = alert.cluster_headline;
  } else if (alert.win_rate != null) {
    const wr = `${Math.round(alert.win_rate * 100)}% wins`;
    const pnl = alert.total_pnl != null
      ? ` \u00b7 ${alert.total_pnl >= 0 ? "+" : ""}${usdFmt.format(alert.total_pnl)}`
      : "";
    compactLabel = `Wallet with ${wr}${pnl}`;
  }

  const detailCopyAction = detail?.llm_copy_action || copyAction;
  const marketUrl = detail?.market_url;
  let ctaText = "";
  if (detailCopyAction && detailCopyAction.outcome) {
    const side = detailCopyAction.side === "SELL" ? "Sell" : "Buy";
    ctaText = `${side} ${detailCopyAction.outcome}`;
  }

  const bullets = detail?.llm_bullets || [];
  const displayBullets =
    bullets.length > 0 ? bullets : detail?.llm_summary ? [detail.llm_summary] : [];

  const effectivePrice = detailCopyAction?.side === "SELL" && currentPrice > 0 ? 1 - currentPrice : currentPrice;

  return (
    <div
      className="rounded-xl border transition-all animate-fade-up"
      style={{
        borderColor: 'var(--border)',
        background: 'var(--surface-card)',
        padding: compact ? '12px 16px' : '16px 20px',
      }}
    >
      {/* Row 1: Title/label + resolution */}
      <div className="flex items-start justify-between gap-3">
        {compact ? (
          <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {compactLabel ?? "\u2014"}
          </span>
        ) : (
          <h3 className="text-sm font-semibold leading-snug" style={{ color: 'var(--text-primary)' }}>
            {alert.market_title ?? "\u2014"}
          </h3>
        )}
        <div className="flex shrink-0 items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
          {!compact && !autoExpand && resolution && (
            <span
              className={
                resolution === "Resolved"
                  ? ""
                  : new Date(alert.end_date).getTime() - Date.now() < 3600000
                    ? "font-medium"
                    : ""
              }
              style={{
                color: resolution === "Resolved"
                  ? 'var(--text-muted)'
                  : new Date(alert.end_date).getTime() - Date.now() < 3600000
                    ? 'var(--bearish)'
                    : new Date(alert.end_date).getTime() - Date.now() < 86400000
                      ? 'var(--warning)'
                      : 'var(--text-muted)'
              }}
            >
              {resolution}
            </span>
          )}
          <span>{relativeTime(alert.scanned_at)}</span>
        </div>
      </div>

      {/* Row 2: Bet summary + live price */}
      <div className="mt-1.5 flex items-center gap-2">
        <p className="text-sm font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)', fontSize: compact ? '0.8rem' : '0.875rem' }}>
          {betSummary}
        </p>
        {alertPrice > 0 && currentPrice > 0 && (
          <PriceMovement
            alertPrice={alertPrice}
            currentPrice={currentPrice}
            outcome={alertOutcome}
            compact
          />
        )}
      </div>

      {/* Detail section (auto-expanded) */}
      {autoExpand && (
        <div className="mt-3">
          {loadingDetail ? (
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Loading...
            </div>
          ) : (
            <>
              {displayBullets.length > 0 && (
                <ul className="space-y-1.5 mt-1">
                  {displayBullets.map((bullet, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--accent)' }} />
                      <span>{bullet}</span>
                    </li>
                  ))}
                </ul>
              )}
              {ctaText && marketUrl && (
                <div className="mt-4 flex items-center gap-3">
                  <a
                    href={marketUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 active:scale-[0.98]"
                    style={{ background: 'var(--accent)', boxShadow: 'var(--glow-medium)' }}
                  >
                    Copy trade &rarr; {ctaText}
                  </a>
                  {effectivePrice > 0 && effectivePrice < 0.99 && (
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                      {Math.round(effectivePrice * 100)}&cent; &rarr; $1.00
                      <span className="ml-1 font-semibold" style={{ color: 'var(--bullish)' }}>
                        +{Math.round(((1 - effectivePrice) / effectivePrice) * 100)}%
                      </span>
                    </span>
                  )}
                </div>
              )}

              {/* Individual trades */}
              {detail?.trades?.length > 0 && (
                <div className="mt-4">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowTrades((v) => !v);
                    }}
                    className="inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    <span className={`inline-block transition-transform ${showTrades ? "rotate-90" : ""}`}>&#9654;</span>
                    {showTrades ? "Hide" : "Show"} {detail.trades.length} trade{detail.trades.length !== 1 ? "s" : ""}
                  </button>

                  {showTrades && (
                    <div className="mt-2 overflow-x-auto rounded-lg border" style={{ borderColor: 'var(--border)' }}>
                      <table className="w-full text-xs">
                        <thead>
                          <tr style={{ background: 'var(--surface-1)' }}>
                            <th className="px-3 py-2 text-left font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>Wallet</th>
                            <th className="px-3 py-2 text-left font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>Side</th>
                            <th className="px-3 py-2 text-left font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>Outcome</th>
                            <th className="px-3 py-2 text-right font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>Amount</th>
                            <th className="px-3 py-2 text-right font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>Price</th>
                            <th className="px-3 py-2 text-right font-medium" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontSize: '0.65rem' }}>When</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.trades.map((t, i) => (
                            <tr
                              key={t.transaction_hash || i}
                              style={{ borderTop: i > 0 ? '1px solid var(--border-subtle)' : 'none' }}
                            >
                              <td className="px-3 py-2" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-secondary)' }}>
                                <a
                                  href={`https://polygonscan.com/tx/${t.transaction_hash}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  className="transition-colors hover:underline"
                                  style={{ color: 'var(--info)' }}
                                  title={t.wallet}
                                >
                                  {shortenWallet(t.wallet)}
                                </a>
                              </td>
                              <td className="px-3 py-2 font-semibold" style={{ color: t.side === "BUY" ? 'var(--bullish)' : 'var(--bearish)' }}>
                                {t.side}
                              </td>
                              <td className="px-3 py-2" style={{ color: 'var(--text-secondary)' }}>{t.outcome ?? "\u2014"}</td>
                              <td className="px-3 py-2 text-right font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}>
                                {usdFmt.format(t.usd_value)}
                              </td>
                              <td className="px-3 py-2 text-right" style={{ fontFamily: 'var(--font-display)', color: 'var(--text-secondary)' }}>
                                {priceToCents(t.price) ?? "\u2014"}
                              </td>
                              <td className="px-3 py-2 text-right" style={{ color: 'var(--text-muted)' }}>
                                {relativeTime(t.trade_timestamp)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Tags (full mode only) */}
      {!compact && !autoExpand && tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <Link
              key={t}
              href={`/tag/${encodeURIComponent(t.toLowerCase().replace(/\s+/g, "-"))}`}
              onClick={(e) => e.stopPropagation()}
              className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors"
              style={{
                background: activeTag === t ? 'var(--accent)' : 'var(--surface-2)',
                color: activeTag === t ? '#fff' : 'var(--text-muted)',
              }}
            >
              {t}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
