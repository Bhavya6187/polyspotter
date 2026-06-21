import { NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- Bot guard --------------------------------------------------------------
// Sheds the scraper that inflated traffic from a single Singapore datacenter
// (0s sessions, ~100% bounce, machine-speed crawl of /wallet, /thesis, /market,
// and mangled "/<strong>market</strong>/0x..." links). Runs before render, so
// blocked requests never pay the SSR + egress cost. Fail-open: any error here
// lets the request through, so the guard can never take the site down.
//
// In-memory rate-limit store is per-instance and resets on deploy — fine for a
// single Railway replica; use a Cloudflare WAF rule for true edge / IP-rotation
// resistance.
const WINDOW_MS = Number(process.env.RL_WINDOW_MS) || 15_000; // sliding window
const MAX_REQUESTS = Number(process.env.RL_MAX) || 40; // matched reqs / window
// Legit crawlers we never throttle (protects SEO). The malformed-path block
// still applies to everyone — real crawlers never hit it.
const GOOD_BOT = /(googlebot|bingbot|slurp|duckduckbot|baiduspider|yandexbot|applebot|petalbot)/i;

// ip -> ascending request timestamps (ms) within the current window.
const hits = new Map();
let lastSweep = 0;

function rateLimited(ip, now) {
  const cutoff = now - WINDOW_MS;
  const arr = hits.get(ip);
  if (!arr) {
    hits.set(ip, [now]);
    return false;
  }
  let i = 0;
  while (i < arr.length && arr[i] <= cutoff) i++;
  if (i) arr.splice(0, i);
  arr.push(now);
  return arr.length > MAX_REQUESTS;
}

// Periodically evict idle IPs so the Map can't grow unbounded.
function sweep(now) {
  if (now - lastSweep < WINDOW_MS) return;
  lastSweep = now;
  const cutoff = now - WINDOW_MS;
  for (const [ip, arr] of hits) {
    if (!arr.length || arr[arr.length - 1] <= cutoff) hits.delete(ip);
  }
}

function clientIp(request) {
  const xff = request.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0].trim();
  return request.headers.get("x-real-ip") || "unknown";
}

function botGuard(request) {
  try {
    // Malformed-path block — catches the "/<strong>...</strong>/" scraper.
    const path = request.nextUrl.pathname;
    const rawLower = request.url.toLowerCase();
    if (
      path.includes("<") || path.includes(">") ||
      rawLower.includes("%3c") || rawLower.includes("%3e")
    ) {
      return new NextResponse("Bad Request", { status: 403 });
    }

    // Per-IP burst limit. Only count full document loads — the scraper does a
    // fresh GET per page, whereas a human's in-app navigation and viewport
    // prefetch are RSC subrequests (they carry an `RSC` header). Skip those and
    // verified-good crawlers so we never throttle real users.
    const ua = request.headers.get("user-agent") || "";
    const isDocumentLoad = !request.headers.get("rsc");
    if (isDocumentLoad && !GOOD_BOT.test(ua)) {
      const now = Date.now();
      sweep(now);
      if (rateLimited(clientIp(request), now)) {
        return new NextResponse("Too Many Requests", {
          status: 429,
          headers: { "Retry-After": String(Math.ceil(WINDOW_MS / 1000)) },
        });
      }
    }
  } catch {
    // Never let the guard break the site — fall through and allow.
  }
  return null;
}

/**
 * Edge proxy: first the bot guard (above), then redirect old
 * /market/0x<full-conditionId> URLs to the new short slug format. Only the
 * redirect triggers for bare condition IDs (0x + 64 hex chars, no title prefix).
 */
export async function proxy(request) {
  const blocked = botGuard(request);
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

// Broadened from "/market/:id*" so the bot guard runs on all content routes;
// the /market redirect above still self-guards by regex, so non-market paths
// just fall through. Skips Next internals and static assets so the rate limit
// counts real navigations, not the dozen asset requests per page.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml)$).*)",
  ],
};
