// Railway health-check target. Exempt from the origin-auth guard in proxy.js so
// Railway's internal probe (no Cloudflare header) stays green. Returns 200.
//
// ?diag=1 reports what the origin actually RECEIVES, to debug why
// Cloudflare-proxied requests lack X-Origin-Auth. Lists header names + a
// safelist of values (never cookies/authorization). Temporary; remove after.
const SAFE = new Set([
  "host", "cf-ray", "cf-connecting-ip", "cf-ipcountry", "cf-visitor",
  "cf-worker", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
  "x-railway-edge", "via", "user-agent",
]);

export function GET(request) {
  const url = new URL(request.url);
  if (url.searchParams.get("diag") === "1") {
    const h = request.headers.get("x-origin-auth");
    const secret = process.env.ORIGIN_AUTH_SECRET || "";
    const names = [];
    const values = {};
    for (const [k, v] of request.headers) {
      names.push(k);
      if (SAFE.has(k.toLowerCase())) values[k] = v;
    }
    const body = {
      origin_auth: {
        has_header: h != null,
        received_len: h ? h.length : 0,
        matches_exact: h === secret && secret !== "",
        expected_len: secret.length,
      },
      header_names: names.sort(),
      safe_values: values,
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
