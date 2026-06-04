/** @type {import('next').NextConfig} */
const nextConfig = {
  // Disable the in-process ISR memory cache. Pages still revalidate on the
  // file-system cache and at the CDN; we just don't pin rendered HTML +
  // fetched JSON for every URL a crawler hits in RAM. Crawled keyspaces here
  // (markets, wallets, events, tags, articles) are tens of thousands of URLs,
  // which can grow the resident set into multi-GB territory by default.
  cacheMaxMemorySize: 0,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "polymarket-upload.s3.us-east-2.amazonaws.com",
      },
    ],
  },
};

export default nextConfig;
