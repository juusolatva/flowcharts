# python-flowcharts MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI (`pyflowcharts`) that turns each function in a Python file into a control-flow flowchart, output as JSON, DOT, SVG, PNG and Mermaid.

**Architecture:** A language frontend (`PythonFrontend`, built on stdlib `ast`) produces a language-neutral IR (`Document` → `FunctionChart` → `Node`/`Edge` dataclasses). Backends (JSON, DOT/Graphviz, Mermaid) consume only the IR. The CLI wires files → frontend → backends → output files.

**Tech Stack:** Python ≥ 3.12, stdlib `ast`/`argparse`/`json`/`dataclasses`, `graphviz` (Python package ≥ 0.21 plus the system `dot` binary), `uv`, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`

## Global Constraints

- `requires-python = ">=3.12"`. The only runtime dependency is `graphviz>=0.21`. Dev dependencies: `pytest`, `ruff`.
- Distribution name `python-flowcharts`, import package `pyflowcharts`, `src/` layout, console script `pyflowcharts = "pyflowcharts.cli:main"`.
- JSON `schema_version` is `1`. No layout data (x/y) anywhere in the IR.
- Node IDs: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}`, synthetic suffix `~finally`, duplicated-finally copy suffixes `~break` / `~continue`. **IDs never contain `:`** (DOT port syntax).
- Default `max_label_length` is 60, and truncation appends `…` (U+2026).
- Deterministic output: the same input gives byte-identical JSON, DOT and Mermaid.
- Work on a feature branch, never directly on `main`.
- Run everything through uv: `uv run pytest`, `uv run ruff check`.
- Follow `AGENTS.md` (project agent instructions; `CLAUDE.md` imports it). If it conflicts with this plan, stop and ask.

## Review Focus

1. **Duplicate qualnames** (`@property` + `@x.setter`, redefined functions). Later definitions must get `@L{line}`, so node IDs and output filenames don't collide. Tested in Task 3 (`test_qualnames_and_duplicates`).
2. **Labels containing quotes, backslashes, `\n` escapes, `<`/`>`.** These must survive into DOT and Mermaid without breaking syntax or turning into real newlines. Tested in Task 7 (`test_label_escaping`) and Task 8 (`test_mermaid_escaping`).
3. **Empty and unreachable code**: docstring-only/`pass`/`...` bodies, statements after `return`. These must not crash and should give a sensible graph. Tested in Task 3 (`test_empty_bodies`, `test_unreachable_code_kept`).
4. **Files that don't parse or decode**: syntax errors, null bytes, latin-1 with a coding cookie. These need a clear `path:line` error while other files still get processed. Tested in Task 3 (`test_source_errors`, `test_coding_cookie`) and Task 9 (`test_bad_file_does_not_stop_others`).
5. **Two inputs with the same file stem** (`a/utils.py`, `b/utils.py`) must error before writing anything instead of overwriting silently. Tested in Task 9 (`test_stem_collision`).

---

## File Structure

```
pyproject.toml
README.md                                  # exists (user-created); filled in Task 9
AGENTS.md / CLAUDE.md                      # exist (user-created); CLAUDE.md imports AGENTS.md
src/pyflowcharts/__init__.py               # __version__
src/pyflowcharts/ir.py                     # IR dataclasses, enums, ChartOptions, SCHEMA_VERSION
src/pyflowcharts/labels.py                 # shorten()
src/pyflowcharts/serialize.py              # to_json / from_json
src/pyflowcharts/frontends/__init__.py     # Frontend protocol, SourceError, registry
src/pyflowcharts/frontends/python_ast/__init__.py   # exports PythonFrontend
src/pyflowcharts/frontends/python_ast/frontend.py   # function discovery, qualnames, signatures
src/pyflowcharts/frontends/python_ast/cfg.py        # CfgBuilder: statements → nodes/edges
src/pyflowcharts/backends/__init__.py
src/pyflowcharts/backends/dot.py           # to_digraph / to_dot / render
src/pyflowcharts/backends/mermaid.py       # to_mermaid
src/pyflowcharts/cli.py                    # argparse, file output, exit codes
tests/conftest.py                          # chart_of(), flow() helpers
tests/fixtures/sample.py                   # realistic input used by integration tests
tests/test_ir.py  tests/test_serialize.py  tests/test_frontend.py
tests/test_cfg_branches.py  tests/test_cfg_loops.py  tests/test_cfg_try_with.py
tests/test_dot.py  tests/test_mermaid.py  tests/test_cli.py
```

---

### Task 1: Project scaffold, IR and labels

**Files:**
- Create: `pyproject.toml`, `src/pyflowcharts/__init__.py`, `src/pyflowcharts/ir.py`, `src/pyflowcharts/labels.py`
- Test: `tests/test_ir.py`

**Interfaces:**
- Produces (in `pyflowcharts.ir`):
  - `SCHEMA_VERSION: int = 1`
  - `class NodeKind(StrEnum)`: `START="start"`, `END="end"`, `PROCESS="process"`, `DECISION="decision"`, `LOOP="loop"`, `RETURN="return"`, `RAISE="raise"`
  - `class ParamKind(StrEnum)`: `POSITIONAL_ONLY="positional_only"`, `POSITIONAL_OR_KEYWORD="positional_or_keyword"`, `VAR_POSITIONAL="var_positional"`, `KEYWORD_ONLY="keyword_only"`, `VAR_KEYWORD="var_keyword"`
  - `@dataclass(frozen=True) SourceLocation(line: int, column: int, end_line: int, end_column: int)`
  - `@dataclass(frozen=True) Node(id: str, kind: NodeKind, label: str, location: SourceLocation | None)`
  - `@dataclass(frozen=True) Edge(source: str, target: str, label: str | None = None)`
  - `@dataclass(frozen=True) Parameter(name: str, annotation: str | None, default: str | None, kind: ParamKind)`
  - `@dataclass FunctionChart(qualname: str, name: str, is_async: bool, parameters: list[Parameter], returns: str | None, location: SourceLocation, nodes: list[Node], edges: list[Edge])`
  - `@dataclass Document(source: str, language: str, functions: list[FunctionChart], schema_version: int = SCHEMA_VERSION)`
  - `@dataclass(frozen=True) ChartOptions(show_variables: bool = False, show_parameters: bool = True, show_returns: bool = True, max_label_length: int = 60)`
- Produces (in `pyflowcharts.labels`): `shorten(text: str, max_length: int) -> str`

- [ ] **Step 1: Create branch and `pyproject.toml`**

`git switch -c feat/mvp`. Build backend `hatchling`, settings from Global Constraints, `[dependency-groups] dev = ["pytest", "ruff"]`, `[tool.pytest.ini_options] testpaths = ["tests"]`, `[tool.ruff] line-length = 100`. Add `__version__ = "0.1.0"` in `__init__.py`. Run `uv sync`. Expected: creates `.venv` and `uv.lock`. Add a `.gitignore` covering `.venv/`, `__pycache__/`, `flowcharts/`.

- [ ] **Step 2: Write failing tests**

```python
from pyflowcharts.ir import ChartOptions, NodeKind
from pyflowcharts.labels import shorten

def test_shorten_collapses_whitespace():
    assert shorten("a =  1\n   + 2", 60) == "a = 1 + 2"

def test_shorten_truncates_with_ellipsis():
    assert shorten("x" * 70, 10) == "x" * 9 + "…"
    assert len(shorten("x" * 70, 10)) == 10

def test_shorten_keeps_exact_length():
    assert shorten("x" * 10, 10) == "x" * 10

def test_enum_values_are_strings():
    assert NodeKind.DECISION == "decision"

def test_default_options():
    assert ChartOptions() == ChartOptions(False, True, True, 60)
```

- [ ] **Step 3: Run** `uv run pytest tests/test_ir.py -v`. Expected: FAIL (ImportError).

- [ ] **Step 4: Implement `ir.py` and `shorten()`** as in Interfaces. `shorten` uses `" ".join(text.split())`.

- [ ] **Step 5: Run** `uv run pytest tests/test_ir.py -v && uv run ruff check`. Expected: PASS, no lint errors.

- [ ] **Step 6: Commit** `feat: project scaffold, IR dataclasses and label shortening`

---

### Task 2: JSON serialization

**Files:**
- Create: `src/pyflowcharts/serialize.py`
- Test: `tests/test_serialize.py`

**Interfaces:**
- Consumes: everything in `pyflowcharts.ir` (Task 1).
- Produces:
  - `to_json(doc: Document) -> str`: `json.dumps(dataclasses.asdict(doc), indent=2, ensure_ascii=False) + "\n"`. Enums serialize as their string values. Key order follows dataclass field order.
  - `from_json(text: str) -> Document`: rebuilds the nested dataclasses and enums.
  - `class UnsupportedSchemaVersionError(ValueError)`: raised by `from_json` when `schema_version != SCHEMA_VERSION`.

- [ ] **Step 1: Write failing tests.** Build a `Document` by hand with one `FunctionChart` holding one `Parameter`, nodes of kinds START/PROCESS/END (one with `location=None`), and edges with and without labels.

```python
def test_round_trip(doc):
    assert from_json(to_json(doc)) == doc

def test_json_shape(doc):
    data = json.loads(to_json(doc))
    assert data["schema_version"] == 1
    assert data["functions"][0]["nodes"][0]["kind"] == "start"
    assert data["functions"][0]["parameters"][0]["kind"] == "positional_or_keyword"

def test_deterministic(doc):
    assert to_json(doc) == to_json(copy.deepcopy(doc))

def test_rejects_unknown_schema_version(doc):
    data = json.loads(to_json(doc)); data["schema_version"] = 99
    with pytest.raises(UnsupportedSchemaVersionError):
        from_json(json.dumps(data))

def test_non_ascii_preserved(doc):  # label "print('é')"
    assert "é" in to_json(doc)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_serialize.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `to_json` and `from_json`. Rebuild objects explicitly per type (`SourceLocation(**d)` when not `None`, `NodeKind(d["kind"])`, …). Don't use a generic reflection helper.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: JSON serialization of the IR with schema version check`

---

### Task 3: Frontend protocol, Python function discovery, sequential CFG

**Files:**
- Create: `src/pyflowcharts/frontends/__init__.py`, `src/pyflowcharts/frontends/python_ast/__init__.py`, `.../python_ast/frontend.py`, `.../python_ast/cfg.py`
- Create: `tests/conftest.py`
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `pyflowcharts.ir`, `pyflowcharts.labels.shorten`.
- Produces (in `pyflowcharts.frontends`):
  - `class SourceError(Exception)`: `__init__(self, path: str, message: str, line: int | None = None)`. `str()` is `f"{path}:{line}: error: {message}"`, or `f"{path}: error: {message}"` when `line` is None. Attributes `path`, `line`, `message`.
  - `class UnsupportedLanguageError(SourceError)`
  - `class Frontend(Protocol)`: `language: str`, `extensions: tuple[str, ...]`, `parse(self, source: bytes, path: str, options: ChartOptions) -> Document`
  - `frontend_for_path(path: Path) -> Frontend`: matches on lower-cased suffix and raises `UnsupportedLanguageError(str(path), "unsupported file type '.js'")` otherwise. The registry is a module-level tuple, `(PythonFrontend(),)`.
- Produces (in `pyflowcharts.frontends.python_ast`): `PythonFrontend` with `language = "python"`, `extensions = (".py",)`.
- Produces (in `cfg.py`, used by Tasks 4–6):
  - `Frontier = list[tuple[str, str | None]]`: pending `(node_id, outgoing_edge_label)` pairs.
  - `class CfgBuilder`: `__init__(self, qualname: str, options: ChartOptions)`, `build(self, func: ast.FunctionDef | ast.AsyncFunctionDef, start_label: str) -> tuple[list[Node], list[Edge]]`
  - Internals that later tasks extend: `_block(self, stmts: list[ast.stmt], frontier: Frontier) -> Frontier`, `_stmt(self, stmt: ast.stmt, frontier: Frontier) -> Frontier` (dispatches with `match stmt:`), `_add_node(self, stmt: ast.stmt | ast.excepthandler | None, kind: NodeKind, label: str, suffix: str = "") -> str`. The ID is `{qualname}#L{line}C{col}{suffix}{self._copy_suffix}`, where `self._copy_suffix` (initially `""`) is used by Task 6 to keep duplicated `finally` bodies unique. A non-empty `suffix` marks a synthetic node and gives it `location=None`., `_connect(self, frontier: Frontier, target_id: str) -> None` (adds one `Edge` per frontier entry, carrying its label).
  - `start_label_for(func, options: ChartOptions) -> str`: a module function in `frontend.py` that `CfgBuilder` also uses for nested-def nodes (Task 6).

**CFG algorithm (applies to Tasks 3–6).** `build` creates `#start` (kind START, location = the def's location) and `#end` (kind END, label `"end"`, location `None`). It runs `_block(func.body, [(start_id, None)])` and connects the resulting frontier to `#end`. `_stmt` returns the new frontier. A statement that ends the path (`return`, `raise`, `break`, `continue`) returns `[]`. When the frontier is empty, later statements still get nodes, just with no incoming edges. Node IDs come from `stmt.lineno`/`stmt.col_offset`. Nodes and edges are appended in creation order, which keeps output deterministic.

Task 3 handles these statements:
- Skipped (return the frontier unchanged): `ast.Pass`, `ast.Global`, `ast.Nonlocal`, an `ast.Expr` whose value is `Constant(Ellipsis)`, and a string `ast.Expr` when it's the first statement of the function body (docstring).
- `ast.Assign`/`ast.AugAssign`/`ast.AnnAssign`: skipped unless `options.show_variables` is set or the value contains an `ast.Call` (`any(isinstance(n, ast.Call) for n in ast.walk(value))`). `AnnAssign` without a value counts as no call.
- `ast.Return`: RETURN node labelled `return <expr>` (or `return` when there's no value or `show_returns` is off). Connect it to `#end` and return `[]`.
- `ast.Raise`: RAISE node labelled with its source. Connect it to `#end` and return `[]`.
- Anything else: PROCESS node labelled `shorten(ast.unparse(stmt), max_label_length)`. Tasks 4–6 add specific cases in front of this fallback.

All labels go through `shorten(..., options.max_label_length)`.

**Discovery (in `frontend.py`).** Parse with `ast.parse(source, filename=path)`, passing bytes so coding cookies work. Then **validate** with `compile(tree, path, "exec", dont_inherit=True)` inside `warnings.catch_warnings()` + `warnings.simplefilter("ignore")`. `ast.parse` accepts compiler-only errors such as `break` outside a loop or `nonlocal` after an assignment, and the CFG builder relies on them being rejected. Ignoring warnings silences, for example, Python 3.14's `SyntaxWarning` for `continue` in `finally`. The compiled code is discarded and never executed. Convert `SyntaxError` (from either call) to `SourceError(path, e.msg, e.lineno)` and `ValueError` to `SourceError(path, str(e))`. Walk the tree with a qualname stack: `ClassDef` pushes its name, function defs emit a chart and then push their name. Recurse into every statement body, including `if`/`try` at module level. Charts appear in source order, depth-first. If a qualname has already been emitted, the later one becomes `f"{qualname}@L{lineno}"`. Nested functions use their parent's *final* qualname as the prefix.

**Signatures.** `Parameter.annotation`/`default` are `ast.unparse` of the node, or `None`. Defaults align right-to-left across `posonlyargs + args`. `kw_defaults` entries may be `None`. `start_label_for`:
- with parameters shown: `f"{'async ' if is_async else ''}def {name}({ast.unparse(func.args)})"` plus `f" -> {ast.unparse(func.returns)}"` when annotated
- with parameters hidden: `def {name}(...)`, with the `async ` prefix but no return annotation

- [ ] **Step 1: Write `tests/conftest.py` helpers**

```python
def chart_of(src: str, qualname: str = "f", **opts) -> FunctionChart:
    doc = PythonFrontend().parse(textwrap.dedent(src).encode(), "t.py", ChartOptions(**opts))
    return next(c for c in doc.functions if c.qualname == qualname)

def flow(chart: FunctionChart) -> set[tuple[str, str, str | None]]:
    label = {n.id: n.label for n in chart.nodes}
    return {(label[e.source], label[e.target], e.label) for e in chart.edges}
```

- [ ] **Step 2: Write failing tests in `tests/test_frontend.py`**

```python
def test_sequential_body_and_implicit_end():
    c = chart_of("""
        def f(a, b=1):
            print(a)
            g(b)
    """)
    assert flow(c) == {("def f(a, b=1)", "print(a)", None), ("print(a)", "g(b)", None),
                       ("g(b)", "end", None)}
    assert c.nodes[0].id == "f#start" and c.nodes[0].kind is NodeKind.START

def test_return_and_raise_end_the_path():
    c = chart_of("""
        def f(x):
            log(x)
            return x + 1
    """)
    assert ("return x + 1", "end", None) in flow(c)
    r = chart_of("def f():\n    raise ValueError('no')\n")
    assert flow(r) == {("def f()", "raise ValueError('no')", None), ("raise ValueError('no')", "end", None)}
    assert r.nodes[-1].kind is NodeKind.RAISE

def test_signature_recorded():
    c = chart_of("def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool: ...",
                 max_label_length=200)
    P, K = Parameter, ParamKind
    assert c.parameters == [P("a", "int", None, K.POSITIONAL_ONLY), P("b", None, "2", K.POSITIONAL_OR_KEYWORD),
        P("args", None, None, K.VAR_POSITIONAL), P("c", None, None, K.KEYWORD_ONLY),
        P("d", "str", "'x'", K.KEYWORD_ONLY), P("kw", None, None, K.VAR_KEYWORD)]
    assert c.returns == "bool"
    assert c.nodes[0].label == "def f(a: int, /, b=2, *args, c, d: str='x', **kw) -> bool"

VARS = """
    def f(xs):
        n = 0
        total = sum(xs)
        n += 1
        return total
"""

def test_variables_hidden_unless_call():
    labels = {n.label for n in chart_of(VARS).nodes}
    assert "total = sum(xs)" in labels and not {"n = 0", "n += 1"} & labels

def test_variables_shown_with_option():
    assert {"n = 0", "n += 1"} <= {n.label for n in chart_of(VARS, show_variables=True).nodes}

def test_hidden_parameters_and_returns():
    labels = {n.label for n in chart_of(VARS, show_parameters=False, show_returns=False).nodes}
    assert {"def f(...)", "return"} <= labels

def test_qualnames_and_duplicates():
    doc = PythonFrontend().parse(textwrap.dedent("""
        def top(): pass
        class A:
            def m(self):
                def inner(): pass
            @property
            def x(self): return 1
            @x.setter
            def x(self, v): pass
        async def co(): pass
    """).encode(), "t.py", ChartOptions())
    assert [c.qualname for c in doc.functions] == ["top", "A.m", "A.m.inner", "A.x", "A.x@L9", "co"]
    co = doc.functions[-1]
    assert co.is_async and co.nodes[0].label == "async def co()"
    assert doc.functions[4].nodes[0].id == "A.x@L9#start"

def test_empty_bodies():
    for body in ['"""doc"""', "...", "pass"]:
        assert flow(chart_of(f"def f():\n    {body}\n")) == {("def f()", "end", None)}

def test_unreachable_code_kept():
    c = chart_of("def f():\n    return 1\n    print('dead')\n")
    dead = next(n for n in c.nodes if n.label == "print('dead')")
    assert all(e.target != dead.id for e in c.edges)
    assert ("return 1", "end", None) in flow(c)

def test_long_labels_truncated():
    c = chart_of(f"def f():\n    g({'a' * 100})\n", max_label_length=20)
    assert c.nodes[2].label == "g(" + "a" * 17 + "…"  # nodes[0]=start, nodes[1]=end

def test_source_errors():
    with pytest.raises(SourceError) as e:
        PythonFrontend().parse(b"def f(:\n", "bad.py", ChartOptions())
    assert e.value.line == 1 and str(e.value).startswith("bad.py:1: error:")
    with pytest.raises(SourceError):
        PythonFrontend().parse(b"x = 1\x00\n", "nul.py", ChartOptions())

def test_compiler_only_syntax_errors():  # ast.parse accepts these; compile() must reject them
    for src, line in [(b"def f():\n    break\n", 2), (b"def f():\n    continue\n", 2),
                      (b"def f():\n    x = 1\n    nonlocal x\n", 3)]:
        with pytest.raises(SourceError) as e:
            PythonFrontend().parse(src, "loop.py", ChartOptions())
        assert e.value.line == line

def test_coding_cookie():
    src = b"# -*- coding: latin-1 -*-\ndef f():\n    print('\xe9')\n"
    doc = PythonFrontend().parse(src, "l1.py", ChartOptions())
    assert doc.functions[0].nodes[2].label == "print('é')"

def test_registry():
    assert isinstance(frontend_for_path(Path("x.PY")), PythonFrontend)
    with pytest.raises(UnsupportedLanguageError):
        frontend_for_path(Path("x.js"))

def test_document_metadata():
    doc = PythonFrontend().parse(b"", "empty.py", ChartOptions())
    assert (doc.source, doc.language, doc.functions, doc.schema_version) == ("empty.py", "python", [], 1)
```

- [ ] **Step 3: Run** `uv run pytest tests/test_frontend.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 4: Implement** the `frontends` package, `PythonFrontend`, discovery, signatures, `start_label_for` and `CfgBuilder` as specified above.
- [ ] **Step 5: Run** `uv run pytest -v && uv run ruff check`. Expected: all PASS.
- [ ] **Step 6: Commit** `feat: Python frontend with function discovery, signatures and sequential CFG`

---

### Task 4: Branches (`if`/`elif`/`else`, `match`)

**Files:**
- Modify: `src/pyflowcharts/frontends/python_ast/cfg.py` (new `_stmt` cases)
- Test: `tests/test_cfg_branches.py`

**Interfaces:**
- Consumes: `CfgBuilder._block/_stmt/_add_node/_connect`, `chart_of`, `flow` (Task 3).
- Produces: no new public names.

Rules:
- `ast.If`: DECISION node `if <test>`. Body from `[(id, "True")]`. If there's an orelse, build it from `[(id, "False")]`, otherwise the frontier is `[(id, "False")]`. Return the union (body first).
- `ast.Match`: DECISION node `match <subject>`. Each case body is built from `[(id, label)]` with label `f"case {unparse(pattern)}"` plus `f" if {unparse(guard)}"`. Add `(id, "no match")` unless the last case has `guard is None` and its pattern is `ast.MatchAs` with `pattern is None`.

- [ ] **Step 1: Write failing tests**

```python
def test_if_elif_else():
    c = chart_of("""
        def f(x):
            if x > 0:
                a()
            elif x < 0:
                b()
            else:
                c()
            d()
    """)
    assert flow(c) == {("def f(x)", "if x > 0", None), ("if x > 0", "a()", "True"),
        ("if x > 0", "if x < 0", "False"), ("if x < 0", "b()", "True"), ("if x < 0", "c()", "False"),
        ("a()", "d()", None), ("b()", "d()", None), ("c()", "d()", None), ("d()", "end", None)}
    assert next(n for n in c.nodes if n.label == "if x > 0").kind is NodeKind.DECISION

def test_if_without_else_falls_through():
    c = chart_of("def f(x):\n    if x:\n        a()\n    b()\n")
    assert {("if x", "a()", "True"), ("if x", "b()", "False"), ("a()", "b()", None)} <= flow(c)

def test_if_with_pass_body():
    c = chart_of("def f(x):\n    if x:\n        pass\n    b()\n")
    assert {("if x", "b()", "True"), ("if x", "b()", "False")} <= flow(c)

def test_if_branch_returning():
    c = chart_of("def f(x):\n    if x:\n        return 1\n    b()\n")
    assert ("return 1", "b()", None) not in flow(c)
    assert {("return 1", "end", None), ("if x", "b()", "False")} <= flow(c)

def test_match_without_wildcard():
    c = chart_of("""
        def f(cmd):
            match cmd:
                case "go":
                    go()
                case [x, *_] if x:
                    other(x)
            done()
    """)
    assert {("match cmd", "go()", "case 'go'"), ("match cmd", "other(x)", "case [x, *_] if x"),
            ("match cmd", "done()", "no match"), ("go()", "done()", None),
            ("other(x)", "done()", None)} <= flow(c)

def test_match_with_wildcard_has_no_fallthrough():
    c = chart_of("def f(v):\n    match v:\n        case 1:\n            a()\n        case _:\n            b()\n")
    assert all(lbl != "no match" for _, _, lbl in flow(c))
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cfg_branches.py -v`. Expected: FAIL. With the Task 3 fallback, `if` shows up as one process node.
- [ ] **Step 3: Implement** the `If` and `Match` cases in `_stmt`.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: CFG support for if/elif/else and match`

---

### Task 5: Loops (`for`, `while`, `break`, `continue`, loop `else`)

**Files:**
- Modify: `src/pyflowcharts/frontends/python_ast/cfg.py`
- Test: `tests/test_cfg_loops.py`

**Interfaces:**
- Consumes: Task 3 internals.
- Produces: internal `_LoopContext(loop_id: str, breaks: Frontier)`, a stack `self._loops: list[_LoopContext]`, and the transfer routers `_break(self, frontier: Frontier) -> None` / `_continue(self, frontier: Frontier) -> None` (extended in Task 6).

Rules:
- `ast.For`/`ast.AsyncFor`: LOOP node `[async ]for <target> in <iter>`. Enter label `"next"`, exit label `"done"`.
- `ast.While`: LOOP node `while <test>`. Enter label `"True"`, exit label `"False"`. When `test` is an `ast.Constant` with a truthy value, there's no exit entry (only breaks leave).
- Algorithm: connect the frontier to the loop node and push a context. Build the body from `[(loop, enter)]`, connect the body's frontier back to the loop node, then pop. `exit = [(loop, exit_label)]` (unless while-constant-true). If there's an orelse, `exit = _block(orelse, exit)`. Return `exit + ctx.breaks`.
- `ast.Break`: call `self._break(frontier)` and return `[]`. `ast.Continue`: call `self._continue(frontier)` and return `[]`. Neither creates a node. In this task, `_break` appends to `self._loops[-1].breaks` and `_continue` connects to `self._loops[-1].loop_id`. Thanks to the `compile()` validation from Task 3, `self._loops` is never empty here. If it is anyway, raise `RuntimeError("internal: break/continue outside loop")` rather than letting an `IndexError` escape.

- [ ] **Step 1: Write failing tests**

```python
def test_for_with_break_continue_else():
    c = chart_of("""
        def f(xs):
            for x in xs:
                if x:
                    continue
                if x is None:
                    break
                work(x)
            else:
                nobreak()
            after()
    """)
    assert {("for x in xs", "if x", "next"), ("if x", "for x in xs", "True"),
            ("if x", "if x is None", "False"), ("if x is None", "after()", "True"),
            ("if x is None", "work(x)", "False"), ("work(x)", "for x in xs", None),
            ("for x in xs", "nobreak()", "done"), ("nobreak()", "after()", None)} <= flow(c)
    assert ("if x is None", "nobreak()", "True") not in flow(c)
    assert next(n for n in c.nodes if n.label == "for x in xs").kind is NodeKind.LOOP

def test_while():
    c = chart_of("def f(n):\n    while n > 0:\n        n = step(n)\n    return n\n")
    assert flow(c) == {("def f(n)", "while n > 0", None), ("while n > 0", "n = step(n)", "True"),
        ("n = step(n)", "while n > 0", None), ("while n > 0", "return n", "False"),
        ("return n", "end", None)}

def test_while_true_exits_only_via_break():
    c = chart_of("def f():\n    while True:\n        if poll():\n            break\n    done()\n")
    assert not any(s == "while True" and t == "done()" for s, t, _ in flow(c))
    assert {("if poll()", "done()", "True"), ("if poll()", "while True", "False")} <= flow(c)

def test_nested_loops_break_inner_only():
    c = chart_of("def f(A, B):\n    for a in A:\n        for b in B:\n            break\n        x()\n")
    assert {("for b in B", "x()", "next"), ("for b in B", "x()", "done"),
            ("x()", "for a in A", None)} <= flow(c)

def test_async_for_label():
    c = chart_of("async def f(s):\n    async for x in s:\n        use(x)\n")
    assert "async for x in s" in {n.label for n in c.nodes}
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cfg_loops.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the loop, `Break` and `Continue` cases.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: CFG support for loops, break, continue and loop else`

---

### Task 6: `try`, `with`, nested definitions, and the sample fixture

**Files:**
- Modify: `src/pyflowcharts/frontends/python_ast/cfg.py`
- Create: `tests/fixtures/sample.py`
- Test: `tests/test_cfg_try_with.py`

**Interfaces:**
- Consumes: Task 3 internals, `start_label_for` (Task 3).
- Produces: `tests/fixtures/sample.py`, used by Tasks 7–9.

Rules:
- `ast.Try`/`ast.TryStar`: PROCESS node `"try"`. The body is built from `[(try, None)]`. Each handler gets a PROCESS node (id from the handler's own position) labelled `except[*] <type>[ as <name>]`, or `except` when bare. Connect `(try, "exception")` to the handler node, then build the handler body from `[(handler, None)]`. `orelse` is built from the body's frontier. `normal = else_or_body_frontier + all handler frontiers`. Without `finalbody`, return `normal`.
- **`finally` and loop transfers.** A `break`/`continue` inside a `try … finally` must run the finally body before it reaches the loop exit or head, and the finally body can override the transfer (for example with its own `continue`/`break`/`return`). Mechanism:
  - State: `_FinallyContext(loop_depth: int, breaks: Frontier, continues: Frontier)` and a stack `self._finally: list[_FinallyContext]`.
  - Routing: `_break`/`_continue` first check whether `self._finally` is non-empty and `self._finally[-1].loop_depth == len(self._loops)`. That means no loop was entered since that `try` began, so the transfer must pass through its finally. In that case they append the frontier to the context's `breaks`/`continues`. Otherwise they behave as in Task 5.
  - For a `try` with `finalbody`: push `_FinallyContext(len(self._loops), [], [])` before building the body, handlers and `orelse`, and pop it afterwards (the finally body itself is built outside the context). Then:
    1. **Normal copy** (always built): a synthetic PROCESS node `"finally"` (suffix `~finally`), connected from `normal`. `result = _block(finalbody, [(fin, None)])`.
    2. **One copy per pending transfer kind**, only when the context's list is non-empty, in the order `break` then `continue`: append `f"~{kind}"` to `self._copy_suffix`, add a synthetic node labelled `f"finally ({kind})"` (suffix `~finally`) connected from the pending frontier, build `out = _block(finalbody, [(node, None)])`, call `self._break(out)` or `self._continue(out)` so outer finally blocks and loops route it in turn, then restore `self._copy_suffix`.
    3. Return `result`.
  - Because the finally body is duplicated per path, a `finally` that ends in `continue` sends its break copy back to the loop head, which leaves code after a `while True` unreachable. `return`/`raise` inside `try … finally` still go straight to `end` (a documented simplification).
- `ast.With`/`ast.AsyncWith`: PROCESS node `[async ]with ` + `", ".join(ast.unparse(i) for i in items)`, then the body.
- Nested `FunctionDef`/`AsyncFunctionDef`: PROCESS node labelled `start_label_for(stmt, options)`. `ClassDef`: PROCESS node `class <name>`. Discovery from Task 3 already emits the nested chart.
- `tests/fixtures/sample.py` (about 40 lines) should exercise every construct: a class with a method containing `for`+`if`+`break`, a `@property` with a setter, a function with `try/except/else/finally`, a loop whose body has `try` with `break` and `continue` plus a `finally` (so duplicated finally copies appear in the ID-uniqueness check), a `match`, a `with`, a nested function, an `async def`, and a string label containing `"` and `\n`.

- [ ] **Step 1: Write failing tests**

```python
def test_try_except_else_finally():
    c = chart_of("""
        def f(path):
            try:
                data = load(path)
            except (OSError, ValueError) as e:
                log(e)
                return None
            except Exception:
                raise
            else:
                use(data)
            finally:
                cleanup()
            return data
    """)
    assert flow(c) == {("def f(path)", "try", None), ("try", "data = load(path)", None),
        ("try", "except (OSError, ValueError) as e", "exception"), ("try", "except Exception", "exception"),
        ("except (OSError, ValueError) as e", "log(e)", None), ("log(e)", "return None", None),
        ("return None", "end", None), ("except Exception", "raise", None), ("raise", "end", None),
        ("data = load(path)", "use(data)", None), ("use(data)", "finally", None),
        ("finally", "cleanup()", None), ("cleanup()", "return data", None), ("return data", "end", None)}
    assert any(n.id.endswith("~finally") for n in c.nodes)

def succ(chart, node_id):
    return {e.target for e in chart.edges if e.source == node_id}

def node(chart, label):
    return next(n.id for n in chart.nodes if n.label == label)

def test_break_runs_finally_before_leaving_loop():
    c = chart_of("""
        def f(xs):
            for x in xs:
                try:
                    if x:
                        break
                    work(x)
                finally:
                    cleanup()
            after()
    """)
    assert {("if x", "finally (break)", "True"), ("work(x)", "finally", None),
            ("for x in xs", "after()", "done")} <= flow(c)
    (brk_cleanup,) = succ(c, node(c, "finally (break)"))
    (norm_cleanup,) = succ(c, node(c, "finally"))
    assert succ(c, brk_cleanup) == {node(c, "after()")}
    assert succ(c, norm_cleanup) == {node(c, "for x in xs")}
    assert brk_cleanup.endswith("~break") and brk_cleanup != norm_cleanup

def test_finally_can_override_break():
    c = chart_of("""
        def f():
            while True:
                try:
                    break
                finally:
                    continue
            after()
    """)
    assert {("try", "finally (break)", None), ("finally (break)", "while True", None)} <= flow(c)
    assert node(c, "after()") not in {e.target for e in c.edges}  # loop never exits

def test_continue_runs_finally():
    c = chart_of("""
        def f(xs):
            for x in xs:
                try:
                    continue
                finally:
                    log(x)
    """)
    (cont_log,) = succ(c, node(c, "finally (continue)"))
    assert succ(c, cont_log) == {node(c, "for x in xs")}

def test_with_statement():
    c = chart_of("def f(p):\n    with open(p) as fh, lock:\n        read(fh)\n")
    assert flow(c) == {("def f(p)", "with open(p) as fh, lock", None),
                       ("with open(p) as fh, lock", "read(fh)", None), ("read(fh)", "end", None)}

def test_nested_def_is_a_node_and_its_own_chart():
    src = "def outer():\n    def inner(x):\n        return x\n    return inner\n"
    assert flow(chart_of(src, "outer")) == {("def outer()", "def inner(x)", None),
        ("def inner(x)", "return inner", None), ("return inner", "end", None)}
    assert flow(chart_of(src, "outer.inner")) == {("def inner(x)", "return x", None), ("return x", "end", None)}

def test_sample_fixture_graph_integrity():
    path = Path(__file__).parent / "fixtures" / "sample.py"
    doc = PythonFrontend().parse(path.read_bytes(), str(path), ChartOptions())
    assert len({c.qualname for c in doc.functions}) == len(doc.functions)
    for chart in doc.functions:
        ids = [n.id for n in chart.nodes]
        assert len(ids) == len(set(ids)), chart.qualname
        assert not any(":" in i for i in ids)
        assert all(e.source in ids and e.target in ids for e in chart.edges)
        assert all(n.kind is not NodeKind.PROCESS or "\n" not in n.label for n in chart.nodes)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cfg_try_with.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the cases and write the fixture.
- [ ] **Step 4: Run** `uv run pytest -v && uv run ruff check`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: CFG support for try, with and nested definitions`

---

### Task 7: DOT / SVG / PNG backend

**Files:**
- Create: `src/pyflowcharts/backends/__init__.py`, `src/pyflowcharts/backends/dot.py`
- Test: `tests/test_dot.py`

**Interfaces:**
- Consumes: `FunctionChart`, `NodeKind` (Task 1). Tests use `chart_of` and the fixture.
- Produces:
  - `SHAPES: dict[NodeKind, str]` = `{START: "oval", END: "oval", PROCESS: "box", DECISION: "diamond", LOOP: "hexagon", RETURN: "parallelogram", RAISE: "octagon"}`
  - `to_digraph(chart: FunctionChart) -> graphviz.Digraph`: graph name = qualname, `graph_attr={"rankdir": "TB"}`, `node_attr={"fontname": "Helvetica"}`, `edge_attr={"fontname": "Helvetica"}`. Each node gets `label=graphviz.escape(node.label)` and `shape=SHAPES[kind]`, plus `tooltip=f"line {line}"` when it has a location. Each edge passes `label=graphviz.escape(label)` only when the label is not None.
  - `to_dot(chart: FunctionChart) -> str`: returns `to_digraph(chart).source`.
  - `render(chart: FunctionChart, fmt: Literal["svg", "png"]) -> bytes`: calls `to_digraph(chart).pipe(format=fmt)`. `graphviz.ExecutableNotFound` propagates to the caller.

- [ ] **Step 1: Write failing tests**

```python
needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
IF_SRC = "def f(x):\n    if x > 0:\n        return 1\n    g()\n"

def line_for(src: str, node_id: str) -> str:
    return next(l for l in src.splitlines() if l.strip().startswith(f'"{node_id}" ['))

def test_nodes_have_shapes_and_tooltips():
    c = chart_of(IF_SRC); src = to_dot(c)
    for n in c.nodes:
        assert f"shape={SHAPES[n.kind]}" in line_for(src, n.id)
    assert 'tooltip="line 2"' in line_for(src, next(n.id for n in c.nodes if n.label == "if x > 0"))

def test_edge_labels():
    src = to_dot(chart_of(IF_SRC))
    assert "label=True" in src and "label=False" in src

def test_label_escaping():
    src = to_dot(chart_of('def f():\n    print("a\\nb", "it\'s")\n'))
    assert r"""print('a\\nb', \"it's\")""" in src

def test_deterministic():
    assert to_dot(chart_of(IF_SRC)) == to_dot(chart_of(IF_SRC))

@needs_dot
def test_render_svg_and_png():
    c = chart_of(IF_SRC)
    assert b"<svg" in render(c, "svg")
    assert render(c, "png")[:8] == b"\x89PNG\r\n\x1a\n"

@needs_dot
def test_renders_whole_fixture():  # every fixture chart is valid DOT
    path = Path(__file__).parent / "fixtures" / "sample.py"
    for chart in PythonFrontend().parse(path.read_bytes(), str(path), ChartOptions()).functions:
        assert b"<svg" in render(chart, "svg")
```

- [ ] **Step 2: Run** `uv run pytest tests/test_dot.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `dot.py`. If the escaping assertion doesn't match the exact quoting the graphviz package emits, inspect `to_dot` output and fix the *implementation*, not the requirement. The requirement is that the label's backslash stays a literal backslash and the quotes don't terminate the DOT string.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: Graphviz backend for DOT, SVG and PNG`

---

### Task 8: Mermaid backend

**Files:**
- Create: `src/pyflowcharts/backends/mermaid.py`
- Test: `tests/test_mermaid.py`

**Interfaces:**
- Consumes: `FunctionChart`, `NodeKind`.
- Produces: `to_mermaid(chart: FunctionChart) -> str`. The first line is `flowchart TD`, followed by one 4-space-indented line per node and then one per edge, with a trailing newline. Mermaid IDs are `n0…nK` by position in `chart.nodes`. Shape templates (with `{t}` the escaped label): START/END `(["{t}"])`, PROCESS `["{t}"]`, DECISION `{"{t}"}`, LOOP `{{"{t}"}}`, RETURN `[/"{t}"/]`, RAISE `>"{t}"]`. Edges are `nA --> nB` or `nA -->|"{label}"| nB`. Escaping applies to node and edge labels and **must replace `#` first**, so literal source text like `#34;` isn't read as an entity: `#`→`#35;`, then `"`→`#34;`, `<`→`#60;`, `>`→`#62;`.

- [ ] **Step 1: Write failing tests**

```python
def test_mermaid_structure():
    out = to_mermaid(chart_of("def f(x):\n    if x > 0:\n        return 1\n    g()\n"))
    lines = out.splitlines()
    assert lines[0] == "flowchart TD" and out.endswith("\n")
    assert '    n0(["def f(x)"])' in lines
    assert '    n2{"if x #62; 0"}' in lines
    assert '    n2 -->|"True"| n3' in lines
    assert "    n0 --> n2" in lines

def test_mermaid_escaping():
    out = to_mermaid(chart_of("def f():\n    print(\"it's\")\n"))
    assert '["print(#34;it\'s#34;)"]' in out

def test_mermaid_escapes_literal_hash():  # literal "#34;" in source must stay literal
    out = to_mermaid(chart_of("def f():\n    print('#34; x#1')\n"))
    assert "[\"print('#35;34; x#35;1')\"]" in out

def test_mermaid_shapes():
    out = to_mermaid(chart_of("def f(xs):\n    for x in xs:\n        raise E(x)\n"))
    assert '{{"for x in xs"}}' in out and '>"raise E(x)"]' in out
```

Node order: `n0` = start and `n1` = end, because `build` creates both before the body. The body nodes follow in creation order.

- [ ] **Step 2: Run** `uv run pytest tests/test_mermaid.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `to_mermaid`.
- [ ] **Step 4: Run** `uv run pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: Mermaid backend`

---

### Task 9: CLI, README, end-to-end tests

**Files:**
- Create: `src/pyflowcharts/cli.py`
- Modify: `README.md` (already exists; keep anything the user has written and add the sections below)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `frontend_for_path`, `SourceError` (Task 3), `to_json`/`from_json` (Task 2), `to_dot`/`render` (Task 7), `to_mermaid` (Task 8), `ChartOptions` (Task 1).
- Produces: `main(argv: list[str] | None = None) -> int`. `cli.py` imports `render` by name (`from pyflowcharts.backends.dot import render, to_dot`) so tests can monkeypatch `pyflowcharts.cli.render`.

Behaviour (from the spec's "Output layout & CLI" and "Errors" sections):
- Arguments: `files` (nargs `+`, `Path`), `-o/--output` (default `flowcharts`), `-f/--format` (nargs `+`, choices `json dot svg png mermaid`, default `["svg", "json"]`), `--variables`, `--no-parameters`, `--no-returns`, `--function` (`nargs="+"`, `action="extend"`, `metavar="QUALNAME"`, so that both `--function a b` and `--function a --function b` work; because `files` also takes `nargs="+"`, the README shows files first), `--max-label` (int, default 60).
- Before writing anything, check that no two input paths share `path.stem`. Otherwise print `error: output name collision: a/utils.py and b/utils.py both map to 'utils'` and return 1.
- Per file: read the bytes (a missing file becomes `SourceError(path, "no such file")`), pick the frontend and parse. On `SourceError`, print `str(err)` to stderr, remember the failure and continue with the next file.
- `--function`: keep the charts whose qualname is listed. If a name matches nothing in *any* file, print `error: unknown function 'X'; available: a, b, …` and return 1.
- Writing: create `OUTDIR`. Only the selected formats are written. When `json` is selected, write `OUTDIR/<stem>.json` first. Per-function files go to `OUTDIR/<stem>/<qualname>.{dot,svg,png,mmd}`. If a file has no functions, print `warning: <path>: no functions found`, and write the (empty) JSON only if `json` is selected.
- `graphviz.ExecutableNotFound` while rendering: print `error: Graphviz 'dot' executable not found; install Graphviz (e.g. 'sudo apt install graphviz') or use --format json dot mermaid`, skip further svg/png output, and finish with exit 2 (unless an exit-1 failure happened, in which case 1 wins).
- Return 0 when everything succeeded.

- [ ] **Step 1: Write failing tests** (use `tmp_path`, `capsys` and `monkeypatch`, and write small source files into `tmp_path`)

```python
def test_default_formats(tmp_path):
    src = write(tmp_path, "mod.py", "def f(x):\n    return x\n")
    assert main([str(src), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out/mod.json").exists() and (tmp_path / "out/mod/f.svg").exists()  # needs_dot

def test_text_formats(tmp_path):
    src = write(tmp_path, "mod.py", "class A:\n    def m(self):\n        pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "dot", "mermaid"]) == 0
    assert {p.name for p in (tmp_path / "o/mod").iterdir()} == {"A.m.dot", "A.m.mmd"}

def test_options_reach_frontend(tmp_path):
    src = write(tmp_path, "m.py", "def f(a):\n    n = 1\n    return n\n")
    main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--variables", "--no-parameters", "--no-returns"])
    labels = {n.label for n in from_json((tmp_path / "o/m.json").read_text()).functions[0].nodes}
    assert {"n = 1", "def f(...)", "return"} <= labels

def test_function_filter_and_unknown(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def a(): pass\ndef b(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "b"]) == 0
    assert [c.qualname for c in from_json((tmp_path / "o/m.json").read_text()).functions] == ["b"]
    assert main([str(src), "-o", str(tmp_path / "o2"), "--function", "zzz"]) == 1
    assert "available: a, b" in capsys.readouterr().err

def test_function_accepts_several_names(tmp_path):
    src = write(tmp_path, "m.py", "def a(): pass\ndef b(): pass\ndef c(): pass\n")
    for i, flags in enumerate([["--function", "a", "b"], ["--function", "a", "--function", "b"]]):
        out = tmp_path / f"o{i}"
        assert main([str(src), "-o", str(out), "-f", "json", *flags]) == 0
        assert [c.qualname for c in from_json((out / "m.json").read_text()).functions] == ["a", "b"]

def test_json_only_when_requested(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n"); empty = write(tmp_path, "e.py", "X = 1\n")
    assert main([str(src), str(empty), "-o", str(tmp_path / "o"), "-f", "mermaid"]) == 0
    assert (tmp_path / "o/m/f.mmd").exists()
    assert not list((tmp_path / "o").glob("*.json"))

def test_bad_file_does_not_stop_others(tmp_path, capsys):
    bad = write(tmp_path, "bad.py", "def f(:\n"); good = write(tmp_path, "good.py", "def g(): pass\n")
    assert main([str(bad), str(good), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    assert f"{bad}:1: error:" in capsys.readouterr().err
    assert (tmp_path / "o/good.json").exists()

def test_missing_and_unsupported_files(tmp_path, capsys):
    js = write(tmp_path, "x.js", "")
    assert main([str(tmp_path / "nope.py"), str(js), "-o", str(tmp_path / "o")]) == 1
    err = capsys.readouterr().err
    assert "no such file" in err and "unsupported file type" in err

def test_stem_collision(tmp_path, capsys):
    a = write(tmp_path / "a", "utils.py", "def f(): pass\n"); b = write(tmp_path / "b", "utils.py", "def g(): pass\n")
    assert main([str(a), str(b), "-o", str(tmp_path / "o")]) == 1
    assert "collision" in capsys.readouterr().err and not (tmp_path / "o").exists()

def test_missing_graphviz(tmp_path, monkeypatch, capsys):
    def boom(*a, **k): raise graphviz.ExecutableNotFound(["dot"])
    monkeypatch.setattr("pyflowcharts.cli.render", boom)
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "svg", "json"]) == 2
    assert "Graphviz" in capsys.readouterr().err and (tmp_path / "o/m.json").exists()

def test_no_functions_warns(tmp_path, capsys):
    src = write(tmp_path, "m.py", "X = 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert "no functions found" in capsys.readouterr().err
    assert from_json((tmp_path / "o/m.json").read_text()).functions == []

@needs_dot
def test_end_to_end_fixture(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample.py"
    assert main([str(fixture), "-o", str(tmp_path), "-f", "json", "dot", "svg", "png", "mermaid"]) == 0
    doc = from_json((tmp_path / "sample.json").read_text())
    assert doc == PythonFrontend().parse(fixture.read_bytes(), str(fixture), ChartOptions())
    for c in doc.functions:
        for ext in ("dot", "svg", "png", "mmd"):
            assert (tmp_path / "sample" / f"{c.qualname}.{ext}").stat().st_size > 0
```

`write(dir, name, text)` is a small helper in the test module: it creates `dir`, writes the file and returns the path. `needs_dot` is the same marker as in Task 7. Also put it on `test_default_formats`.

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `cli.py`.
- [ ] **Step 4: Write `README.md`.** Cover: what the tool does (one paragraph), installation (`uv sync`, plus installing Graphviz with `sudo apt install graphviz` / `brew install graphviz` for SVG/PNG), usage examples (`uv run pyflowcharts mymodule.py`, the `-f json mermaid` and `--variables` variants), the output layout, a short note that the JSON (schema v1) is the stable format meant for external tools, and the known simplifications copied from the spec.
- [ ] **Step 5: Run** `uv run pytest -v && uv run ruff check && uv run pyflowcharts tests/fixtures/sample.py -o /tmp/pfc-demo`. Expected: all tests PASS, and the demo writes `sample.json` plus `sample/*.svg`. Open one SVG and check that it looks right.
- [ ] **Step 6: Commit** `feat: pyflowcharts CLI with multi-format output`
