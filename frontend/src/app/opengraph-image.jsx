import { ImageResponse } from "next/og";

export const alt = "PolySpotter — Large bets. Sharp wallets. Early signals.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          background: "linear-gradient(145deg, #030712 0%, #0f172a 50%, #030712 100%)",
          padding: "60px 80px",
          fontFamily: "system-ui, sans-serif",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Subtle grid pattern */}
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
            background: "radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%)",
          }}
        />

        {/* Top: title area */}
        <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
          <div
            style={{
              fontSize: 56,
              fontWeight: 800,
              color: "#f9fafb",
              letterSpacing: "-0.02em",
              lineHeight: 1.1,
            }}
          >
            PolySpotter
          </div>
          <div
            style={{
              fontSize: 26,
              color: "#9ca3af",
              marginTop: 16,
              lineHeight: 1.4,
            }}
          >
            Large bets. Sharp wallets. Early signals.
          </div>
        </div>

        {/* Bottom: signal pills */}
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {[
            { label: "Whale Trades", color: "#3b82f6" },
            { label: "Coordinated Flow", color: "#8b5cf6" },
            { label: "Price Impact", color: "#10b981" },
          ].map(({ label, color }) => (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 999,
                padding: "12px 24px",
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: color,
                  boxShadow: `0 0 12px ${color}`,
                }}
              />
              <span style={{ fontSize: 20, color: "#e5e7eb", fontWeight: 500 }}>
                {label}
              </span>
            </div>
          ))}
        </div>

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
