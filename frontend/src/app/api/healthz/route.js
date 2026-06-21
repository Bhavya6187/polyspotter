// Railway health-check target (healthcheckPath in railway.json). Plain 200.
export function GET() {
  return new Response("ok", {
    status: 200,
    headers: { "cache-control": "no-store" },
  });
}
