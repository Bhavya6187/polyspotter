import { test } from "node:test";
import assert from "node:assert/strict";
import { tagSlug, resolveTagSlug } from "./slugify.js";

const TAGS = [
  { tag: "Politics", alert_count: 10 },
  { tag: "Spider-Man", alert_count: 3 },
  { tag: "US-Iran", alert_count: 2 },
  "Trump-Netanyahu",
  { name: "Earn 4%" },
];

test("tagSlug lowercases and turns whitespace into dashes, keeping hyphens", () => {
  assert.equal(tagSlug("Spider-Man"), "spider-man");
  assert.equal(tagSlug("World Cup"), "world-cup");
});

test("resolves a hyphenated tag object", () => {
  assert.equal(resolveTagSlug("spider-man", TAGS), "Spider-Man");
});

test("resolves an acronym-cased hyphenated tag", () => {
  assert.equal(resolveTagSlug("us-iran", TAGS), "US-Iran");
});

test("resolves a plain string tag", () => {
  assert.equal(resolveTagSlug("trump-netanyahu", TAGS), "Trump-Netanyahu");
});

test("resolves a simple tag", () => {
  assert.equal(resolveTagSlug("politics", TAGS), "Politics");
});

test("resolves a tag given by .name with a literal %", () => {
  assert.equal(resolveTagSlug("earn-4%", TAGS), "Earn 4%");
});

test("unknown slug resolves to null", () => {
  assert.equal(resolveTagSlug("no-such-tag", TAGS), null);
});

test("missing tag list resolves to null", () => {
  assert.equal(resolveTagSlug("politics", undefined), null);
});
