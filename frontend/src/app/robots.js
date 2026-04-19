const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://polyspotter.com";

export default function robots() {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Filter-only query params (resolves=, severity=) produce thin/duplicate
        // variants of tag pages. Canonicals consolidate authority, but blocking
        // reduces crawl waste on faceted URLs. Pagination (?page=) is allowed
        // since paginated tag pages have unique content and self-canonical.
        disallow: ["/*?*resolves=", "/*?*severity="],
      },
      // AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, etc.)
      // fall under the default "*" allow rule above. We explicitly permit them
      // because these bots cite sources in their answers, which drives referral
      // traffic back to PolySpotter. Remove this comment and add disallow rules
      // here if that policy changes.
    ],
    // Multiple Sitemap: lines are valid per robots.txt spec and let crawlers
    // discover the wallet sitemap without a manual GSC submission.
    sitemap: [
      `${SITE_URL}/sitemap.xml`,
      `${SITE_URL}/sitemap-wallets.xml`,
    ],
  };
}
