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
test("key slashes stay separate from the qualname segment", () => {
  assert.equal(formatHash({ view: "chart", key: "a/b", qualname: "f" }), "#/chart/a%2Fb/f");
  assert.deepEqual(parseHash("#/chart/a%2Fb/f"), { view: "chart", key: "a/b", qualname: "f" });
});
test("file route", () => {
  assert.equal(formatHash({ view: "file", key: "a/b" }), "#/file/a%2Fb");
  assert.deepEqual(parseHash("#/file/a%2Fb"), { view: "file", key: "a/b" });
});
test("call graph route", () => {
  assert.equal(formatHash({ view: "callgraph" }), "#/");
  assert.deepEqual(parseHash("#/"), { view: "callgraph" });
  assert.deepEqual(parseHash(""), { view: "callgraph" });
  assert.deepEqual(parseHash(undefined), { view: "callgraph" });
});
test("malformed hashes fall back to the call graph", () => {
  for (const h of ["#/chart/m/%E0%A4%A", "#/chart//f", "#/chart/m", "#/file/", "#/nope", "#/file/%E0%A4%A", "#/chart/m/f/x"]) {
    assert.deepEqual(parseHash(h), { view: "callgraph" });
  }
});
