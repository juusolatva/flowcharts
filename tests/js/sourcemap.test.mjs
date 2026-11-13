import test from "node:test";
import assert from "node:assert/strict";
import { nodeForLine, fallbackFunction, sourceLines } from "../../src/pyflowcharts/explorer/static/lib/sourcemap.mjs";

test("fallbackFunction ignores the module chart", () => {
  const entry = { functions: [{ qualname: "outer", line: 1, end_line: 9 }, { qualname: "outer.inner", line: 3, end_line: 5 }] };
  assert.equal(fallbackFunction(entry, 4), "outer.inner");
  assert.equal(fallbackFunction(entry, 8), "outer");
  assert.equal(fallbackFunction(entry, 20), null);
  assert.equal(fallbackFunction({ functions: [] }, 1), null);
});
test("nodeForLine skips nodes without a location", () => {
  const chart = { nodes: [{ id: "f#end", location: null }, { id: "f#L2C4", location: { line: 2, end_line: 2 } }] };
  assert.equal(nodeForLine(chart, 2), "f#L2C4");
});
test("nodeForLine picks the smallest span, earliest on ties, else null", () => {
  const chart = { nodes: [
    { id: "wide", location: { line: 1, end_line: 9 } },
    { id: "first", location: { line: 3, end_line: 4 } },
    { id: "second", location: { line: 4, end_line: 5 } },
  ] };
  assert.equal(nodeForLine(chart, 4), "first");
  assert.equal(nodeForLine(chart, 8), "wide");
  assert.equal(nodeForLine(chart, 5), "second");
  assert.equal(nodeForLine(chart, 20), null);
});
test("sourceLines drops the trailing empty element", () => {
  assert.deepEqual(sourceLines("a\nb\n"), ["a", "b"]);
  assert.deepEqual(sourceLines("a\nb"), ["a", "b"]);
  assert.deepEqual(sourceLines(""), []);
  assert.deepEqual(sourceLines("a\n\n"), ["a", ""]);
});
