/**
 * Create a URL-friendly slug from a market title and condition ID.
 * Uses only the first 5 hex chars of the condition ID for shorter URLs.
 * Example: "Will Trump win 2024?" + "0xc5300759dc..." -> "will-trump-win-2024-0xc530"
 */
export function marketSlug(title, conditionId) {
  if (!title || !conditionId) return conditionId || "";
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  const shortId = conditionId.slice(0, 7); // "0x" + 5 hex chars
  return `${slug}-${shortId}`;
}

/**
 * Extract the partial condition ID (0x.....) from a market slug.
 * Returns the 0x-prefixed hex suffix which can be used to resolve the full ID via the API.
 */
export function partialIdFromSlug(slug) {
  const match = slug.match(/(0x[a-fA-F0-9]+)$/);
  return match ? match[1] : slug;
}

/**
 * Extract the title part of a market slug (everything before the trailing
 * "-0x…" short id). Sent to /api/market/resolve as `slug` so colliding
 * 5-hex-char prefixes (~1,150 of them) resolve to the right market.
 */
export function titleSlugFromSlug(slug) {
  return slug.replace(/-?0x[a-fA-F0-9]+$/, "");
}

/**
 * Tag -> URL slug (not percent-encoded). Hyphens survive and case is lost, so
 * the slug can't be mapped back to the tag by string munging alone:
 * "Spider-Man" -> "spider-man". Links wrap this in encodeURIComponent.
 */
export function tagSlug(tag) {
  return tag.toLowerCase().replace(/\s+/g, "-");
}

/**
 * Resolve an incoming /tag/<slug> (already decoded by the router) to the
 * exact tag string from the known tag list. `tags` may hold strings or
 * /api/tags objects ({ tag } or { name }). Returns the first match or null.
 */
export function resolveTagSlug(slug, tags) {
  if (!slug || !Array.isArray(tags)) return null;
  const want = slug.toLowerCase();
  for (const t of tags) {
    const name = typeof t === "string" ? t : t?.tag ?? t?.name;
    if (typeof name === "string" && tagSlug(name) === want) return name;
  }
  return null;
}
