import Link from "next/link";
import { walletPseudonym } from "../lib/pseudonym";

export default function MarketTheses({ theses }) {
  if (!theses || theses.length === 0) return null;

  return (
    <section>
      <h3
        className="mb-3 text-xs font-semibold uppercase tracking-widest"
        style={{
          fontFamily: "var(--font-display)",
          color: "var(--text-muted)",
          fontSize: "0.6rem",
        }}
      >
        Related Theses
      </h3>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {theses.map((thesis) => (
          <Link
            key={thesis.id}
            href={`/thesis/${thesis.id}`}
            className="block rounded-xl border p-3.5 transition-colors hover:border-[var(--text-muted)]"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface-1)",
            }}
          >
            <div
              className="mb-1.5 text-sm font-semibold"
              style={{ color: "var(--text-primary)" }}
            >
              {thesis.thesis_headline}
            </div>
            <div
              className="mb-2 text-xs leading-relaxed"
              style={{ color: "var(--text-muted)" }}
            >
              {walletPseudonym(thesis.wallet)} trades{" "}
              {(thesis.markets || []).length} related market
              {(thesis.markets || []).length !== 1 ? "s" : ""}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(thesis.markets || []).slice(0, 3).map((m, i) => (
                <span
                  key={i}
                  className="rounded px-2 py-0.5 text-[10px]"
                  style={{
                    background: "var(--surface-2)",
                    color: "var(--text-muted)",
                  }}
                >
                  {m.market_title
                    ? m.market_title.length > 30
                      ? m.market_title.slice(0, 30) + "…"
                      : m.market_title
                    : m.outcome || "Market"}
                </span>
              ))}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
