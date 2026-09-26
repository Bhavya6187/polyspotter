import { test } from "node:test";
import assert from "node:assert/strict";
import { chunkCount } from "./sitemap.js";

test("zero URLs still yields one (empty) child", () => {
  assert.equal(chunkCount(0, 40000), 1);
});

test("exactly one full chunk is one child", () => {
  assert.equal(chunkCount(40000, 40000), 1);
});

test("one URL over a chunk spills into a second child", () => {
  assert.equal(chunkCount(40001, 40000), 2);
});

test("today's ~49.5k markets need two children", () => {
  assert.equal(chunkCount(49541, 40000), 2);
});
