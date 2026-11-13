import test from "node:test";
import assert from "node:assert/strict";
import { createTracker, isStale } from "../../src/pyflowcharts/explorer/static/lib/generation.mjs";

test("needsRefetch does not change the current generation", () => {
  const t = createTracker(); t.set(3);
  assert.equal(t.needsRefetch(3), false);
  assert.equal(t.needsRefetch(4), true);
  assert.equal(t.current, 3);
});
test("a fresh tracker needs any generation", () => {
  assert.equal(createTracker().needsRefetch(0), true);
});
test("isStale is true only for 409", () => {
  assert.equal(isStale(409), true);
  assert.equal(isStale(200), false);
  assert.equal(isStale(404), false);
});
