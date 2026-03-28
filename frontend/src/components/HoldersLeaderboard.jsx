import Link from "next/link";
import { walletPseudonym } from "../lib/pseudonym";

const fmtUsd = (v) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${Math.round(v)}`;
};

function wrColor(wr) {
  if (wr == null) return "var(--text-muted)";
  if (wr >= 0.8) return "var(--accent)";
  if (wr >= 0.65) return "var(--warning)";
  return "var(--text-muted)";
}

export default function HoldersLeaderboard({ holders }) {
  if (!holders || holders.length === 0) return null;

  return (
    <div>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Top Holders
      </h3>
      <div
        className="overflow-hidden rounded-xl border"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        {holders.map((h, i) => (
          <div
            key={h.wallet}
            className="flex items-center gap-2.5 px-3.5 py-3"
            style={{
              borderBottom:
                i < holders.length - 1
                  ? "1px solid var(--border)"
                  : "none",
            }}
          >
            <span
              className="w-5 text-xs font-bold"
              style={{ color: "var(--text-muted)" }}
            >
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <Link
                  href={`/wallet/${h.wallet}`}
                  className="truncate text-sm font-semibold hover:underline"
                  style={{
                    fontFamily: "var(--font-display)",
                    color: "var(--text-primary)",
                    fontSize: "0.8rem",
                  }}
                >
                  {walletPseudonym(h.wallet)}
                </Link>
                <span
                  className="ml-2 text-xs font-semibold"
                  style={{
                    color:
                      h.position_size >= 10000
                        ? "var(--accent)"
                        : h.position_size >= 3000
                          ? "var(--warning)"
                          : "var(--text-primary)",
                  }}
                >
                  {fmtUsd(h.position_size)}
                </span>
              </div>
              <div className="mt-1 flex gap-2">
                {h.win_rate != null && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{
                      background: `color-mix(in srgb, ${wrColor(h.win_rate)} 12%, transparent)`,
                      color: wrColor(h.win_rate),
                    }}
                  >
                    {Math.round(h.win_rate * 100)}% WR
                  </span>
                )}
                {h.total_pnl != null && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{
                      background: "rgba(59,130,246,0.1)",
                      color: "var(--info)",
                    }}
                  >
                    {h.total_pnl >= 0 ? "+" : ""}
                    {fmtUsd(Math.abs(h.total_pnl))} PnL
                  </span>
                )}
                <span
                  className="text-[10px]"
                  style={{ color: "var(--text-muted)" }}
                >
                  {h.outcome}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
