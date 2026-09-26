// Server-side API base URL, resolved once per process.
//
// At runtime on Railway, API_URL_SERVER points at the backend's PRIVATE
// network address (http://polybot.railway.internal:8080): no public hop, no
// egress billing, no Cloudflare bot challenge in the way of our own SSR.
//
// During `next build`, the private network is not reachable (Railway only
// wires it up at runtime), so build-time prerendering falls back to the
// public URL in API_URL_BUILD. Without this fallback every prerendered page
// would ship empty until its first ISR revalidation after deploy.
const isBuildPhase = process.env.NEXT_PHASE === "phase-production-build";

const runtimeUrl = process.env.API_URL_SERVER;
const buildUrl = process.env.API_URL_BUILD;
const publicUrl = process.env.NEXT_PUBLIC_API_URL;

const resolved =
  (isBuildPhase && (buildUrl || publicUrl)) ||
  runtimeUrl ||
  publicUrl ||
  "http://localhost:8000";

// Consumers build URLs with `${API_URL}/api/...`; a trailing slash would turn
// that into `//api/...`, which FastAPI 404s. That exact misconfiguration
// blanked the site once (2026-07), so normalise here rather than trust .env.
export const API_URL = resolved.replace(/\/+$/, "");

// Public (browser-reachable) API origin, for anything rendered INTO markup:
// <img src>, og:image, JSON-LD. Never use API_URL for those — at runtime it
// is the private Railway address (http://polybot.railway.internal:8080),
// which crawlers and browsers cannot reach. API_URL stays for server fetches.
export function publicApiBase() {
  return (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.API_URL_BUILD ||
    "https://api.polyspotter.com"
  ).replace(/\/+$/, "");
}
