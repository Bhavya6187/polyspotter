import { test } from "node:test";
import assert from "node:assert/strict";
import { safeJsonLd } from "./jsonld.js";

test("escapes </script> so a string value cannot close the tag", () => {
  const out = safeJsonLd({ name: "evil </script><script>alert(1)</script>" });
  assert.ok(!out.includes("</script"), out);
  assert.ok(!out.includes("<"), out);
});

test("round-trips to the same object", () => {
  const obj = { "@type": "Article", headline: "a < b </script>", n: 1 };
  assert.deepEqual(JSON.parse(safeJsonLd(obj)), obj);
});
