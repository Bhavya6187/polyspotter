// Proof hero, distilled to one number: what $100 on every graded call would have
// returned over the window (return × calls × $100). The dollar figure is the
// unfakeable edge — far more visceral than a bare percentage — and it doubles as
// the hook into the daily digest CTA below it. Shows a "building" state until
// >= MIN_GRADED calls exist so a tiny early sample never reads as a claim.

import Link from "next/link";
import EmailCapture from "./EmailCapture";

const MIN_GRADED = 10;

// Flat $100-per-call profit, rounded to the nearest $100 (it's an estimate).
function asDollars(amount) {
  if (!Number.isFinite(amount)) return "—";
  const rounded = Math.round(amount / 100) * 100 || 0; // `|| 0` normalizes -0
  const sign = rounded >= 0 ? "+" : "−";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

function formatShortDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

// The newsletter pitch — shared by the live and "building" hero states.
function DigestCTA({ latestDigest }) {
  return (
    <div
      className="mt-6 rounded-xl p-4 sm:p-5"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-[11px] font-bold uppercase tracking-[0.18em]"
          style={{ color: "var(--accent)", fontFamily: "var(--font-display)" }}
        >
          The Daily Brief
        </span>
        <span
          className="h-px flex-1"
          style={{ background: "var(--border)" }}
          aria-hidden="true"
        />
      </div>

      <p
        className="mt-2 text-base font-semibold leading-snug sm:text-lg"
        style={{ color: "var(--text-primary)" }}
      >
        Every sharp call, in your inbox before the market wakes up.
      </p>

      {latestDigest && (
        <Link
          href={`/digest/${latestDigest.digest_date}`}
          className="group mt-3 flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors"
          style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
        >
          <span
            className="shrink-0 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
            style={{ background: "var(--accent)", color: "var(--surface-0)" }}
          >
            Latest
          </span>
          <span className="min-w-0 flex-1">
            <span
              className="block truncate text-sm font-medium"
              style={{ color: "var(--text-primary)" }}
            >
              {latestDigest.subject}
            </span>
            <span className="block text-xs" style={{ color: "var(--text-muted)" }}>
              {formatShortDate(latestDigest.digest_date)} edition
            </span>
          </span>
          <span
            className="shrink-0 text-sm font-semibold transition-transform group-hover:translate-x-0.5"
            style={{ color: "var(--accent)" }}
            aria-hidden="true"
          >
            Read →
          </span>
        </Link>
      )}

      <div className="mt-3">
        <EmailCapture source="hero" />
      </div>
    </div>
  );
}

export default function ScoreboardHero({ scoreboard, latestDigest }) {
  const window = scoreboard?.window;
  const allTime = scoreboard?.all_time;
  const gradedCount = allTime ? allTime.wins + allTime.losses : 0;

  const shell =
    "relative mb-6 overflow-hidden rounded-2xl p-6 sm:p-8";
  const shellStyle = {
    background: "var(--surface-card)",
    border: "1px solid var(--border)",
  };

  if (!window || gradedCount < MIN_GRADED) {
    return (
      <section aria-label="Track record" className={shell} style={shellStyle}>
        <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          We grade every call we make.
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          PolySpotter tracks Polymarket&rsquo;s sharpest wallets and scores each
          call against the result.{" "}
          {gradedCount > 0
            ? `Building our track record — ${gradedCount} call${gradedCount === 1 ? "" : "s"} graded so far.`
            : "Our public track record is being built now."}
        </p>
        <DigestCTA latestDigest={latestDigest} />
      </section>
    );
  }

  const windowCount = window.wins + window.losses;
  const profit = window.copy_return_pct * windowCount * 100; // flat $100 / call
  const isUp = Math.round(profit / 100) * 100 >= 0;
  const numberColor = isUp ? "var(--bullish)" : "var(--bearish)";

  return (
    <section aria-label="Track record" className={shell} style={shellStyle}>
      {/* Soft accent glow behind the number — atmosphere, not a box */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full opacity-[0.18] blur-3xl"
        style={{ background: numberColor }}
      />

      <div className="relative">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span
              className="animate-pulse-live absolute inline-flex h-full w-full rounded-full opacity-75"
              style={{ background: "var(--accent)" }}
            />
            <span
              className="relative inline-flex h-2 w-2 rounded-full"
              style={{ background: "var(--accent)" }}
            />
          </span>
          <span
            className="text-[11px] font-bold uppercase tracking-[0.18em]"
            style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
          >
            Track record · last {scoreboard.window_days} days
          </span>
        </div>

        <div
          className="mt-3 text-6xl font-extrabold leading-none tracking-tight tabular-nums sm:text-7xl"
          style={{ color: numberColor }}
        >
          {asDollars(profit)}
        </div>

        <p
          className="mt-3 max-w-md text-sm leading-relaxed"
          style={{ color: "var(--text-secondary)" }}
        >
          What you&rsquo;d be up putting{" "}
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>$100</span>{" "}
          on every graded call we&rsquo;ve made.
        </p>
      </div>

      <DigestCTA latestDigest={latestDigest} />
    </section>
  );
}
