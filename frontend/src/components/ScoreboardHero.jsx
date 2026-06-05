// Presentational proof hero. Leads with copy return (the unfakeable edge) over
// a curated graded set (recurring-crypto coin-flips excluded server-side).
// Hit rate and the W-L record are intentionally not shown — return is the
// honest signal; hit rate just tracks entry price. Shows a "building" state
// until >= MIN_GRADED calls exist so a tiny early sample never reads as a claim.

import EmailCapture from "./EmailCapture";

const MIN_GRADED = 10;

function asSignedPct(fraction) {
  if (!Number.isFinite(fraction)) return "—";
  const v = Math.round(fraction * 100) || 0; // `|| 0` normalizes -0 to 0
  return `${v >= 0 ? "+" : ""}${v}%`;
}

// Flat $100-per-call profit, rounded to the nearest $100 (it's an estimate).
function asDollars(amount) {
  if (!Number.isFinite(amount)) return "—";
  const rounded = Math.round(amount / 100) * 100 || 0;
  const sign = rounded >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

export default function ScoreboardHero({ scoreboard }) {
  const window = scoreboard?.window;
  const allTime = scoreboard?.all_time;
  const gradedCount = allTime ? allTime.wins + allTime.losses : 0;
  const categories = scoreboard?.categories ?? [];

  const shell = "mb-6 rounded-2xl p-6 sm:p-8";
  const shellStyle = {
    background: "var(--surface-card)",
    border: "1px solid var(--border)",
  };

  if (!window || gradedCount < MIN_GRADED) {
    return (
      <section aria-label="Track record" className={shell} style={shellStyle}>
        <h2
          className="text-lg font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          We grade every call we make.
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          PolySpotter tracks Polymarket&rsquo;s sharpest wallets and scores each
          call against the result.{" "}
          {gradedCount > 0
            ? `Building our track record — ${gradedCount} call${gradedCount === 1 ? "" : "s"} graded so far.`
            : "Our public track record is being built now."}
        </p>
        <div className="mt-4 max-w-md">
          <EmailCapture source="hero" />
        </div>
      </section>
    );
  }

  const windowCount = window.wins + window.losses;
  const ret = window.copy_return_pct;
  // Color off the rounded percent we actually display, so a tiny negative that
  // renders as "+0%" never shows in red.
  const returnColor =
    Math.round(ret * 100) >= 0 ? "var(--bullish)" : "var(--bearish)";
  const profit = ret * windowCount * 100; // flat $100 on each graded call

  return (
    <section aria-label="Track record" className={shell} style={shellStyle}>
      <div
        className="text-5xl font-extrabold tracking-tight tabular-nums"
        style={{ color: returnColor }}
      >
        {asSignedPct(ret)}
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        avg return per call · last {scoreboard.window_days}d
      </div>
      <div
        className="mt-2 text-base font-semibold tabular-nums"
        style={{ color: "var(--text-secondary)" }}
      >
        ≈ {asDollars(profit)} if you&rsquo;d put $100 on every call
      </div>

      <p
        className="mt-5 max-w-xl text-sm"
        style={{ color: "var(--text-secondary)" }}
      >
        Across {windowCount.toLocaleString("en-US")} graded calls, copying
        Polymarket&rsquo;s sharpest wallets returned {asSignedPct(ret)}. We grade
        every call against the result — crypto coin-flips excluded.
      </p>

      {categories.length > 0 && (
        <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          <span style={{ color: "var(--text-muted)" }}>Sharpest in: </span>
          {categories.map((c) => c.name).join(" · ")}
        </p>
      )}

      <div className="mt-5 max-w-md">
        <p className="mb-2 text-xs" style={{ color: "var(--text-muted)" }}>
          Get the daily smart-money brief:
        </p>
        <EmailCapture source="hero" />
      </div>
    </section>
  );
}
