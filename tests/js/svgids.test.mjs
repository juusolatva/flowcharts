import test from "node:test";
import assert from "node:assert/strict";
import { nodeIdFromTitle, splitCallgraphId } from "../../src/pyflowcharts/explorer/static/lib/svgids.mjs";

test("nodeIdFromTitle trims", () => {
  assert.equal(nodeIdFromTitle("  f#L2C4\n"), "f#L2C4");
});
test("splitCallgraphId splits at the first #", () => {
  assert.deepEqual(splitCallgraphId("12#A.m#x"), { doc: 12, qualname: "A.m#x" });
  assert.deepEqual(splitCallgraphId("0#<module>"), { doc: 0, qualname: "<module>" });
});
