import { NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Malformed-path block — cheap, stateless defense against the scraper's
// "/<strong>...</strong>/" links. No real route or browser ever requests these.
// (The header-based origin lock was removed: Railway sits behind its own
// Cloudflare, which strips headers our front-Cloudflare injects — "orange to
// orange" — so the app can't distinguish CF traffic from direct-to-origin.
// Bot mitigation lives at Cloudflare / GA instead.)
function malformed(request) {
  const path = request.nextUrl.pathname;
  const rawLower = request.url.toLowerCase();
  return (
    path.includes("<") || path.includes(">") ||
    rawLower.includes("%3c") || rawLower.includes("%3e")
  );
}

/**
 * Edge proxy: drop malformed-path scrapes, then redirect old
 * /market/0x<full-conditionId> URLs to the new short slug format. Only the
 * redirect triggers for bare condition IDs (0x + 64 hex chars, no title prefix).
 */
export async function proxy(request) {
  try {
    if (malformed(request)) {
      return new NextResponse("Bad Request", { status: 403 });
    }
  } catch {
    // never let the guard break the site
  }

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
  matcher: [
    "/((?!_next/static|_next/image|favicon|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml)$).*)",
  ],
};
