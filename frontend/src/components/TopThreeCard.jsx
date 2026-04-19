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

function ifResolvesPct(entryPrice, outcome) {
  if (entryPrice == null || entryPrice <= 0 || entryPrice >= 1) return null;
  const denom = outcome === "NO" ? 1 - entryPrice : entryPrice;
  if (denom <= 0) return null;
  return Math.round((1 / denom - 1) * 100);
}

// "Copy YES" for binary props; for sports/named outcomes, use the most distinctive
// last word ("AUGUST HOLMGREN" → "Holmgren", "Top Esports" → "Top Esports").
function copyButtonLabel(outcome) {
  if (!outcome) return "Copy bet";
  const upper = outcome.toUpperCase();
  if (upper === "YES" || upper === "NO") return `Copy ${upper}`;
  const tokens = outcome.trim().split(/\s+/);
  // Multi-word names: take the last word (last name / final identifier) and Title-case it.
  const pick = tokens.length >= 2 ? tokens[tokens.length - 1] : outcome;
  const titled = pick.charAt(0).toUpperCase() + pick.slice(1).toLowerCase();
  return `Copy ${titled}`;
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

function CountdownLabel({ endDate, gameStartTime }) {
  // Prefer countdown to game start when known — that's the meaningful number
  // for sports. Falls back to resolution deadline for non-game markets.
  const target = gameStartTime || endDate;
  const countdown = useCountdown(target);
  const hoursToTarget = target ? (new Date(target).getTime() - Date.now()) / 3_600_000 : null;
  let color = "var(--text-muted)";
  if (hoursToTarget != null && hoursToTarget < 6) color = "var(--bearish)";
  else if (hoursToTarget != null && hoursToTarget < 24) color = "var(--warning)";
  const verb = gameStartTime ? "Starts in" : "Resolves in";
  return <span style={{ color }}>{verb} {countdown.label}</span>;
}

function LiveBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ background: "var(--bearish)", color: "white" }}
    >
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full"
        style={{ background: "white" }}
        aria-hidden="true"
      />
      Live
    </span>
  );
}

// Footer renders different content depending on the category — the wallet
// pseudonym only makes sense for the single-sharp-wallet conviction case.
function CardFooterContext({ alert }) {
  if (alert.category === "HIGHEST_CONVICTION") {
    const tier = computeTier(alert.wallet?.win_rate, alert.wallet?.total_invested);
    const pseudonym = walletPseudonym(alert.wallet?.address, tier);
    const avatarBg = tier?.color || "var(--border)";
    const initial = pseudonym.charAt(0).toUpperCase();
    const wr = alert.wallet?.win_rate;
    const pnl = alert.wallet?.total_pnl;
    return (
      <div className="flex items-center gap-2 text-xs min-w-0">
        <span
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
          style={{ background: avatarBg }}
        >
          {initial}
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-bold" style={{ color: "var(--text-primary)" }}>{pseudonym}</span>
          <span className="truncate" style={{ color: "var(--text-muted)" }}>
            {wr != null ? `${Math.round(wr * 100)}% WR` : "—"}
            {pnl != null ? ` · ${usdCompact.format(pnl)} PnL` : ""}
          </span>
        </div>
      </div>
    );
  }

  if (alert.category === "COORDINATED_FLOW") {
    const count = alert.wallet_count || 0;
    const total = alert.total_usd;
    return (
      <div className="flex items-center gap-2 text-xs min-w-0">
        <span
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px]"
          style={{ background: "var(--category-coordinated)", color: "white" }}
          aria-hidden="true"
        >
          {"\u{1F465}"}
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-bold" style={{ color: "var(--text-primary)" }}>
            {count >= 2 ? `${count}-wallet cluster` : "Coordinated flow"}
          </span>
          <span className="truncate" style={{ color: "var(--text-muted)" }}>
            {total != null ? `${usdCompact.format(total)} combined` : "—"}
          </span>
        </div>
      </div>
    );
  }

  // TIMING_EDGE — emphasize the countdown (or LIVE state), not a wallet.
  const live = alert.live;
  return (
    <div className="flex items-center gap-2 text-xs min-w-0">
      <span
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px]"
        style={{ background: live ? "var(--bearish)" : "var(--category-timing)", color: "white" }}
        aria-hidden="true"
      >
        {live ? "\u25CF" : "\u23F1\uFE0F"}
      </span>
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-bold" style={{ color: "var(--text-primary)" }}>
          {live ? "Game in progress" : "Closing soon"}
        </span>
        <span className="truncate" style={{ color: live ? "var(--bearish)" : "var(--text-muted)" }}>
          {live ? "Action mid-event" : (
            <CountdownLabel endDate={alert.end_date} gameStartTime={alert.game_start_time} />
          )}
        </span>
      </div>
    </div>
  );
}

export default function TopThreeCard({ alert }) {
  const meta = CATEGORY_META[alert.category] ?? CATEGORY_META.HIGHEST_CONVICTION;
  const color = `var(${meta.colorVar})`;
  const copyAction = alert.llm_copy_action || {};
  const outcome = (copyAction.outcome || "YES").toUpperCase();
  const entryPrice = copyAction.entry_price;
  const pct = ifResolvesPct(entryPrice, outcome);

  const href = `/market/${marketSlug(alert.market_title, alert.condition_id)}`;
  const isRankOne = alert.rank === 1;

  return (
    <Link
      href={href}
      className="group relative flex flex-col gap-3 overflow-hidden rounded-xl p-4 no-underline transition-shadow hover:shadow-lg"
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border)",
        color: "inherit",
        boxShadow: isRankOne ? "0 4px 16px -4px rgba(0,0,0,0.18)" : undefined,
      }}
    >
      {/* Rank-1 colored top ribbon for hierarchy */}
      {isRankOne && (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-[3px]"
          style={{ background: color }}
        />
      )}

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
            {alert.live ? (
              <LiveBadge />
            ) : (
              <CountdownLabel endDate={alert.end_date} gameStartTime={alert.game_start_time} />
            )}
          </div>
        </div>
      </div>

      {/* Summary */}
      {alert.llm_summary && (
        <p className="text-sm leading-relaxed line-clamp-3" style={{ color: "var(--text-secondary)" }}>
          {alert.llm_summary}
        </p>
      )}

      {/* Stats row — Smart Money + hero Upside */}
      <div
        className="grid grid-cols-2 gap-3 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border-subtle)", fontFamily: "var(--font-display)" }}
      >
        <div>
          <div className="uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Smart Money</div>
          <div className="mt-1 text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {alert.total_usd != null ? usdCompact.format(alert.total_usd) : "—"}
          </div>
        </div>
        <div style={{ borderLeft: "1px solid var(--border-subtle)", paddingLeft: "0.75rem" }}>
          <div className="uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Upside if hit
          </div>
          <div className="mt-1 text-2xl font-bold leading-none" style={{ color: "var(--accent)" }}>
            {pct != null ? `+${pct}%` : "—"}
          </div>
          {entryPrice != null && (
            <div className="mt-1 text-[11px]" style={{ color: "var(--text-muted)" }}>
              entry {Math.round(entryPrice * 100)}¢
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3">
        <CardFooterContext alert={alert} />
        <span
          className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-bold"
          style={{ background: "var(--accent)", color: "#0a0f1a" }}
        >
          {copyButtonLabel(copyAction.outcome)} &rarr;
        </span>
      </div>
    </Link>
  );
}
