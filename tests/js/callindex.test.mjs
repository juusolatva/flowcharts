import test from "node:test";
import assert from "node:assert/strict";
import { buildCallIndex, distinctTargets, resolveTarget } from "../../src/pyflowcharts/explorer/static/lib/callindex.mjs";

test("distinct targets collapse repeated calls", () => {
  const t = { module: "m", qualname: "g" };
  assert.deepEqual(distinctTargets([{ node: "f#L2C4", target: t }, { node: "f#L2C4", target: t }], "f#L2C4"), [t]);
});
test("distinct targets skip other nodes and unresolved calls, keep first-seen order", () => {
  const a = { module: "m", qualname: "a" };
  const b = { module: "m", qualname: "b" };
  const calls = [
    { node: "n", target: b },
    { node: "n", target: null },
    { node: "other", target: a },
    { node: "n", target: a },
    { node: "n", target: { ...b } },
  ];
  assert.deepEqual(distinctTargets(calls, "n"), [b, a]);
});
test("resolveTarget follows the linker's unique-module rule", () => {
  const state = { entries: [{ key: "p/__init__", module_name: "p" }, { key: "a.b", module_name: "a.b" }, { key: "x1", module_name: "x" }, { key: "x2", module_name: "x" }, { key: "e", module_name: "" }] };
  assert.deepEqual(resolveTarget(state, { module: "p", qualname: "f" }), { key: "p/__init__", qualname: "f" });
  assert.deepEqual(resolveTarget(state, { module: "a.b", qualname: "g" }), { key: "a.b", qualname: "g" });
  assert.equal(resolveTarget(state, { module: "x", qualname: "h" }), null);
  assert.equal(resolveTarget(state, { module: "", qualname: "h" }), null);
  assert.equal(resolveTarget(state, { module: "none", qualname: "h" }), null);
});
const state = {
  entries: [
    { key: "a", doc: 0, functions: [{ qualname: "f" }, { qualname: "h" }] },
    { key: "b", doc: 1, functions: [{ qualname: "f" }] },
  ],
  edges: [
    [[0, "f"], [1, "f"]],
    [[0, "h"], [1, "f"]],
    [[0, "f"], [0, "h"]],
  ],
};
test("callers and callees disambiguate repeated qualnames with the key", () => {
  const idx = buildCallIndex(state);
  assert.deepEqual(idx.callees(0, "f"), [
    { doc: 1, key: "b", qualname: "f", label: "f (b)" },
    { doc: 0, key: "a", qualname: "h", label: "h" },
  ]);
  assert.deepEqual(idx.callers(1, "f"), [
    { doc: 0, key: "a", qualname: "f", label: "f (a)" },
    { doc: 0, key: "a", qualname: "h", label: "h" },
  ]);
});
test("unknown functions have no callers or callees", () => {
  const idx = buildCallIndex(state);
  assert.deepEqual(idx.callers(5, "zz"), []);
  assert.deepEqual(idx.callees(5, "zz"), []);
});
test("edges to unknown documents are ignored; module charts count", () => {
  const idx = buildCallIndex({ entries: [{ key: "a", doc: 0, functions: [] }], edges: [[[0, "<module>"], [9, "x"]], [[0, "<module>"], [0, "<module>"]]] });
  assert.deepEqual(idx.callees(0, "<module>"), [{ doc: 0, key: "a", qualname: "<module>", label: "<module>" }]);
});
