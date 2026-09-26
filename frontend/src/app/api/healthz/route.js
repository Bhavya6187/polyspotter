import { API_URL } from "../../../lib/apiBase";

// Railway health-check target (healthcheckPath in railway.json). Plain 200.
//
// `?upstream=1` additionally probes the backend through the same base URL the
// server-side renders use, and reports which URL that is. This is the only
// way to confirm from outside that SSR can reach the API (e.g. after pointing
// API_URL_SERVER at the Railway private network) — Railway containers can't
// be shelled into casually, and a broken SSR fetch fails silently into empty
// pages while client-side fetches keep the site looking healthy.
export async function GET(request) {
  const headers = { "cache-control": "no-store" };
  const { searchParams } = new URL(request.url);
  if (searchParams.get("upstream") !== "1") {
    return new Response("ok", { status: 200, headers });
  }

  let apiBase;
  try {
    apiBase = new URL(API_URL);
  } catch {
    apiBase = null;
  }
  // Report host + port only; never echo secrets or full internal URLs.
  const upstreamHost = apiBase ? apiBase.host : "invalid";

  const started = Date.now();
  try {
    const res = await fetch(new URL("/api/health", API_URL), {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    return Response.json(
      { ok: res.ok, upstream: upstreamHost, status: res.status, ms: Date.now() - started },
      { status: res.ok ? 200 : 503, headers },
    );
  } catch (err) {
    return Response.json(
      { ok: false, upstream: upstreamHost, error: String(err?.message || err), ms: Date.now() - started },
      { status: 503, headers },
    );
  }
}
