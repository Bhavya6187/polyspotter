"use client";

import { useId } from "react";

export default function Sparkline({
  candles,
  data,
  entryPrice,
  width = 200,
  height = 50,
  color = "var(--accent)",
}) {
  const gradientId = useId();

  const normalised = (() => {
    if (Array.isArray(candles) && candles.length) {
      return candles.map((c) => ({ t: c.t, p: c.p }));
    }
    if (Array.isArray(data) && data.length) {
      return data.map((p, i) => ({ t: i, p }));
    }
    return [];
  })();
  if (normalised.length < 2) return null;

  const prices = normalised.map((c) => c.p);
  const times = normalised.map((c) => c.t);
  const minP = Math.min(...prices) * 0.98;
  const maxP = Math.max(...prices) * 1.02;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeP = maxP - minP || 1;
  const rangeT = maxT - minT || 1;

  const points = normalised.map((c) => {
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
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
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
        stroke={color}
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
          fill={color}
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
      )}
    </svg>
  );
}
