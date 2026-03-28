"use client";

import { useState, useEffect } from "react";
import { useSpotlight } from "../hooks/useSpotlight";
import { useCountdown } from "../hooks/useCountdown";
import Sparkline from "./Sparkline";

function SpotlightSlide({ alert }) {
  const countdown = useCountdown(alert.end_date);
  const copyAction = alert.llm_copy_action || {};
  const entryPrice = copyAction.entry_price;

  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div className="flex flex-col gap-3 px-5 py-5 rounded-xl"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Biggest move right now
          </p>
          <h2 className="text-lg font-bold mt-1 truncate" style={{ color: "var(--text-primary)" }}>
            {alert.market_title}
          </h2>
          <p className="text-sm mt-1" style={{ color: "var(--accent)" }}>
            {usdFmt.format(alert.total_usd)} in smart money flow
            {alert.wallet_count > 1 ? ` \u00b7 ${alert.wallet_count} sharp wallets aligned` : ""}
          </p>
        </div>
        {alert.candles?.length > 0 && (
          <div className="shrink-0">
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
    </div>
  );
}

export default function HeroSpotlight() {
  const { data, loading } = useSpotlight();
  const [activeIndex, setActiveIndex] = useState(0);

  // Auto-rotate every 8s
  useEffect(() => {
    if (data.length <= 1) return;
    const timer = setInterval(() => {
      setActiveIndex((i) => (i + 1) % data.length);
    }, 8000);
    return () => clearInterval(timer);
  }, [data.length]);

  if (loading || data.length === 0) return null;

  return (
    <div className="mb-4">
      <SpotlightSlide alert={data[activeIndex]} />

      {data.length > 1 && (
        <div className="flex justify-center gap-1.5 mt-2">
          {data.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className="rounded-full transition-all"
              style={{
                width: i === activeIndex ? 16 : 6,
                height: 6,
                background: i === activeIndex ? "var(--accent)" : "var(--border)",
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
