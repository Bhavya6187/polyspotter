"use client";

import { useId } from "react";

export default function Sparkline({ candles, entryPrice, width = 200, height = 50 }) {
  const gradientId = useId();
  if (!candles || candles.length < 2) return null;

  const prices = candles.map((c) => c.p);
  const times = candles.map((c) => c.t);
  const minP = Math.min(...prices) * 0.98;
  const maxP = Math.max(...prices) * 1.02;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeP = maxP - minP || 1;
  const rangeT = maxT - minT || 1;

  const points = candles.map((c) => {
    const x = ((c.t - minT) / rangeT) * width;
    const y = height - ((c.p - minP) / rangeP) * height;
    return `${x},${y}`;
  }).join(" ");

  // Entry price marker
  let entryY = null;
  if (entryPrice != null) {
    entryY = height - ((entryPrice - minP) / rangeP) * height;
  }

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      {/* Gradient fill */}
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.15" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Fill area */}
      <polygon
        points={`0,${height} ${points} ${width},${height}`}
        fill={`url(#${gradientId})`}
      />

      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Entry price dot */}
      {entryY != null && (
        <circle
          cx={width * 0.85}
          cy={entryY}
          r="3"
          fill="var(--accent)"
          style={{ filter: "drop-shadow(0 0 4px var(--accent))" }}
        />
      )}
    </svg>
  );
}
