import assert from "node:assert/strict";
import test from "node:test";

import { opensSearch } from "../../src/pyflowcharts/explorer/static/lib/keys.mjs";

test("opensSearch: plain slash outside inputs", () => {
  assert.equal(opensSearch({ key: "/", target: { tagName: "DIV" } }), true);
  assert.equal(opensSearch({ key: "a", target: { tagName: "DIV" } }), false);
});

test("opensSearch: not while typing or with modifiers", () => {
  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {
    assert.equal(opensSearch({ key: "/", target: { tagName } }), false);
  }
  assert.equal(opensSearch({ key: "/", target: { tagName: "DIV", isContentEditable: true } }), false);
  for (const mod of ["ctrlKey", "metaKey", "altKey"]) {
    assert.equal(opensSearch({ key: "/", [mod]: true, target: { tagName: "DIV" } }), false);
  }
});
