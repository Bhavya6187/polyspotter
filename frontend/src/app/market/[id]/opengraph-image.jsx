import { ImageResponse } from "next/og";
import { partialIdFromSlug } from "../../../lib/slugify";

export const runtime = "edge";
export const alt = "PolySpotter Market";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function resolveConditionId(partialId) {
  if (/^0x[a-fA-F0-9]{64}$/.test(partialId)) return partialId;
  try {
    const res = await fetch(`${API_URL}/api/market/resolve/${partialId}`, {
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      return data.condition_id;
    }
  } catch {}
  return partialId;
}

async function getMarketData(conditionId) {
  try {
    const [liveRes, alertsRes] = await Promise.all([
      fetch(`${API_URL}/api/market/${conditionId}/live`, {
        signal: AbortSignal.timeout(5000),
      }),
      fetch(
        `${API_URL}/api/alerts?condition_id=${conditionId}&per_page=50`,
        { signal: AbortSignal.timeout(5000) }
      ),
    ]);
    const live = liveRes.ok ? await liveRes.json() : null;
    const alertsData = alertsRes.ok ? await alertsRes.json() : null;
    return { live, alerts: alertsData?.alerts || [] };
  } catch {
    return { live: null, alerts: [] };
  }
}

export default async function OGImage({ params }) {
  const { id } = await params;
  const partialId = partialIdFromSlug(id);
  const conditionId = await resolveConditionId(partialId);
  const { live, alerts } = await getMarketData(conditionId);

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const alertCount = alerts.length;
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const usdStr = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(totalUsd);

  // Collect unique signal types from alerts
  const signals = [...new Set(alerts.map((a) => a.signal_type).filter(Boolean))].slice(0, 3);

  const signalColors = {
    whale_trade: "#3b82f6",
    new_wallet_large_bet: "#f59e0b",
    timing_relative_resolution: "#ef4444",
    low_activity_large_bet: "#8b5cf6",
    pre_event_volume_spike: "#ec4899",
    wallet_clustering: "#6366f1",
    concentrated_one_sided: "#14b8a6",
    price_impact: "#10b981",
    correlated_cross_market: "#f97316",
  };

  const signalLabels = {
    whale_trade: "Whale Trade",
    new_wallet_large_bet: "New Wallet",
    timing_relative_resolution: "Near Resolution",
    low_activity_large_bet: "Low Activity",
    pre_event_volume_spike: "Volume Spike",
    wallet_clustering: "Wallet Cluster",
    concentrated_one_sided: "One-Sided Flow",
    price_impact: "Price Impact",
    correlated_cross_market: "Cross-Market",
  };

  // Truncate title for display
  const displayTitle = title.length > 80 ? title.slice(0, 77) + "..." : title;

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          background:
            "linear-gradient(145deg, #030712 0%, #0f172a 50%, #030712 100%)",
          padding: "60px 80px",
          fontFamily: "system-ui, sans-serif",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Grid pattern */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        {/* Accent glow */}
        <div
          style={{
            position: "absolute",
            top: -100,
            right: -100,
            width: 400,
            height: 400,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)",
          }}
        />

        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 32,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 700, color: "#60a5fa" }}>
            PolySpotter
          </div>
        </div>

        {/* Market title */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flex: 1,
          }}
        >
          <div
            style={{
              fontSize: 48,
              fontWeight: 800,
              color: "#f9fafb",
              letterSpacing: "-0.02em",
              lineHeight: 1.15,
            }}
          >
            {displayTitle}
          </div>

          {/* Stats row */}
          <div
            style={{
              display: "flex",
              gap: 40,
              marginTop: 32,
            }}
          >
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 18, color: "#6b7280", fontWeight: 500 }}>
                Notable Trades
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#f9fafb" }}>
                {alertCount}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 18, color: "#6b7280", fontWeight: 500 }}>
                Smart Money Flow
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: "#10b981" }}>
                {usdStr}
              </div>
            </div>
          </div>
        </div>

        {/* Signal pills */}
        {signals.length > 0 && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {signals.map((signal) => (
              <div
                key={signal}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 999,
                  padding: "10px 20px",
                }}
              >
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: signalColors[signal] || "#6b7280",
                    boxShadow: `0 0 10px ${signalColors[signal] || "#6b7280"}`,
                  }}
                />
                <span
                  style={{ fontSize: 16, color: "#e5e7eb", fontWeight: 500 }}
                >
                  {signalLabels[signal] || signal}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Domain watermark */}
        <div
          style={{
            position: "absolute",
            bottom: 30,
            right: 40,
            fontSize: 16,
            color: "#4b5563",
            fontWeight: 500,
          }}
        >
          polyspotter.com
        </div>
      </div>
    ),
    { ...size }
  );
}
