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

export const API_URL =
  (isBuildPhase && (buildUrl || publicUrl)) ||
  runtimeUrl ||
  publicUrl ||
  "http://localhost:8000";
