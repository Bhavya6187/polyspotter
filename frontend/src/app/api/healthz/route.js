import { API_URL } from "../../../lib/apiBase";

// Railway health-check target (healthcheckPath in railway.json). Plain 200.
//
// `?upstream=1` additionally probes the backend through the same base URL the
// server-side renders use. It answers one question only: can SSR reach the
// API at all? `reachable` is true for ANY HTTP response — the backend's own
// /api/health deliberately returns 503 when the scanner hasn't ingested for an
// hour, and that is reported separately as `upstreamStatus` so scanner
// staleness is never mistaken for a broken network path. This is the only
// way to confirm from outside that SSR works (e.g. after pointing
// API_URL_SERVER at the Railway private network): a broken SSR fetch fails
// silently into empty pages while client-side fetches keep the site looking
// healthy.
export async function GET(request) {
  const headers = { "cache-control": "no-store" };
  const { searchParams } = new URL(request.url);
  if (searchParams.get("upstream") !== "1") {
    return new Response("ok", { status: 200, headers });
  }

  // Say which KIND of path SSR is using without echoing internal hostnames.
  let route = "invalid";
  try {
    const { hostname } = new URL(API_URL);
    route = hostname.endsWith(".railway.internal") ? "private-network" : "public";
  } catch {}

  const started = Date.now();
  try {
    const res = await fetch(new URL("/api/health", API_URL), {
      method: "HEAD",
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return Response.json(
      { reachable: true, route, upstreamStatus: res.status, ms: Date.now() - started },
      { status: 200, headers },
    );
  } catch (err) {
    return Response.json(
      { reachable: false, route, error: String(err?.message || err), ms: Date.now() - started },
      { status: 503, headers },
    );
  }
}
