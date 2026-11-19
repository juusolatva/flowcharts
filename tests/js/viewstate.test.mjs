import assert from "node:assert/strict";
import test from "node:test";

import {
  chartState,
  createViewMemory,
  movedView,
  viewKey,
} from "../../src/pyflowcharts/explorer/static/lib/viewstate.mjs";

const entry = (extra = {}) => ({
  error: null,
  skipped: [{ qualname: "bad" }],
  functions: [{ qualname: "f" }],
  has_module: true,
  ...extra,
});

test("chartState: missing entry or chart is gone", () => {
  assert.equal(chartState(undefined, "f", "<module>"), "gone");
  assert.equal(chartState(entry(), "nope", "<module>"), "gone");
});

test("chartState: a file error wins over a vanished chart", () => {
  assert.equal(chartState(entry({ error: "denied", functions: [] }), "f", "<module>"), "error");
});

test("chartState: skipped, function and module charts", () => {
  assert.equal(chartState(entry(), "bad", "<module>"), "skipped");
  assert.equal(chartState(entry(), "f", "<module>"), "chart");
  assert.equal(chartState(entry(), "<module>", "<module>"), "chart");
  assert.equal(chartState(entry({ has_module: false }), "<module>", "<module>"), "gone");
});

test("viewKey: one key per call graph or chart, none for file views", () => {
  assert.equal(viewKey({ view: "callgraph" }), "callgraph");
  const a = viewKey({ view: "chart", key: "pkg/a", qualname: "f" });
  assert.equal(a, viewKey({ view: "chart", key: "pkg/a", qualname: "f" }));
  assert.notEqual(a, viewKey({ view: "chart", key: "pkg/a", qualname: "g" }));
  assert.notEqual(a, viewKey({ view: "chart", key: "pkg/b", qualname: "f" }));
  // no separator trick can make two different charts share a key
  assert.notEqual(
    viewKey({ view: "chart", key: "a", qualname: "b,c" }),
    viewKey({ view: "chart", key: "a,b", qualname: "c" }),
  );
  assert.equal(viewKey({ view: "file", key: "pkg/a" }), null);
});

test("movedView: null while the view is where it started", () => {
  assert.equal(movedView([0, 0, 100, 50], [0, 0, 100, 50]), null);
  assert.deepEqual(movedView([0, 0, 100, 50], [10, 0, 100, 50]), [10, 0, 100, 50]);
  assert.deepEqual(movedView([0, 0, 100, 50], [0, 0, 80, 40]), [0, 0, 80, 40]);
});

test("view memory: a redraw of the same view gets its moved view back", () => {
  const memory = createViewMemory();
  memory.remember("callgraph", [1, 2, 3, 4]);
  assert.deepEqual(memory.recall("callgraph"), [1, 2, 3, 4]);
  assert.equal(memory.recall("chart-a"), null);
});

test("view memory: an untouched view is not restored", () => {
  const memory = createViewMemory();
  memory.remember("a", [1, 2, 3, 4]);
  memory.remember("a", null); // the redrawn chart was fitted and not moved again
  assert.equal(memory.recall("a"), null);
});

test("view memory: opening another view forgets the first", () => {
  const memory = createViewMemory();
  memory.remember("a", [1, 2, 3, 4]);
  memory.remember("b", null);
  assert.equal(memory.recall("a"), null); // back to a: it opens fitted, like any navigation
});

test("view memory: a null key (a notice, no chart) is ignored", () => {
  const memory = createViewMemory();
  memory.remember("a", [1, 2, 3, 4]);
  memory.remember(null, null);
  assert.deepEqual(memory.recall("a"), [1, 2, 3, 4]);
  assert.equal(memory.recall(null), null);
});

test("movedView: zooming in and back out counts as unmoved despite float error", () => {
  // The viewBox is stored as 32-bit floats; replay the zoom buttons' arithmetic with that rounding.
  const f = Math.fround;
  const initial = [0, 0, 320, 279];
  let box = initial.map(f);
  for (const k of [1.25, 1.25, 1.15, 1 / 1.25, 1 / 1.15, 1 / 1.25]) {
    const [x, y, w, h] = box;
    const [cx, cy] = [x + w / 2, y + h / 2];
    box = [f(cx - (cx - x) / k), f(cy - (cy - y) / k), f(w / k), f(h / k)];
  }
  assert.notDeepEqual(box, initial); // the error this test is about
  assert.equal(movedView(initial, box), null);
});

test("movedView: a small real pan or zoom still counts as moved", () => {
  // A drag pans at least the 4px drag threshold; one wheel step zooms by 15%.
  assert.deepEqual(movedView([0, 0, 320, 279], [2, 0, 320, 279]), [2, 0, 320, 279]);
  assert.notEqual(movedView([0, 0, 320, 279], [0, 0, 320 / 1.15, 279 / 1.15]), null);
});
