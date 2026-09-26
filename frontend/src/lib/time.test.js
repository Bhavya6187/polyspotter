import { test } from "node:test";
import assert from "node:assert/strict";
import { relativeTime } from "./time.js";

const NOW = Date.parse("2026-09-26T12:00:00Z");

test("relativeTime falls back to the UTC stamp when now is null", () => {
  assert.equal(relativeTime("2026-09-26T11:58:30Z", null), "2026-09-26 11:58 UTC");
});

test("relativeTime renders seconds for a few seconds ago", () => {
  assert.equal(relativeTime("2026-09-26T11:59:55Z", NOW), "5s ago");
});

test("relativeTime renders days for multiple days ago", () => {
  assert.equal(relativeTime("2026-09-23T10:00:00Z", NOW), "3d ago");
});
