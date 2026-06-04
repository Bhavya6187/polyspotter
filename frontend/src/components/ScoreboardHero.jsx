// Presentational proof hero. Renders the graded track record (Plan 1
// /api/scoreboard). Shows a "building" state until >= MIN_GRADED calls exist
// so a tiny early sample never reads as a confident claim.

const MIN_GRADED = 10;

function asPct(fraction) {
  if (!Number.isFinite(fraction)) return "—";
  return `${Math.round(fraction * 100)}%`;
}

function asSignedPct(fraction) {
  if (!Number.isFinite(fraction)) return "—";
  const v = Math.round(fraction * 100) || 0; // `|| 0` normalizes -0 to 0
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function Stat({ value, label, color }) {
  return (
    <div>
      <div
        className="text-4xl font-extrabold tracking-tight tabular-nums"
        style={{ color }}
      >
        {value}
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
    </div>
  );
}

export default function ScoreboardHero({ scoreboard }) {
  const window = scoreboard?.window;
  const allTime = scoreboard?.all_time;
  const gradedCount = allTime ? allTime.wins + allTime.losses : 0;

  const shell =
    "mb-6 rounded-2xl p-6 sm:p-8";
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
      </section>
    );
  }

  const returnColor =
    window.copy_return_pct >= 0 ? "var(--bullish)" : "var(--bearish)";

  return (
    <section aria-label="Track record" className={shell} style={shellStyle}>
      <div className="flex flex-wrap items-end gap-x-10 gap-y-5">
        <Stat
          value={`${window.wins}–${window.losses}`}
          label={`tracked calls · last ${scoreboard.window_days}d`}
          color="var(--bullish)"
        />
        <Stat
          value={asSignedPct(window.copy_return_pct)}
          label="if you copied $100 each"
          color={returnColor}
        />
        <Stat
          value={asPct(window.hit_rate)}
          label="hit rate"
          color="var(--text-primary)"
        />
      </div>
      <p
        className="mt-5 max-w-xl text-sm"
        style={{ color: "var(--text-secondary)" }}
      >
        We track Polymarket&rsquo;s sharpest wallets and grade every call —
        here&rsquo;s how copying them has actually worked out.
      </p>
    </section>
  );
}
