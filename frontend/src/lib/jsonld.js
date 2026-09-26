// Serialize an object for a <script type="application/ld+json"> block.
// JSON.stringify leaves "<" alone, so a backend string containing
// "</script>" would close the tag and inject markup; < is equivalent
// JSON and inert in HTML.
export function safeJsonLd(obj) {
  return JSON.stringify(obj).replace(/</g, "\\u003c");
}
