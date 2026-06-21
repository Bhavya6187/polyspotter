// Edge guard against the scraper bot that inflates traffic from a single
// Singapore datacenter (0s sessions, ~100% bounce, machine-speed bursts across
// /wallet, /thesis, /market pages, and mangled "/<strong>market</strong>/0x..."
// links). This runs in the Next server process BEFORE page render/data-fetch,
// so blocked requests never pay the expensive SSR + egress cost.
//
// Two cheap, high-precision rules:
//   1. Malformed paths (contain < > or their encodings)  -> 403  (the scraper's
//      signature; no real route or browser ever requests these).
//   2. Per-IP burst rate limit                            -> 429  (humans never
//      fire 40 page requests in 15s; a crawler does).
//
// LIMITS: the rate-limit store is in-memory, so it's per-instance and resets on
// deploy. That's fine for one Railway replica; for distributed/edge-level
// blocking (offloading Railway entirely) use a Cloudflare WAF rule instead.
//
// Fail-open by design: any error here allows the request through, so the guard
// can never take the site down.
import { NextResponse } from "next/server";

// --- Tunables (env-overridable) ---------------------------------------------
const WINDOW_MS = Number(process.env.RL_WINDOW_MS) || 15_000; // sliding window
const MAX_REQUESTS = Number(process.env.RL_MAX) || 40; // matched reqs / window

// Legit crawlers we never want to throttle (protects SEO indexing). The
// malformed-path block still applies to everyone — real crawlers never hit it.
const GOOD_BOT = /(googlebot|bingbot|slurp|duckduckbot|baiduspider|yandexbot|applebot|petalbot)/i;

// --- In-memory sliding-window store -----------------------------------------
// ip -> array of request timestamps (ms) within the current window.
const hits = new Map();
let lastSweep = 0;

function rateLimited(ip, now) {
  const cutoff = now - WINDOW_MS;
  const arr = hits.get(ip);
  if (!arr) {
    hits.set(ip, [now]);
    return false;
  }
  // Drop timestamps older than the window, then record this hit.
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

export function middleware(request) {
  try {
    // 1. Malformed-path block — catches the "/<strong>...</strong>/" scraper.
    // Check both the decoded pathname and the raw URL (encoded < / >).
    const path = request.nextUrl.pathname;
    const rawLower = request.url.toLowerCase();
    if (
      path.includes("<") || path.includes(">") ||
      rawLower.includes("%3c") || rawLower.includes("%3e")
    ) {
      return new NextResponse("Bad Request", { status: 403 });
    }

    // 2. Per-IP burst rate limit. Only count full document loads — the scraper
    // does a fresh GET per page, whereas a human's in-app navigation and
    // viewport prefetch are RSC subrequests (they carry an `RSC` header). Skip
    // those, and skip verified-good crawlers, so we never throttle real users.
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
  return NextResponse.next();
}

// Run on page/content routes only; skip Next internals and static assets so the
// rate limit counts real navigations, not the dozen asset requests per page.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|txt|xml)$).*)",
  ],
};
