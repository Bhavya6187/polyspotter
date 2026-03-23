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
