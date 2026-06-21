import { NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- Origin lock ------------------------------------------------------------
// The Singapore scraper bypasses Cloudflare by hitting the Railway origin IP
// directly (Cloudflare saw 11 SG requests in 24h while GA saw ~1,671), so no
// WAF rule can touch it. Railway can't IP-firewall the origin to Cloudflare on
// our plan, so we lock it at the app layer instead:
//
//   Cloudflare injects `X-Origin-Auth: <secret>` on every request it proxies
//   (a Transform Rule). Anything reaching us WITHOUT that header skipped
//   Cloudflare entirely -> 403.
//
// Safe rollout (order matters — wrong order 403s the whole site):
//   1. Deploy this code with ORIGIN_AUTH_SECRET unset -> guard is a no-op.
//   2. Add the Cloudflare Transform Rule that injects the header.
//   3. THEN set ORIGIN_AUTH_SECRET on the frontend service -> lock engages.
//
// HEALTH_PATH is exempt because Railway's internal health probe does not pass
// through Cloudflare and so never carries the header.
const ORIGIN_SECRET = process.env.ORIGIN_AUTH_SECRET || "";
const HEALTH_PATH = "/api/healthz";

function guard(request) {
  try {
    const path = request.nextUrl.pathname;

    // Malformed-path block (defense in depth) — catches the scraper's
    // "/<strong>...</strong>/" links. No real route or browser hits these.
    const rawLower = request.url.toLowerCase();
    if (
      path.includes("<") || path.includes(">") ||
      rawLower.includes("%3c") || rawLower.includes("%3e")
    ) {
      return new NextResponse("Bad Request", { status: 403 });
    }

    // Origin lock — only when configured, and never on the health path.
    if (ORIGIN_SECRET && path !== HEALTH_PATH) {
      if (request.headers.get("x-origin-auth") !== ORIGIN_SECRET) {
        return new NextResponse("Forbidden", { status: 403 });
      }
    }
  } catch {
    // Never let the guard break the site — fall through and allow.
    return null;
  }
  return null;
}

/**
 * Edge proxy: first the origin-lock / bot guard above, then redirect old
 * /market/0x<full-conditionId> URLs to the new short slug format. Only the
 * redirect triggers for bare condition IDs (0x + 64 hex chars, no title prefix).
 */
export async function proxy(request) {
  const blocked = guard(request);
  if (blocked) return blocked;

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

// All content routes (so the origin lock covers everything), minus Next
// internals and static assets. The /market redirect self-guards by regex, so
// non-market paths just fall through.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml)$).*)",
  ],
};
