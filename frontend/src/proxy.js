import { NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Redirect old /market/0x<full-conditionId> URLs to the new short slug format.
 * Only triggers for bare condition IDs (0x + 64 hex chars with no title prefix).
 */
export async function proxy(request) {
  const { pathname } = request.nextUrl;
  const match = pathname.match(/^\/market\/(0x[a-fA-F0-9]{64})$/);
  if (!match) return NextResponse.next();

  const conditionId = match[1];

  try {
    const res = await fetch(`${API_URL}/api/market/${conditionId}/live`, {
      next: { revalidate: 3600 },
    });
    if (res.ok) {
      const data = await res.json();
      const title = data.title;
      if (title) {
        const slug = title
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "")
          .slice(0, 80);
        const shortId = conditionId.slice(0, 7);
        const url = request.nextUrl.clone();
        url.pathname = `/market/${slug}-${shortId}`;
        return NextResponse.redirect(url, 301);
      }
    }
  } catch {
    // Fall through to render normally if API is unavailable
  }

  return NextResponse.next();
}

export const config = {
  matcher: "/market/:id*",
};
