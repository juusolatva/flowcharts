# Directory Recursion and Module-Level Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pyflowcharts` accepts directories (walked recursively, output mirrored) and draws a module-level chart for files whose top level does work.

**Architecture:** The IR gains a base `Chart` and `Document.module` (schema version 2). The Python frontend decides whether the top level "does work" and builds the module chart through the unchanged `cfg` builder. `cli.py` is split: `inputs.py` turns path arguments into `Input(path, key, explicit)` records, and `output.py` writes each document under its output key.

**Tech Stack:** Python ≥ 3.12, tree-sitter / tree-sitter-python, graphviz, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-11-13-directories-and-module-code-design.md`. Read it before starting; it is the source of truth for messages and rules quoted below.

## Global Constraints

- Use `uv run pytest` and `uv run ruff check` / `uv run ruff format`; never bare `pip`, `python` or `pytest`. Both must pass before every commit.
- Layering: `cfg/` must not change. Backends, `cli.py`, `inputs.py` and `output.py` must not import `ast`, tree-sitter or `frontends/python/`. `inputs.py` imports only `supported_extensions` from `pyflowcharts.frontends`.
- No new runtime dependencies (stdlib + `graphviz`, `tree-sitter`, `tree-sitter-python`).
- Output is deterministic: no set iteration or timestamps in any output order.
- Node IDs never contain `:`. The module qualname is exactly `<module>` (`MODULE_QUALNAME`).
- `SCHEMA_VERSION = 2`; `from_json` reads 1 and 2.
- Keep modules under ~300 lines.
- TDD: each step's failing test comes first. CFG-shape tests assert on `flow(chart)`.
- Conventional Commits, one logical change each, on branch `feat/directories-and-module-code`. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. `pyflowcharts .`: the argument `.` must not count as hidden, and keys are relative to it (`pkg/mod`, not `./pkg/mod`). Test in Task 6.
2. Stems containing dots (`a.b.py`): outputs are `a.b.json`, `a.b.svg`, `a.b/`, never `a.json` (no `with_suffix`). Test in Task 5.
3. Upper-case extensions in a walk (`X.PY`) are picked up, like explicit files (the registry lower-cases suffixes). Test in Task 6.
4. Directory arguments spelled differently (`src`, `src/`, absolute path) give the same keys. Test in Task 6.
5. Output directory inside the walked tree (`pyflowcharts . -o charts`, run twice): generated `.json`/`.svg`/`.dot`/`.mmd` files are not picked up on the second run. Test in Task 6.

---

### Task 1: IR `Chart`, `Document.module`, schema version 2

**Files:**
- Modify: `src/pyflowcharts/ir.py`, `src/pyflowcharts/serialize.py`
- Modify tests: `tests/test_serialize.py`, `tests/test_ir.py`, `tests/test_frontend.py:156-163`, `tests/test_python_frontend.py:56`, `tests/test_builder.py:28`, `tests/test_python_statements.py:19`, `tests/conftest.py` (type hints `FunctionChart` → `Chart` in `flow` and `assert_graph_integrity`)

**Interfaces:**
- Produces (`ir.py`): `SCHEMA_VERSION = 2`; `MODULE_QUALNAME = "<module>"`; `@dataclass class Chart(qualname: str, location: SourceLocation, nodes: list[Node], edges: list[Edge])`; `@dataclass class FunctionChart(Chart)` adding `name: str, is_async: bool, parameters: list[Parameter], returns: str | None`; `Document(source, language, functions: list[FunctionChart], module: Chart | None = None, schema_version: int = SCHEMA_VERSION)`; `ChartOptions.show_module: bool = True` as the **last** field.
- Produces (`serialize.py`): `to_json(doc)` unchanged (still `dataclasses.asdict`); `from_json(text) -> Document` accepting versions 1 and 2.

- [ ] **Step 1: Write failing tests** in `tests/test_serialize.py` (build module charts with keyword arguments):

```python
def test_json_shape(doc):  # replaces the existing test
    data = json.loads(to_json(doc))
    assert data["schema_version"] == 2
    assert list(data) == ["source", "language", "functions", "module", "schema_version"]
    assert data["module"] is None
    assert list(data["functions"][0]) == ["qualname", "location", "nodes", "edges",
                                          "name", "is_async", "parameters", "returns"]
    assert data["functions"][0]["nodes"][0]["kind"] == "start"
    assert data["functions"][0]["parameters"][0]["kind"] == "positional_or_keyword"

def test_round_trip_with_module(doc):
    doc.module = Chart(qualname=MODULE_QUALNAME, location=doc.functions[0].location,
                       nodes=doc.functions[0].nodes, edges=doc.functions[0].edges)
    assert from_json(to_json(doc)) == doc
    assert set(json.loads(to_json(doc))["module"]) == {"qualname", "location", "nodes", "edges"}

def test_reads_version_1(doc):
    data = json.loads(to_json(doc))
    data["schema_version"] = 1
    del data["module"]
    old = from_json(json.dumps(data))
    assert (old.schema_version, old.module, old.functions) == (1, None, doc.functions)

def test_rejects_unknown_schema_version(doc):  # extend the existing test
    ...
    with pytest.raises(UnsupportedSchemaVersionError, match=r"expected 1 or 2"):
        from_json(json.dumps(data))
```

  In `tests/test_ir.py` add `assert ChartOptions().show_module is True` to `test_default_options` (keep the positional assertion). Change the `schema_version` expectations in `test_frontend.py` and `test_python_frontend.py` to `2`. Switch the positional `FunctionChart(...)` calls in `test_builder.py` and `test_python_statements.py` to keyword arguments.

- [ ] **Step 2: Run** `uv run pytest tests/test_serialize.py tests/test_ir.py -v`. Expected: FAIL (`Chart`/`MODULE_QUALNAME` import errors, version 1 ≠ 2).

- [ ] **Step 3: Implement** the IR changes listed under Interfaces. Update the `ChartOptions` docstring: options affect labels, which assignment nodes exist and whether a module chart is built, never the data inside a chart. In `serialize.py`: accept `version in (1, 2)` with the message `unsupported schema_version {version!r} (expected 1 or 2)`; read `module` with `data.get("module")` (absent in v1); split `_chart` into `_nodes_edges` helpers shared by `_function_chart(data) -> FunctionChart` and `_module_chart(data) -> Chart`.

- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: all pass.

- [ ] **Step 5: Commit** `feat(ir): add Chart base and Document.module, bump schema to 2`

---

### Task 2: Backends take `Chart`; DOT quotes `<module>`

**Files:**
- Modify: `src/pyflowcharts/backends/dot.py`, `src/pyflowcharts/backends/mermaid.py`
- Test: `tests/test_dot.py`

**Interfaces:**
- Consumes: `Chart`, `MODULE_QUALNAME` (Task 1).
- Produces: `to_digraph(chart: Chart)`, `to_dot(chart: Chart) -> str`, `render(chart: Chart, fmt) -> bytes`, `to_mermaid(chart: Chart) -> str`.

- [ ] **Step 1: Write failing tests** in `tests/test_dot.py`:

```python
def _module_chart() -> Chart:
    c = chart_of("def f():\n    g()\n")
    return Chart(qualname=MODULE_QUALNAME, location=c.location, nodes=c.nodes, edges=c.edges)

def test_module_graph_name_is_quoted():
    assert to_dot(_module_chart()).startswith('digraph "<module>" {')

@needs_dot
def test_module_svg_title_keeps_brackets():
    assert b"<title>&lt;module&gt;</title>" in render(_module_chart(), "svg")
```

- [ ] **Step 2: Run** `uv run pytest tests/test_dot.py -v`. Expected: FAIL (`digraph <module> {`).

- [ ] **Step 3: Implement**: pass `graphviz.nohtml(chart.qualname)` as the `Digraph` name; change the type hints in both backends from `FunctionChart` to `Chart`.

- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.

- [ ] **Step 5: Commit** `fix(dot): quote the graph name so <module> is not read as HTML`

---

### Task 3: Python frontend builds module charts

**Files:**
- Create: `src/pyflowcharts/frontends/python/module.py`
- Modify: `src/pyflowcharts/frontends/python/statements.py`, `src/pyflowcharts/frontends/python/validate.py`, `src/pyflowcharts/frontends/python/frontend.py`
- Test: `tests/test_python_module.py` (new)

**Interfaces:**
- Consumes: `Chart`, `MODULE_QUALNAME`, `ChartOptions.show_module` (Task 1); `build_chart`, `StrayLoopTransfer` (`cfg/builder.py`, unchanged).
- Produces:
  - `statements.convert_statements(parent: Node | None, src: Source, options: ChartOptions) -> Block`: converts `parent`'s named statement children (extras removed), dropping a leading docstring. `convert_body(func, src, options)` keeps its signature and calls `convert_statements(func.child_by_field_name("body"), …)`.
  - `validate.first_error_line(node: Node) -> int | None`: the existing `_first_error_line`, made public (it already skips `function_definition` subtrees).
  - `module.does_work(root: Node) -> bool`.
  - `module.module_chart(root: Node, src: Source, path: str, options: ChartOptions) -> Chart`: raises `StrayLoopTransfer`.
  - Messages in `module.py`: `UNSUPPORTED = "unsupported syntax in module code; module chart skipped"`, `STRAY = "syntax error in module code; module chart skipped"`.

- [ ] **Step 1: Write failing tests** in `tests/test_python_module.py`, with helper `parse(text, **opts)` as in `test_python_frontend.py` (path `"t.py"`):

```python
@pytest.mark.parametrize("src", [
    '"""doc"""\nimport os\nfrom a import b\nfrom __future__ import annotations\n',
    "def f(): pass\n@d\ndef g(): pass\nclass A: pass\n",
    "x = 1\ny += 2\nz: int = 3\nlogger = getLogger(__name__)\ntype T = int\n",
    "pass\n...\nglobal q\n",
    "",
])
def test_no_module_chart_for_declarations(src):
    assert parse(src).document.module is None

@pytest.mark.parametrize("src", [
    "if __name__ == '__main__':\n    main()\n", "for x in y:\n    pass\n",
    "try:\n    import a\nexcept ImportError:\n    a = None\n", "with o:\n    pass\n",
    "assert x\n", "del x\n", "raise SystemExit\n", "main()\n",
    "match x:\n    case 1:\n        pass\n",
])
def test_module_chart_when_top_level_does_work(src):
    assert parse(src).document.module is not None

def test_main_block_flow():
    m = parse('import sys\ndef main(): pass\nif __name__ == "__main__":\n    main()\n').document.module
    cond = 'if __name__ == "__main__"'
    assert flow(m) == {("module t", "import sys", None), ("import sys", "def main()", None),
                       ("def main()", cond, None), (cond, "main()", "True"),
                       (cond, "end", "False"), ("main()", "end", None)}
    assert m.qualname == "<module>"
    assert all(n.id.startswith("<module>#") for n in m.nodes)
    assert_graph_integrity(m)

def test_module_location_spans_first_statement_to_last_token():
    m = parse("\n\nmain()\nother()\n# c\n").document.module
    assert (m.location.line, m.location.end_line) == (3, 4)
    m = parse("#!/usr/bin/env python3\n# head\n\nmain()\n").document.module
    assert (m.location.line, m.location.column, m.location.end_line) == (4, 0, 4)

def test_assignment_with_comment_inside_is_not_work():
    assert parse("x = (  # c\n    1)\ny = \\\n    2\n").document.module is None

def test_no_module_option():
    r = parse("main()\nbreak\n", show_module=False)
    assert r.document.module is None and r.warnings == ()

def test_skeleton_syntax_error_means_no_module_chart():
    r = parse("main()\nx = = 1\ndef g(): pass\n")
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(2, None)]

def test_stray_break_skips_module_chart():
    r = parse("main()\nbreak\ndef g(): pass\n")
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [str(w) for w in r.warnings] == ["t.py:2: warning: syntax error in module code; module chart skipped"]
    assert r.warnings[0].qualname == "<module>"

def test_unsupported_top_level_syntax_skips_module_chart():
    src = "type Box[T = int] = list[T]\ndef g(): pass\n"  # no work: the error check must run first
    try:
        ast.parse(src)
    except SyntaxError:
        pytest.skip("this interpreter does not accept PEP 696 defaults")
    r = parse(src)
    assert r.document.module is None and [c.qualname for c in r.document.functions] == ["g"]
    assert [str(w) for w in r.warnings] == ["t.py:1: warning: unsupported syntax in module code; module chart skipped"]
    assert r.warnings[0].qualname == "<module>"
```

  Leave `tests/test_python_statements.py` calling `convert_body` unchanged.

- [ ] **Step 2: Run** `uv run pytest tests/test_python_module.py -v`. Expected: FAIL (`document.module` is always `None`).

- [ ] **Step 3: Implement.** Make `statements._named` and `statements._is_docstring` public (`named`, `is_docstring`) and use them from `module.py` rather than duplicating them. `does_work` scans `named(root)`, skipping a leading docstring. A child is a declaration if:
  - its type is `import_statement`, `import_from_statement`, `future_import_statement`, `function_definition`, `decorated_definition`, `class_definition`, `type_alias_statement`, `pass_statement` or `global_statement`, or
  - it is an `expression_statement` with exactly one child in `named(child)` (extras removed, as in `_Converter._expression`), and that child's type is `assignment`, `augmented_assignment` or `ellipsis`.

  Any other child means the top level does work. `module_chart` calls `build_chart(MODULE_QUALNAME, f"module {PurePath(path).stem}", location, convert_statements(root, src, options), options)` and wraps the result in a `Chart`. Its `location` starts at the first child in `named(root)` (`start_point`) and ends where `src.location(root)` ends, so leading comments such as a shebang are not included. `Source.location` itself does not change. In `PythonFrontend.parse`, inside the existing `RecursionError` guard and only when `options.show_module and validation.outside is None`, check in this order:
  1. `first_error_line(root)` is not `None` → `Diagnostic(path, line, UNSUPPORTED, MODULE_QUALNAME)`.
  2. otherwise, if `does_work(root)`, build the chart; on `StrayLoopTransfer` → `Diagnostic(path, e.loc.line, STRAY, MODULE_QUALNAME)`.

  These warnings join the line-sorted list. Pass `module=` to `Document`.

- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.

- [ ] **Step 5: Commit** `feat(python): chart module-level code when the top level does work`

---

### Task 4: Move the writer to `output.py` (no behaviour change)

**Files:**
- Create: `src/pyflowcharts/output.py`
- Modify: `src/pyflowcharts/cli.py`, `tests/test_cli.py:102` (monkeypatch target `pyflowcharts.output.render`)

**Interfaces:**
- Produces: `output.Writer(outdir: Path, formats: list[str])` with `.write(doc: Document, stem: str) -> None` and attributes `graphviz_missing: bool`, `write_failed: bool`; `output.GRAPHVIZ_MISSING`, `output.EXTENSIONS`. This is the current `_Writer`, renamed public and moved verbatim.

- [ ] **Step 1: Change the monkeypatch target** in `test_missing_graphviz` to `"pyflowcharts.output.render"`.
- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py::test_missing_graphviz -v`. Expected: FAIL (`pyflowcharts.output` does not exist).
- [ ] **Step 3: Move** `_Writer`, `EXTENSIONS` and `GRAPHVIZ_MISSING` to `output.py`; `cli.py` imports `Writer`.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `refactor(cli): move the output writer to output.py`

---

### Task 5: Writer uses output keys and writes module charts

**Files:**
- Modify: `src/pyflowcharts/output.py`
- Test: `tests/test_output.py` (new)

**Interfaces:**
- Consumes: `Document.module`, `Chart` (Task 1); `Writer` (Task 4).
- Produces: `Writer.write(doc: Document, key: PurePosixPath) -> None`. For base `outdir / key`:
  - `base.parent / f"{base.name}.json"` for JSON.
  - `base.parent / f"{base.name}.{ext}"` for the module chart in each non-JSON format.
  - `base / f"{qualname}.{ext}"` for each function chart.
  - Each file's parent directory is created just before that file is written. Nothing is created for a document with no outputs.

- [ ] **Step 1: Write failing tests** in `tests/test_output.py`. Documents come from `PythonFrontend().parse(...)`.

```python
def test_mirrored_key_with_module_and_functions(tmp_path):
    doc = parse("def f(): pass\nmain()\n")
    Writer(tmp_path, ["json", "dot", "mermaid"]).write(doc, PurePosixPath("pkg/io/load"))
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == {
        "pkg/io/load.json", "pkg/io/load.dot", "pkg/io/load.mmd", "pkg/io/load/f.dot", "pkg/io/load/f.mmd"}

def test_module_only_creates_no_function_directory(tmp_path):
    Writer(tmp_path, ["dot"]).write(parse("main()\n"), PurePosixPath("s"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.dot"]

def test_no_outputs_creates_no_directories(tmp_path):
    Writer(tmp_path / "o", ["dot"]).write(parse(""), PurePosixPath("pkg/__init__"))
    assert not (tmp_path / "o").exists()

def test_dotted_stem_keeps_full_name(tmp_path):  # Review Focus 2
    Writer(tmp_path, ["json", "dot"]).write(parse("def f(): pass\nmain()\n"), PurePosixPath("a.b"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.b", "a.b.dot", "a.b.json"]

def test_missing_graphviz_reported_once_for_module_and_functions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pyflowcharts.output.render", boom)  # raises graphviz.ExecutableNotFound
    w = Writer(tmp_path, ["svg"]); w.write(parse("def f(): pass\nmain()\n"), PurePosixPath("m"))
    assert w.graphviz_missing and capsys.readouterr().err.count("Graphviz") == 1
```

- [ ] **Step 2: Run** `uv run pytest tests/test_output.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the paths listed under Interfaces. Write the module chart before function charts, and handle Graphviz the same way for both (one shared `_chart(chart, target_without_ext)` helper). `_save` creates `target.parent`; drop the up-front `outdir` mkdir. In `cli.py`, call `writer.write(doc, PurePosixPath(path.stem))` for now.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass, including all of `tests/test_cli.py`.
- [ ] **Step 5: Commit** `feat(output): write under output keys and add module chart files`

---

### Task 6: `inputs.py`: expand paths, `--exclude`, dedupe, collisions

**Files:**
- Create: `src/pyflowcharts/inputs.py`
- Modify: `src/pyflowcharts/frontends/__init__.py` (add `supported_extensions`)
- Test: `tests/test_inputs.py` (new)

**Interfaces:**
- Produces:
  - `frontends.supported_extensions() -> tuple[str, ...]`: every registered frontend's extensions, lower-case, in registry order.
  - `@dataclass(frozen=True) class Input(path: Path, key: PurePosixPath, explicit: bool)`.
  - `@dataclass(frozen=True) class Expansion(inputs: list[Input], warnings: list[str], errors: list[str])`. Messages are complete lines ready to print.
  - `expand(paths: list[Path], excludes: list[str]) -> Expansion`.
  - `collision_error(inputs: list[Input]) -> str | None`.
- Rules (spec "The walk", "`--exclude GLOB`", "Output paths"):
  - **Arguments.** A path that is not a directory, including a missing one, is an explicit input with key `PurePosixPath(path.stem)`, passed through unchecked. A directory (`is_dir()`, following a symlinked argument) is walked.
  - **What the walk keeps.** Prune directories named `__pycache__`, directories that are symlinks, names starting with `.` below the argument, and excluded paths. Keep only regular files (`is_file()`) whose `suffix.lower()` is in `supported_extensions()`.
  - **Order and keys.** Collect every walked file, then sort by `rel.parts`. Key = `rel.with_suffix("")` as a `PurePosixPath`. Build it from the parts so a dotted stem keeps its full name: `PurePosixPath(*rel.parent.parts, Path(rel.name).stem)`.
  - **Unreadable directories.** Use `os.walk(top, onerror=…)`. Each `OSError` adds `f"{err.filename or top}: error: cannot read directory: {err.strerror or err}"` to `errors`.
  - **Empty directory.** If a directory argument yields no files (counted before cross-argument dedupe) and its walk reported no error, add `f"warning: {path}: no source files found"` to `warnings`. An unreadable argument gets only the error.
  - **Dedupe.** Dedupe by `path.resolve()`. The first occurrence keeps its path and key; `explicit` becomes true if any occurrence was explicit.
  - **Exclude matching**, for relative path `rel` and `is_dir`:

    ```python
    for pattern in excludes:
        dir_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if dir_only and not is_dir:
            continue
        target = rel.as_posix() if "/" in pattern else rel.name
        if fnmatch.fnmatchcase(target, pattern):
            return True
    ```
  - **Collisions.** Build `dict[tuple[str, ...], Input]` from `key.parts`, in input order. For a duplicate key, return `f"error: output name collision: {a.path} and {b.path} both map to '{key}'; run them separately with different --output directories"`, where `a` is first. Otherwise, for each input, check each proper prefix of its parts against the dict. On a hit `s` (shorter) and `l` (longer), return `f"error: output name collision: {s.path} maps to '{s.key}' and {l.path} to '{l.key}', which would share the directory '{s.key}'; run them separately with different --output directories"`.

- [ ] **Step 1: Write failing tests** in `tests/test_inputs.py`. Use a `tree(tmp_path, *relpaths)` helper that creates files containing `"pass\n"`, and `keys(expansion) = [i.key.as_posix() for i in expansion.inputs]`.

```python
def test_walk_order_and_keys(tmp_path):
    tree(tmp_path, "z.py", "pkg/__init__.py", "pkg/io/load.py", "a.py", "notes.txt")
    assert keys(expand([tmp_path], [])) == ["a", "pkg/__init__", "pkg/io/load", "z"]
    assert all(not i.explicit for i in expand([tmp_path], []).inputs)

def test_hidden_pycache_and_dir_symlinks_skipped(tmp_path):
    tree(tmp_path, "src/.venv/x.py", "src/.h.py", "src/__pycache__/c.py", "src/ok.py", "other/o.py")
    (tmp_path / "src/link").symlink_to(tmp_path / "other", target_is_directory=True)
    (tmp_path / "src/broken.py").symlink_to(tmp_path / "missing.py")
    assert keys(expand([tmp_path / "src"], [])) == ["ok"]

def test_file_symlink_to_regular_file_is_charted(tmp_path):
    tree(tmp_path, "real/m.py", "src/a.py"); (tmp_path / "src/l.py").symlink_to(tmp_path / "real/m.py")
    assert keys(expand([tmp_path / "src"], [])) == ["a", "l"]

def test_hidden_directory_argument_is_walked(tmp_path):
    tree(tmp_path, ".hidden/x.py")
    assert keys(expand([tmp_path / ".hidden"], [])) == ["x"]

def test_symlinked_directory_argument_is_walked(tmp_path):
    tree(tmp_path, "real/m.py"); (tmp_path / "ln").symlink_to(tmp_path / "real", target_is_directory=True)
    assert keys(expand([tmp_path / "ln"], [])) == ["m"]

@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_directory_is_an_error_and_walk_continues(tmp_path):
    tree(tmp_path, "locked/x.py", "ok.py"); (tmp_path / "locked").chmod(0)
    try:
        e = expand([tmp_path], [])
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert keys(e) == ["ok"] and e.errors == [f"{tmp_path / 'locked'}: error: cannot read directory: Permission denied"]

@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_directory_argument_gets_only_the_error(tmp_path):
    (tmp_path / "locked").mkdir(); (tmp_path / "locked").chmod(0)
    try:
        e = expand([tmp_path / "locked"], [])
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert len(e.errors) == 1 and e.warnings == []

def test_explicit_files_pass_through(tmp_path):
    e = expand([tmp_path / "nope.py", tmp_path / "x.js"], [])
    assert [(i.key.as_posix(), i.explicit) for i in e.inputs] == [("nope", True), ("x", True)]

@pytest.mark.parametrize("patterns, expected", [
    (["venv"], ["a", "pkg/m", "pkg/sub/s", "x_pb2"]),
    (["*_pb2.py"], ["a", "pkg/m", "pkg/sub/s", "venv/v"]),
    (["pkg/*"], ["a", "venv/v", "x_pb2"]), (["pkg/"], ["a", "venv/v", "x_pb2"]),
    (["m.py/"], ["a", "pkg/m", "pkg/sub/s", "venv/v", "x_pb2"]),
    (["PKG"], ["a", "pkg/m", "pkg/sub/s", "venv/v", "x_pb2"]),
    (["pkg/sub/"], ["a", "pkg/m", "venv/v", "x_pb2"]),
])
def test_exclude(tmp_path, patterns, expected):
    tree(tmp_path, "a.py", "pkg/m.py", "pkg/sub/s.py", "venv/v.py", "x_pb2.py")
    assert keys(expand([tmp_path], patterns)) == expected

@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_excluded_directory_is_not_walked(tmp_path):
    # a walk into venv/ would hit onerror; pruning means no error
    tree(tmp_path, "venv/x.py", "a.py"); (tmp_path / "venv").chmod(0)
    try:
        assert expand([tmp_path], ["venv/"]).errors == []
    finally:
        (tmp_path / "venv").chmod(0o755)

def test_exclude_does_not_apply_to_explicit_files(tmp_path):
    tree(tmp_path, "venv.py")
    assert keys(expand([tmp_path / "venv.py"], ["venv.py"])) == ["venv"]

def test_dedupe_keeps_first_and_ors_explicit(tmp_path):
    tree(tmp_path, "d/e.py")
    e = expand([tmp_path / "d", tmp_path / "d" / "e.py"], [])
    assert [(i.key.as_posix(), i.explicit) for i in e.inputs] == [("e", True)]

def test_empty_directory_warns_but_repeated_directory_does_not(tmp_path):
    (tmp_path / "empty").mkdir(); tree(tmp_path, "d/x.py")
    assert expand([tmp_path / "empty"], []).warnings == [f"warning: {tmp_path / 'empty'}: no source files found"]
    assert expand([tmp_path / "d", tmp_path / "d"], []).warnings == []

def test_collisions(tmp_path):
    tree(tmp_path, "a/x.py", "b/x.py", "pkg/mod.py", "pkg/mod/__init__.py", "q/m.py", "q/m_extra.py",
         "t/mod/__init__.py")
    assert "both map to 'x'" in collision_error(expand([tmp_path / "a", tmp_path / "b"], []).inputs)
    assert "both map to 'x'" in collision_error(expand([tmp_path / "a/x.py", tmp_path / "b"], []).inputs)
    msg = collision_error(expand([tmp_path / "pkg"], []).inputs)
    assert "maps to 'mod' and" in msg and "share the directory 'mod'" in msg  # longer key first
    msg = collision_error(expand([tmp_path / "pkg/mod.py", tmp_path / "t"], []).inputs)
    assert "maps to 'mod' and" in msg and "share the directory 'mod'" in msg  # shorter key first
    assert collision_error(expand([tmp_path / "q"], []).inputs) is None

def test_dot_argument(tmp_path, monkeypatch):  # Review Focus 1
    tree(tmp_path, "pkg/m.py"); monkeypatch.chdir(tmp_path)
    assert keys(expand([Path(".")], [])) == ["pkg/m"]

def test_upper_case_extension_in_walk(tmp_path):  # Review Focus 3
    tree(tmp_path, "X.PY")
    assert keys(expand([tmp_path], [])) == ["X"]

def test_argument_spellings_give_same_keys(tmp_path, monkeypatch):  # Review Focus 4
    tree(tmp_path, "src/p/m.py"); monkeypatch.chdir(tmp_path)
    assert keys(expand([Path("src")], [])) == keys(expand([Path("src/")], [])) == keys(expand([tmp_path / "src"], []))

def test_outputs_inside_tree_are_not_inputs(tmp_path):  # Review Focus 5
    tree(tmp_path, "m.py", "charts/m.json", "charts/m.svg", "charts/m.dot", "charts/m.mmd")
    assert keys(expand([tmp_path], [])) == ["m"]
```

  In the `pkg/` collision case, walk order visits `pkg/mod/__init__.py` before `pkg/mod.py`, so this test also covers the reverse direction.

- [ ] **Step 2: Run** `uv run pytest tests/test_inputs.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `supported_extensions` and `inputs.py` per the rules above.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(inputs): expand directories into inputs with exclude, dedupe and collision checks`

---

### Task 7: CLI: paths, `--exclude`, `--no-module`, `--function '<module>'`, warnings

**Files:**
- Modify: `src/pyflowcharts/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `expand`, `collision_error`, `Input` (Task 6); `Writer.write(doc, key)` (Task 5); `MODULE_QUALNAME`, `ChartOptions.show_module` (Task 1).
- Changes:
  - **Arguments.**
    - The positional argument becomes `paths`, `nargs="+"`, `type=Path`, `metavar="PATH"`, help `"source files or directories"`.
    - `--exclude`: `nargs="+"`, `action="extend"`, `default=[]`, `metavar="GLOB"`, `type=_exclude_pattern`. The type raises `ArgumentTypeError` when `text.rstrip("/") == ""`.
    - `--no-module`: `store_true`, sets `show_module=False`.
    - Epilog: `"Put input paths before options that take several values (-f, --function, --exclude)."`
  - **Main flow.**
    1. Run `expand`. If `collision_error` returns a message, print it and return 1 before writing anything.
    2. Print the expansion's warnings and errors; any error sets status 1.
    3. Parse each input.
    4. Compute the set of explicit inputs that get `nothing to chart`: no function charts, no module chart and no warnings. Do this before `--function` selection.
    5. Select.
    6. In the per-file loop, print the warnings and the `warning: {path}: nothing to chart` line.
    7. Write each document with `writer.write(doc, input.key)`.
  - **`_select`.**
    - The available list is deduplicated with `dict.fromkeys`. For each file, in input order, it holds that file's function qualnames, then `<module>` if the file has a module chart, then `"{qualname} (skipped)"` for every warning with a qualname, which covers `<module>`.
    - Filtered documents are built with `dataclasses.replace(document, functions=…, module=document.module if MODULE_QUALNAME in wanted else None)`.

- [ ] **Step 1: Write failing tests** in `tests/test_cli.py`. Rename `test_no_functions_warns` to `test_nothing_to_chart_warns` and expect `"nothing to chart"`. In `test_all_functions_skipped_…`, assert that `"nothing to chart"` is absent. Add:

```python
def test_directory_input_mirrors_tree(tmp_path):
    write(tmp_path / "src/pkg/io", "load.py", "def f(): pass\nmain()\n")
    write(tmp_path / "src/pkg", "__init__.py", "")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json", "dot"]) == 0
    files = {p.relative_to(tmp_path / "o").as_posix() for p in (tmp_path / "o").rglob("*") if p.is_file()}
    assert files == {"pkg/__init__.json", "pkg/io/load.json", "pkg/io/load.dot", "pkg/io/load/f.dot"}
    doc = from_json((tmp_path / "o/pkg/io/load.json").read_text())
    assert doc.source == str(tmp_path / "src/pkg/io/load.py") and doc.module.qualname == "<module>"

def test_walked_empty_file_does_not_warn(tmp_path, capsys):
    write(tmp_path / "d", "__init__.py", "")
    assert main([str(tmp_path / "d"), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert capsys.readouterr().err == ""

def test_explicit_file_also_walked_still_warns(tmp_path, capsys):
    empty = write(tmp_path / "d", "e.py", "")
    assert main([str(tmp_path / "d"), str(empty), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert f"warning: {empty}: nothing to chart" in capsys.readouterr().err

def test_empty_directory_warning(tmp_path, capsys):
    (tmp_path / "e").mkdir()
    assert main([str(tmp_path / "e"), "-o", str(tmp_path / "o")]) == 0
    assert "no source files found" in capsys.readouterr().err

def test_exclude_option(tmp_path):
    write(tmp_path / "s/venv", "v.py", "def v(): pass\n"); write(tmp_path / "s", "a.py", "def a(): pass\n")
    assert main([str(tmp_path / "s"), "-o", str(tmp_path / "o"), "-f", "json", "--exclude", "venv"]) == 0
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["a.json"]

def test_exclude_rejects_bare_slash(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path), "--exclude", "/"])
    assert exc.value.code == 2

def test_prefix_collision_writes_nothing(tmp_path, capsys):
    write(tmp_path / "s", "mod.py", "def f(): pass\n"); write(tmp_path / "s/mod", "__init__.py", "")
    assert main([str(tmp_path / "s"), "-o", str(tmp_path / "o")]) == 1
    assert "share the directory 'mod'" in capsys.readouterr().err and not (tmp_path / "o").exists()

def test_no_module_option(tmp_path):
    src = write(tmp_path, "s.py", "def f(): pass\nmain()\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--no-module"]) == 0
    assert from_json((tmp_path / "o/s.json").read_text()).module is None

def test_function_selects_module(tmp_path):
    src = write(tmp_path, "s.py", "def f(): pass\nmain()\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "<module>"]) == 0
    doc = from_json((tmp_path / "o/s.json").read_text())
    assert doc.functions == [] and doc.module is not None and doc.schema_version == 2
    assert main([str(src), "-o", str(tmp_path / "o2"), "-f", "json", "--function", "f"]) == 0
    assert from_json((tmp_path / "o2/s.json").read_text()).module is None

def test_skipped_module_and_function_filter(tmp_path, capsys):
    src = write(tmp_path, "s.py", "def good(): pass\nbreak\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "good"]) == 0
    assert "module chart skipped" not in capsys.readouterr().err
    assert main([str(src), "-o", str(tmp_path / "o2"), "-f", "json", "--function", "<module>"]) == 1
    assert "syntax error in module code; module chart skipped" in capsys.readouterr().err

def test_available_list_is_deduplicated(tmp_path, capsys):
    a = write(tmp_path / "a", "a.py", "def f(): pass\nmain()\n")
    b = write(tmp_path / "b", "b.py", "def f(): pass\nmain()\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o"), "--function", "zzz"]) == 1
    assert "available: f, <module>" in capsys.readouterr().err

def test_no_nothing_to_chart_after_function_filter(tmp_path, capsys):
    a = write(tmp_path, "a.py", "def foo(): pass\n"); b = write(tmp_path, "b.py", "def bar(): pass\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o"), "-f", "json", "--function", "foo"]) == 0
    assert "nothing to chart" not in capsys.readouterr().err

def test_syntax_error_only_file_has_no_nothing_to_chart(tmp_path, capsys):
    src = write(tmp_path, "s.py", "x = = 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    err = capsys.readouterr().err
    assert "syntax error outside functions" in err and "nothing to chart" not in err
```

  The existing `test_stem_collision` and `test_same_file_twice_is_not_a_collision` must keep passing unchanged.

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the changes listed under Interfaces. Remove `_unique_paths` and `_stem_collision`; `inputs.py` replaces them.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`, and check `wc -l src/pyflowcharts/cli.py` (target < 300). Expected: pass.
- [ ] **Step 5: Smoke test**: `uv run pyflowcharts src -o /tmp/pyflowcharts-self -f json mermaid`. Expected: exit 0, a mirrored `pyflowcharts/…` tree, and exactly one module chart, `pyflowcharts/cfg/finally_.mmd`, because of its top-level `if TYPE_CHECKING:` block.
- [ ] **Step 6: Commit** `feat(cli): accept directories, --exclude, --no-module and --function '<module>'`

---

### Task 8: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`, `AGENTS.md`, `README.md`, `docs/superpowers/specs/2026-11-13-directories-and-module-code-design.md` (status line)

- [ ] **Step 1: Main spec.** Fold in this feature, following the spec's Documentation section:
  - Status line: amended by the new spec.
  - Scope: directory recursion and module code move to in scope; class bodies beyond methods and call graphs remain out of scope.
  - IR: `Chart`, `module`, `schema_version` 2, and the `<module>` IDs.
  - Output layout with keys.
  - CLI synopsis and `--function '<module>'`.
  - Error table rows.
- [ ] **Step 2: `AGENTS.md`.**
  - Node ID format: add `<module>#…`.
  - Architecture: add `inputs.py` and `output.py`.
  - CLI example: `uv run pyflowcharts PATH … -o OUTDIR`.
  - Known simplifications: drop directory recursion and module-level code; add "class bodies are charted only through their methods".
- [ ] **Step 3: `README.md`.**
  - Schema version 2.
  - Known simplifications: remove the two bullets that PR #2 made out of date (exceptions drawn from the `try` node; `return`/`raise` skipping `finally`) and replace them with the current one: handlers are assumed to catch whatever reaches them.
  - Usage lines for `pyflowcharts src/`, `--exclude`, `--no-module` and `--function '<module>'`.
  - A sentence on when module charts appear.
  - Exit-code note: "nothing to chart".
  - Remove directory recursion and module code from the known simplifications.
- [ ] **Step 4: New spec status.** Set it to "Implemented; folded into the main spec."
- [ ] **Step 5: Verify** with `uv run pytest && uv run ruff check`, and `grep -in "no functions\|schema version 1\|(= 1)\|not supported yet\|out of scope for the MVP\|edges from the .try. node\|straight to the end" README.md AGENTS.md docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`. Expected: tests pass and grep prints nothing.
- [ ] **Step 6: Commit** `docs: describe directory inputs and module charts`
