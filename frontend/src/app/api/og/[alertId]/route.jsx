import { ImageResponse } from "next/og";

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

  const winPct =
    alert.win_rate != null ? `${Math.round(alert.win_rate * 100)}%` : null;
  const pnl =
    alert.total_pnl != null
      ? `$${Math.round(alert.total_pnl).toLocaleString()}`
      : null;
  const amount = `$${Math.round(alert.total_usd || 0).toLocaleString()}`;
  const copyAction = alert.llm_copy_action || {};
  const entryPct = copyAction.entry_price
    ? `${Math.round(copyAction.entry_price * 100)}¢`
    : "";
  const betLine = copyAction.outcome
    ? `${amount} on ${copyAction.outcome} at ${entryPct}`
    : amount;

  const statParts = [];
  if (winPct) statParts.push(`${winPct} win rate`);
  if (pnl) statParts.push(`${pnl} P&L`);
  const statsText = statParts.join("  ·  ");

  const winBarWidth = alert.win_rate != null ? Math.round(alert.win_rate * 100) : 0;

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          padding: "48px",
          background:
            "linear-gradient(135deg, #060a12 0%, #0c1120 50%, #162030 100%)",
          color: "#e8ecf4",
          fontFamily: "monospace",
        }}
      >
        {/* Logo bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            marginBottom: "32px",
          }}
        >
          <div
            style={{
              display: "flex",
              width: "32px",
              height: "32px",
              background: "#00c26a",
              borderRadius: "8px",
            }}
          />
          <div
            style={{
              display: "flex",
              fontSize: "16px",
              color: "#8b91a3",
            }}
          >
            PolySpotter · Follow the smart money
          </div>
        </div>

        {/* Market title */}
        <div
          style={{
            display: "flex",
            fontSize: "32px",
            fontWeight: "bold",
            marginBottom: "12px",
            lineHeight: 1.2,
          }}
        >
          {alert.market_title || "Unknown Market"}
        </div>

        {/* Bet line */}
        <div
          style={{
            display: "flex",
            fontSize: "40px",
            fontWeight: "bold",
            color: "#00c26a",
            marginBottom: "24px",
          }}
        >
          {betLine}
        </div>

        {/* Stats row */}
        {statsText ? (
          <div
            style={{
              display: "flex",
              fontSize: "18px",
              color: "#8b91a3",
            }}
          >
            {statsText}
          </div>
        ) : (
          <div style={{ display: "flex" }} />
        )}

        {/* Win rate bar */}
        {winBarWidth > 0 ? (
          <div
            style={{
              display: "flex",
              marginTop: "24px",
              width: "100%",
              height: "8px",
              background: "#1a2535",
              borderRadius: "4px",
            }}
          >
            <div
              style={{
                display: "flex",
                width: `${winBarWidth}%`,
                height: "100%",
                background:
                  "linear-gradient(90deg, #00c26a, #00e87b)",
                borderRadius: "4px",
              }}
            />
          </div>
        ) : (
          <div style={{ display: "flex" }} />
        )}

        {/* Footer */}
        <div
          style={{
            display: "flex",
            marginTop: "auto",
            fontSize: "14px",
            color: "#5a6073",
          }}
        >
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
