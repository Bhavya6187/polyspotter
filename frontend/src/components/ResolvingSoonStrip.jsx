"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import { fetchResolvingSoon } from "../lib/api";
import { useCountdown } from "../hooks/useCountdown";
import { marketSlug } from "../lib/slugify";

function ResolvingCard({ alert, ariaHidden, tabIndex }) {
  const countdown = useCountdown(alert.end_date);
  const urgent = countdown.total > 0 && countdown.total < 3600_000;
  const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const slug = marketSlug(alert.market_title, alert.condition_id);

  return (
    <Link href={`/market/${slug}`} className="shrink-0" aria-hidden={ariaHidden} tabIndex={tabIndex}>
      <div
        className={`rounded-lg px-3 py-2 sm:px-4 sm:py-3 transition-all ${urgent ? "animate-urgency" : ""}`}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          borderLeftWidth: 3,
          borderLeftColor: urgent ? "var(--bearish)" : "var(--warning)",
          minWidth: 160,
          maxWidth: 260,
        }}
      >
        <div className="flex items-center gap-2 mb-0.5">
          {alert.market_image && (
            <Image
              src={alert.market_image}
              alt=""
              width={20}
              height={20}
              className="h-5 w-5 rounded object-cover shrink-0"
            />
          )}
          <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
            {alert.market_title}
          </p>
        </div>
        <p
          className="text-sm sm:text-lg font-bold mt-0.5"
          style={{ color: urgent ? "var(--bearish)" : "var(--warning)", fontFamily: "var(--font-display)" }}
        >
          {countdown.label}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {usdFmt.format(alert.total_usd)} smart money
          {alert.dominant_side ? ` on ${alert.dominant_side}` : ""}
        </p>
      </div>
    </Link>
  );
}

export default function ResolvingSoonStrip() {
  const [alerts, setAlerts] = useState([]);
  const outerRef = useRef(null);
  const trackRef = useRef(null);
  const [marquee, setMarquee] = useState({ enabled: false, duration: 40 });

  useEffect(() => {
    fetchResolvingSoon().then(setAlerts).catch(() => {});
    const interval = setInterval(() => {
      fetchResolvingSoon().then(setAlerts).catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  // Drop markets whose end_date has already passed (event over, awaiting resolution)
  const live = alerts.filter((a) => a.end_date && new Date(a.end_date) > new Date());

  useEffect(() => {
    const outer = outerRef.current;
    const track = trackRef.current;
    if (!outer || !track) return;
    function check() {
      setMarquee((prev) => {
        const naturalWidth = track.scrollWidth / (prev.enabled ? 2 : 1);
        const containerWidth = outer.clientWidth;
        const shouldEnable = prev.enabled
          ? naturalWidth > containerWidth - 12
          : naturalWidth > containerWidth + 4;
        const pxPerSec = 16;
        const duration = Math.max(40, Math.round(naturalWidth / pxPerSec));
        if (shouldEnable === prev.enabled && duration === prev.duration) return prev;
        return { enabled: shouldEnable, duration };
      });
    }
    check();
    const ro = new ResizeObserver(check);
    ro.observe(outer);
    ro.observe(track);
    return () => ro.disconnect();
  }, [live.length, marquee.enabled]);

  if (live.length === 0) return null;

  const items = marquee.enabled ? [...live, ...live] : live;

  return (
    <div className="mb-4">
      <p className="text-[11px] uppercase tracking-wider mb-2 px-1"
        style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>
        Resolving Soon
      </p>
      <div
        ref={outerRef}
        className={marquee.enabled ? "overflow-hidden pb-2" : "overflow-x-auto pb-2"}
        style={marquee.enabled ? undefined : { scrollbarWidth: "thin" }}
      >
        <div
          ref={trackRef}
          className={`flex gap-3 ${marquee.enabled ? "auto-marquee w-max" : ""}`}
          style={marquee.enabled ? { "--marquee-duration": `${marquee.duration}s` } : undefined}
        >
          {items.map((a, i) => {
            const isCopy = marquee.enabled && i >= live.length;
            return (
              <ResolvingCard
                key={`${a.condition_id}-${i}`}
                alert={a}
                ariaHidden={isCopy || undefined}
                tabIndex={isCopy ? -1 : undefined}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
