import assert from "node:assert/strict";
import test from "node:test";

import { chartState } from "../../src/pyflowcharts/explorer/static/lib/viewstate.mjs";

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
