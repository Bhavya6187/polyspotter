// Dedicated sitemap for wallet profile pages. Separate from the main sitemap
// because wallets are unbounded (thousands+) and update on a different cadence
// than content pages — keeping them isolated keeps the main sitemap small and
// prevents one slow upstream from blocking content-URL discovery.

export const revalidate = 3600;

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

const PER_PAGE = 1000;
const FETCH_OPTS = { next: { revalidate: 3600 } };

function escapeXml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

async function fetchAllWallets() {
  const all = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages) {
    const res = await fetch(
      `${API_URL}/api/wallets/sitemap?page=${page}&per_page=${PER_PAGE}`,
      FETCH_OPTS
    );
    if (!res.ok) break;
    const data = await res.json();
    const wallets = data?.wallets || [];
    all.push(...wallets);
    const total = data?.total || 0;
    totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    page++;
  }

  return all;
}

export async function GET() {
  let wallets = [];
  try {
    wallets = await fetchAllWallets();
  } catch {
    wallets = [];
  }

  const urls = wallets
    .map((w) => {
      const address = (w.wallet || "").toLowerCase();
      if (!address) return "";
      const lastmod = w.last_seen
        ? new Date(w.last_seen).toISOString()
        : new Date().toISOString();
      return `<url><loc>${escapeXml(SITE_URL)}/wallet/${escapeXml(address)}</loc><lastmod>${lastmod}</lastmod><changefreq>daily</changefreq><priority>0.6</priority></url>`;
    })
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`;

  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
