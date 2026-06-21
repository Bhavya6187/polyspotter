// Railway health-check target. Kept separate from "/" and exempted from the
// origin-auth guard in proxy.js, so Railway's internal probe — which does NOT
// arrive through Cloudflare and therefore lacks the X-Origin-Auth header — stays
// green even with the origin lock enabled. Returns 200 with no body work.
//
// ?diag=1 reports what X-Origin-Auth the origin actually RECEIVES (lengths +
// match booleans only — never the secret value), to debug Cloudflare header
// injection. Temporary; remove once the origin lock is confirmed working.
export function GET(request) {
  const url = new URL(request.url);
  if (url.searchParams.get("diag") === "1") {
    const h = request.headers.get("x-origin-auth");
    const secret = process.env.ORIGIN_AUTH_SECRET || "";
    const body = {
      has_header: h != null,
      received_len: h ? h.length : 0,
      received_trimmed_len: h ? h.trim().length : 0,
      matches_exact: h === secret && secret !== "",
      matches_trimmed: h != null && secret !== "" && h.trim() === secret,
      expected_len: secret.length,
      cf_ray: request.headers.get("cf-ray") || null,
    };
    return new Response(JSON.stringify(body, null, 2), {
      status: 200,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }
  return new Response("ok", {
    status: 200,
    headers: { "cache-control": "no-store" },
  });
}
