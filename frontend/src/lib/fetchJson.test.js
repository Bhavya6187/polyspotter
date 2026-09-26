import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { fetchJsonOr404, ApiError } from "./fetchJson.js";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function stub(status, body = {}) {
  globalThis.fetch = async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("returns parsed JSON on 200", async () => {
  stub(200, { ok: 1 });
  assert.deepEqual(await fetchJsonOr404("http://x/api/a"), { ok: 1 });
});

test("returns null on 404", async () => {
  stub(404, { detail: "not found" });
  assert.equal(await fetchJsonOr404("http://x/api/a"), null);
});

test("throws ApiError carrying .status on 5xx", async () => {
  stub(503);
  await assert.rejects(fetchJsonOr404("http://x/api/a"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 503);
    return true;
  });
});

test("propagates network errors instead of treating them as 404", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(fetchJsonOr404("http://x/api/a"), TypeError);
});
