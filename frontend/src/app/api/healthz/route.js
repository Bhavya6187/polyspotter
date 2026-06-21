// Railway health-check target. Kept separate from "/" and exempted from the
// origin-auth guard in proxy.js, so Railway's internal probe — which does NOT
// arrive through Cloudflare and therefore lacks the X-Origin-Auth header — stays
// green even with the origin lock enabled. Returns 200 with no body work.
export function GET() {
  return new Response("ok", {
    status: 200,
    headers: { "cache-control": "no-store" },
  });
}
