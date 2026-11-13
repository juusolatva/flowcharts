import test from "node:test";
import assert from "node:assert/strict";
import { createDragTracker } from "../../src/pyflowcharts/explorer/static/lib/drag.mjs";

test("movement within the threshold is not a drag", () => {
  const t = createDragTracker(4);
  t.begin(10, 10);
  assert.equal(t.move(13, 10), null);
  assert.equal(t.move(10, 14), null);
  assert.equal(t.dragging, false);
});
test("the first move past the threshold reports the whole distance, later ones the increment", () => {
  const t = createDragTracker(4);
  t.begin(0, 0);
  assert.deepEqual(t.move(5, 0), { dx: 5, dy: 0 });
  assert.equal(t.dragging, true);
  assert.deepEqual(t.move(6, 2), { dx: 1, dy: 2 });
  assert.deepEqual(t.move(1, 2), { dx: -5, dy: 0 });
});
test("begin resets the drag; move before begin is ignored", () => {
  const t = createDragTracker(4);
  assert.equal(t.move(9, 9), null);
  t.begin(0, 0); t.move(9, 9);
  t.begin(0, 0);
  assert.equal(t.dragging, false);
  assert.equal(t.move(1, 1), null);
});
