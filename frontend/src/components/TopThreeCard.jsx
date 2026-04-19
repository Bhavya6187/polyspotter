"use client";

import Link from "next/link";
import Image from "next/image";
import { useCountdown } from "../hooks/useCountdown";
import { computeTier } from "../lib/tiers";
import { walletPseudonym } from "../lib/pseudonym";
import { marketSlug } from "../lib/slugify";

const CATEGORY_META = {
  HIGHEST_CONVICTION: { label: "HIGHEST CONVICTION", emoji: "\u26A1", colorVar: "--category-conviction" },
  COORDINATED_FLOW:   { label: "COORDINATED FLOW",   emoji: "\u{1F3AF}", colorVar: "--category-coordinated" },
  TIMING_EDGE:        { label: "TIMING EDGE",        emoji: "\u23F1\uFE0F", colorVar: "--category-timing" },
};

const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
});

function formatCents(price) {
  if (price == null) return "—";
  return `${Math.round(price * 100)}¢`;
}

function ifResolvesPct(entryPrice, outcome) {
  if (entryPrice == null || entryPrice <= 0 || entryPrice >= 1) return null;
  const denom = outcome === "NO" ? 1 - entryPrice : entryPrice;
  if (denom <= 0) return null;
  return Math.round((1 / denom - 1) * 100);
}

function SignalBars({ strength, color }) {
  const bars = [1, 2, 3, 4];
  return (
    <span className="inline-flex items-end gap-[2px]" aria-label={`Signal strength ${strength} of 4`}>
      {bars.map((i) => (
        <span
          key={i}
          className="inline-block w-[3px] rounded-sm"
          style={{
            height: `${4 + i * 2}px`,
            background: i <= strength ? color : "var(--border)",
          }}
        />
      ))}
    </span>
  );
}

function CountdownLabel({ endDate }) {
  const countdown = useCountdown(endDate);
  const hoursToEnd = endDate ? (new Date(endDate).getTime() - Date.now()) / 3_600_000 : null;
  let color = "var(--text-muted)";
  if (hoursToEnd != null && hoursToEnd < 6) color = "var(--bearish)";
  else if (hoursToEnd != null && hoursToEnd < 24) color = "var(--warning)";
  return <span style={{ color }}>Resolves in {countdown.label}</span>;
}

export default function TopThreeCard({ alert }) {
  const meta = CATEGORY_META[alert.category] ?? CATEGORY_META.HIGHEST_CONVICTION;
  const color = `var(${meta.colorVar})`;
  const copyAction = alert.llm_copy_action || {};
  const outcome = (copyAction.outcome || "YES").toUpperCase();
  const entryPrice = copyAction.entry_price;
  const pct = ifResolvesPct(entryPrice, outcome);

  const tier = computeTier(alert.wallet?.win_rate, alert.wallet?.total_invested);
  const pseudonym = walletPseudonym(alert.wallet?.address, tier);
  const avatarBg = tier?.color || "var(--border)";
  const initial = pseudonym.charAt(0).toUpperCase();

  const href = `/market/${marketSlug(alert.market_title, alert.condition_id)}`;

  const isRankOne = alert.rank === 1;
  const cardStyle = {
    background: "var(--surface-card)",
    border: "1px solid var(--border)",
    boxShadow: isRankOne ? `0 0 0 1px ${color} inset` : undefined,
  };

  return (
    <Link
      href={href}
      className="flex flex-col gap-3 rounded-xl p-4 transition-shadow hover:shadow-md no-underline"
      style={{ ...cardStyle, color: "inherit" }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider"
            style={{ color, background: "color-mix(in srgb, currentColor 12%, transparent)" }}
          >
            <span aria-hidden="true">{meta.emoji}</span>
            {meta.label}
          </span>
          <SignalBars strength={alert.strength} color={color} />
        </div>
        <span
          className="inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
          style={{ border: `1px solid ${color}`, color }}
        >
          {alert.rank}
        </span>
      </div>

      {/* Title row */}
      <div className="flex items-start gap-3">
        {alert.market_image ? (
          <Image
            src={alert.market_image}
            alt=""
            width={40}
            height={40}
            className="h-10 w-10 shrink-0 rounded-lg object-cover"
          />
        ) : (
          <div className="h-10 w-10 shrink-0 rounded-lg" style={{ background: "var(--surface-2)" }} />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3
            className="text-base font-bold leading-snug line-clamp-2"
            style={{ color: "var(--text-primary)" }}
          >
            {alert.market_title}
          </h3>
          <div className="flex items-center gap-2 text-xs" style={{ fontFamily: "var(--font-display)" }}>
            {alert.primary_tag && (
              <span
                className="rounded-full px-2 py-0.5"
                style={{ border: "1px solid var(--border)", color: "var(--text-muted)" }}
              >
                {alert.primary_tag}
              </span>
            )}
            <CountdownLabel endDate={alert.end_date} />
          </div>
        </div>
      </div>

      {/* Summary */}
      {alert.llm_summary && (
        <p className="text-sm leading-relaxed line-clamp-3" style={{ color: "var(--text-secondary)" }}>
          {alert.llm_summary}
        </p>
      )}

      {/* Stats row */}
      <div
        className="grid grid-cols-3 gap-2 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border-subtle)", fontFamily: "var(--font-display)" }}
      >
        <div>
          <div className="uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Smart Money</div>
          <div className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {alert.total_usd != null ? usdCompact.format(alert.total_usd) : "—"}
          </div>
        </div>
        <div style={{ borderLeft: "1px solid var(--border-subtle)", paddingLeft: "0.5rem" }}>
          <div className="uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Entry / Now</div>
          <div className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {formatCents(entryPrice)} <span style={{ color: "var(--text-muted)" }}>&rarr;</span> {formatCents(alert.latest_price)}
          </div>
        </div>
        <div style={{ borderLeft: "1px solid var(--border-subtle)", paddingLeft: "0.5rem" }}>
          <div className="uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            If resolves {outcome}
          </div>
          <div className="mt-1 text-lg font-bold" style={{ color: "var(--accent)" }}>
            {pct != null ? `+${pct}%` : "—"}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          <span
            className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold text-white"
            style={{ background: avatarBg }}
          >
            {initial}
          </span>
          <div className="flex flex-col">
            <span className="font-bold" style={{ color: "var(--text-primary)" }}>{pseudonym}</span>
            <span style={{ color: "var(--text-muted)" }}>
              {alert.wallet?.win_rate != null ? `${Math.round(alert.wallet.win_rate * 100)}%` : "—"}
              {alert.wallet?.total_pnl != null ? ` · ${usdCompact.format(alert.wallet.total_pnl)} PnL` : ""}
            </span>
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-bold"
          style={{ background: "var(--accent)", color: "#0a0f1a" }}
        >
          Copy {outcome} &rarr;
        </span>
      </div>
    </Link>
  );
}
