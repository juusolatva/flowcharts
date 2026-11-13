import test from "node:test";
import assert from "node:assert/strict";
import { searchCharts } from "../../src/pyflowcharts/explorer/static/lib/search.mjs";

const entries = [
  { key: "pkg/a", functions: [{ qualname: "Run" }, { qualname: "go" }], has_module: true, skipped: [{ qualname: "broken" }] },
  { key: "b", functions: [{ qualname: "run_it" }], has_module: false, skipped: [] },
];

test("case-insensitive substring over qualname and key, in sidebar order", () => {
  assert.deepEqual(searchCharts(entries, "RUN").map((r) => r.qualname), ["Run", "run_it"]);
  assert.deepEqual(searchCharts(entries, "pkg").map((r) => r.qualname), ["Run", "go", "broken", "<module>"]);
});
test("labels and skipped flag", () => {
  const [hit] = searchCharts(entries, "broken");
  assert.deepEqual(hit, { key: "pkg/a", qualname: "broken", label: "broken — pkg/a", skipped: true });
  assert.equal(searchCharts(entries, "go")[0].skipped, false);
});
test("module charts are searchable", () => {
  assert.deepEqual(searchCharts(entries, "<mod").map((r) => r.key), ["pkg/a"]);
});
test("empty or blank query returns nothing", () => {
  assert.deepEqual(searchCharts(entries, ""), []);
  assert.deepEqual(searchCharts(entries, "   "), []);
});
test("entries without charts are tolerated", () => {
  assert.deepEqual(searchCharts([{ key: "e" }], "e"), []);
});
