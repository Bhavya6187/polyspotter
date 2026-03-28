"use client";

import { useState, useId } from "react";

const RANGES = ["24h", "7d", "30d", "all"];

export default function PriceChart({ history, outcome, alerts, conditionId }) {
  const gradientId = useId();
  const [activeRange, setActiveRange] = useState("7d");
  const [points, setPoints] = useState(history || []);
  const [loading, setLoading] = useState(false);

  if (!points || points.length < 2) return null;

  const prices = points.map((pt) => pt.p);
  const times = points.map((pt) => pt.t);
  const minP = Math.min(...prices) * 0.98;
  const maxP = Math.max(...prices) * 1.02;
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeP = maxP - minP || 0.01;
  const rangeT = maxT - minT || 1;

  const W = 600;
  const H = 140;

  const svgPoints = points
    .map((pt) => {
      const x = ((pt.t - minT) / rangeT) * W;
      const y = H - ((pt.p - minP) / rangeP) * H;
      return `${x},${y}`;
    })
    .join(" ");

  // Map alerts to chart coordinates
  const alertMarkers = (alerts || [])
    .filter((a) => a.scanned_at)
    .map((a) => {
      const ts = new Date(a.scanned_at).getTime() / 1000;
      if (ts < minT || ts > maxT) return null;
      const x = ((ts - minT) / rangeT) * W;
      let closest = points[0];
      let minDist = Infinity;
      for (const pt of points) {
        const dist = Math.abs(pt.t - ts);
        if (dist < minDist) {
          minDist = dist;
          closest = pt;
        }
      }
      const y = H - ((closest.p - minP) / rangeP) * H;
      const isTopScore =
        a.composite_score ===
        Math.max(...alerts.map((al) => al.composite_score || 0));
      return { x, y, isTopScore, id: a.id };
    })
    .filter(Boolean);

  const yTicks = [maxP, (maxP + minP) / 2, minP].map((p) => ({
    label: `${Math.round(p * 100)}¢`,
    y: H - ((p - minP) / rangeP) * H,
  }));

  async function handleRangeChange(range) {
    if (range === activeRange) return;
    setActiveRange(range);
    setLoading(true);
    try {
      const { fetchPriceHistory } = await import("../lib/api");
      const data = await fetchPriceHistory(conditionId, range);
      setPoints(data.history || []);
    } catch {
      // keep existing points on error
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <div className="mb-3 flex items-center justify-between">
        <span
          className="text-xs font-semibold uppercase tracking-widest"
          style={{
            fontFamily: "var(--font-display)",
            color: "var(--text-muted)",
            fontSize: "0.6rem",
          }}
        >
          Price History — &ldquo;{outcome}&rdquo;
        </span>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => handleRangeChange(r)}
              className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
              style={{
                background:
                  r === activeRange ? "var(--surface-2)" : "transparent",
                color:
                  r === activeRange
                    ? "var(--text-primary)"
                    : "var(--text-muted)",
                fontWeight: r === activeRange ? 600 : 400,
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="relative" style={{ height: 160, opacity: loading ? 0.5 : 1, transition: "opacity 0.2s" }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-full w-full"
          preserveAspectRatio="none"
        >
          {yTicks.map((tick, i) => (
            <line
              key={i}
              x1="0"
              y1={tick.y}
              x2={W}
              y2={tick.y}
              stroke="var(--border)"
              strokeWidth="0.5"
              strokeDasharray="4,4"
            />
          ))}
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.15" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon
            points={`0,${H} ${svgPoints} ${W},${H}`}
            fill={`url(#${gradientId})`}
          />
          <polyline
            points={svgPoints}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {alertMarkers.map((m) => (
            <circle
              key={m.id}
              cx={m.x}
              cy={m.y}
              r="5"
              fill={m.isTopScore ? "var(--warning)" : "var(--info)"}
              stroke="var(--surface-1)"
              strokeWidth="2"
            />
          ))}
        </svg>
        {yTicks.map((tick, i) => (
          <div
            key={i}
            className="absolute right-1"
            style={{
              top: `${(tick.y / H) * 100}%`,
              transform: "translateY(-50%)",
              fontSize: 10,
              fontFamily: "var(--font-display)",
              color: "var(--text-muted)",
            }}
          >
            {tick.label}
          </div>
        ))}
        <div
          className="absolute bottom-0 left-0 flex gap-3.5"
          style={{ fontSize: 10, color: "var(--text-muted)" }}
        >
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: "var(--info)" }}
            />
            Alert entries
          </span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: "var(--warning)" }}
            />
            High-conviction
          </span>
        </div>
      </div>
    </div>
  );
}
