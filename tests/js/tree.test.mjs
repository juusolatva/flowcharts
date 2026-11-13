import test from "node:test";
import assert from "node:assert/strict";
import { buildTree } from "../../src/pyflowcharts/explorer/static/lib/tree.mjs";

const entry = (key, source) => ({ key, source });

test("folders come from key segments and leaves are source file names", () => {
  const tree = buildTree([entry("pkg/sub/io", "src/pkg/sub/io.py"), entry("pkg/app", "src/pkg/app.py")]);
  assert.equal(tree.files.length, 0);
  assert.equal(tree.folders.length, 1);
  const pkg = tree.folders[0];
  assert.deepEqual([pkg.name, pkg.path], ["pkg", "pkg"]);
  assert.deepEqual(pkg.files.map((f) => f.label), ["app.py"]);
  assert.deepEqual([pkg.folders[0].name, pkg.folders[0].path], ["sub", "pkg/sub"]);
  assert.deepEqual(pkg.folders[0].files.map((f) => f.label), ["io.py"]);
});

test("top-level files stay at the root and keep input order", () => {
  const tree = buildTree([entry("b", "b.py"), entry("a", "a.py")]);
  assert.deepEqual(tree.files.map((f) => f.label), ["b.py", "a.py"]);
  assert.equal(tree.folders.length, 0);
});

test("a Windows-style source path still gives the file name", () => {
  assert.equal(buildTree([entry("x", "C:\\p\\x.py")]).files[0].label, "x.py");
});
