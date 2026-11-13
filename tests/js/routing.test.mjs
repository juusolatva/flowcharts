import test from "node:test";
import assert from "node:assert/strict";
import { parseHash, formatHash } from "../../src/pyflowcharts/explorer/static/lib/routing.mjs";

test("chart route round-trips special characters", () => {
  const route = { view: "chart", key: "pkg/a b#c", qualname: "größe" };
  assert.deepEqual(parseHash(formatHash(route)), route);
});
test("module chart route", () => {
  assert.equal(formatHash({ view: "chart", key: "m", qualname: "<module>" }), "#/chart/m/%3Cmodule%3E");
});
test("key segments are encoded separately: a/b stays two segments", () => {
  assert.equal(formatHash({ view: "chart", key: "a/b", qualname: "f" }), "#/chart/a/b/f");
  assert.deepEqual(parseHash("#/chart/a/b/f"), { view: "chart", key: "a/b", qualname: "f" });
});
test("multi-segment keys round-trip for chart and file routes", () => {
  const chart = { view: "chart", key: "pkg/sub/mod", qualname: "A.m" };
  assert.equal(formatHash(chart), "#/chart/pkg/sub/mod/A.m");
  assert.deepEqual(parseHash(formatHash(chart)), chart);
  const file = { view: "file", key: "pkg/sub/mod" };
  assert.equal(formatHash(file), "#/file/pkg/sub/mod");
  assert.deepEqual(parseHash(formatHash(file)), file);
});
test("an extra segment extends the key", () => {
  assert.deepEqual(parseHash("#/chart/m/f/x"), { view: "chart", key: "m/f", qualname: "x" });
});
test("file route", () => {
  assert.equal(formatHash({ view: "file", key: "a/b" }), "#/file/a/b");
  assert.deepEqual(parseHash("#/file/a/b"), { view: "file", key: "a/b" });
});
test("call graph route", () => {
  assert.equal(formatHash({ view: "callgraph" }), "#/");
  assert.deepEqual(parseHash("#/"), { view: "callgraph" });
  assert.deepEqual(parseHash(""), { view: "callgraph" });
  assert.deepEqual(parseHash(undefined), { view: "callgraph" });
});
test("malformed hashes fall back to the call graph", () => {
  for (const h of ["#/chart/m/%E0%A4%A", "#/chart//f", "#/chart/m", "#/file/", "#/nope", "#/file/%E0%A4%A", "#/file/a//b", "#/chart/m//"]) {
    assert.deepEqual(parseHash(h), { view: "callgraph" });
  }
});
