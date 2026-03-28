import { ImageResponse } from "next/og";

export const runtime = "edge";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request, { params }) {
  const { alertId } = await params;

  let alert;
  try {
    const res = await fetch(`${API_URL}/api/alerts/${alertId}`);
    if (!res.ok) return new Response("Not found", { status: 404 });
    alert = await res.json();
  } catch {
    return new Response("Error fetching alert", { status: 500 });
  }

  const winPct = alert.win_rate != null ? `${Math.round(alert.win_rate * 100)}%` : null;
  const pnl = alert.total_pnl != null ? `$${Math.round(alert.total_pnl).toLocaleString()}` : null;
  const amount = `$${Math.round(alert.total_usd || 0).toLocaleString()}`;
  const copyAction = alert.llm_copy_action || {};
  const entryPct = copyAction.entry_price ? `${Math.round(copyAction.entry_price * 100)}¢` : "";
  const betLine = copyAction.outcome
    ? `${amount} on ${copyAction.outcome} at ${entryPct}`
    : amount;

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          padding: "48px",
          background: "linear-gradient(135deg, #060a12 0%, #0c1120 50%, #162030 100%)",
          color: "#e8ecf4",
          fontFamily: "monospace",
        }}
      >
        {/* Logo bar */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "32px" }}>
          <div style={{ width: "32px", height: "32px", background: "#00c26a", borderRadius: "8px" }} />
          <span style={{ fontSize: "16px", color: "#8b91a3" }}>PolySpotter · Follow the smart money</span>
        </div>

        {/* Market title */}
        <div style={{ fontSize: "32px", fontWeight: "bold", marginBottom: "12px", lineHeight: 1.2 }}>
          {alert.market_title || "Unknown Market"}
        </div>

        {/* Bet line */}
        <div style={{ fontSize: "40px", fontWeight: "bold", color: "#00c26a", marginBottom: "24px" }}>
          {betLine}
        </div>

        {/* Stats row */}
        <div style={{ display: "flex", gap: "32px", fontSize: "18px", color: "#8b91a3" }}>
          {winPct && <span>{winPct} win rate</span>}
          {pnl && <span>{pnl} P&L</span>}
        </div>

        {/* Win rate bar */}
        {alert.win_rate != null && (
          <div style={{ marginTop: "24px", display: "flex", flexDirection: "column", gap: "4px" }}>
            <div style={{ width: "100%", height: "8px", background: "#1a2535", borderRadius: "4px", overflow: "hidden" }}>
              <div style={{ width: `${Math.round(alert.win_rate * 100)}%`, height: "100%", background: "linear-gradient(90deg, #00c26a, #00e87b)", borderRadius: "4px" }} />
            </div>
          </div>
        )}

        {/* Footer */}
        <div style={{ marginTop: "auto", fontSize: "14px", color: "#5a6073" }}>
          polyspotter.com
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      headers: {
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    }
  );
}
