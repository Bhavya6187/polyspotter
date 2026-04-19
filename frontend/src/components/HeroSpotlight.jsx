"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { useSpotlight } from "../hooks/useSpotlight";
import { useCountdown } from "../hooks/useCountdown";
import { marketSlug } from "../lib/slugify";
import Sparkline from "./Sparkline";

function SpotlightSlide({ alert }) {
  const countdown = useCountdown(alert.end_date);
  const copyAction = alert.llm_copy_action || {};
  const entryPrice = copyAction.entry_price;

  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  const href = `/market/${marketSlug(alert.market_title, alert.condition_id)}`;

  return (
    <Link href={href} className="block flex flex-col gap-2 sm:gap-3 px-4 py-3 sm:px-5 sm:py-5 rounded-xl transition-shadow hover:shadow-md"
      style={{ background: "var(--surface-1)", border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="hidden sm:block text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
            Biggest move right now
          </p>
          <div className="flex items-center gap-2.5 mt-0 sm:mt-1">
            {alert.market_image && (
              <Image
                src={alert.market_image}
                alt=""
                width={32}
                height={32}
                className="h-8 w-8 rounded-lg object-cover shrink-0"
              />
            )}
            <h2 className="text-base sm:text-lg font-bold truncate" style={{ color: "var(--text-primary)" }}>
              {alert.market_title}
            </h2>
          </div>
          <p className="text-sm mt-1" style={{ color: "var(--accent)" }}>
            {usdFmt.format(alert.total_usd)} in smart money flow
            {alert.wallet_count > 1 ? ` \u00b7 ${alert.wallet_count} sharp wallets aligned` : ""}
          </p>
        </div>
        {alert.candles?.length > 0 && (
          <div className="hidden sm:block shrink-0">
            <Sparkline candles={alert.candles} entryPrice={entryPrice} width={140} height={48} />
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        {alert.best_win_rate != null && (
          <span>{"\ud83c\udfaf"} {Math.round(alert.best_win_rate * 100)}% win rate wallet</span>
        )}
        <span>{"\u23f1\ufe0f"} {alert.game_start_time ? "Starts" : "Resolves"} in {countdown.label}</span>
      </div>
    </Link>
  );
}

export default function HeroSpotlight() {
  const { data, loading } = useSpotlight();
  const [activeIndex, setActiveIndex] = useState(0);
  const paused = useRef(false);

  // Auto-rotate every 8s, pausing on hover
  useEffect(() => {
    if (data.length <= 1) return;
    const timer = setInterval(() => {
      if (!paused.current) {
        setActiveIndex((i) => (i + 1) % data.length);
      }
    }, 8000);
    return () => clearInterval(timer);
  }, [data.length]);

  const handleMouseEnter = useCallback(() => { paused.current = true; }, []);
  const handleMouseLeave = useCallback(() => { paused.current = false; }, []);

  const goPrev = useCallback(() => {
    setActiveIndex((i) => (i - 1 + data.length) % data.length);
  }, [data.length]);

  const goNext = useCallback(() => {
    setActiveIndex((i) => (i + 1) % data.length);
  }, [data.length]);

  if (loading || data.length === 0) return null;

  return (
    <div className="mb-4 relative group" onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
      {data.length > 1 && (
        <>
          <button
            onClick={goPrev}
            className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-3 z-10 hidden md:group-hover:flex items-center justify-center w-8 h-8 rounded-full transition-opacity"
            style={{ background: "var(--surface-1)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
            aria-label="Previous alert"
          >
            &#8249;
          </button>
          <button
            onClick={goNext}
            className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-3 z-10 hidden md:group-hover:flex items-center justify-center w-8 h-8 rounded-full transition-opacity"
            style={{ background: "var(--surface-1)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
            aria-label="Next alert"
          >
            &#8250;
          </button>
        </>
      )}

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
