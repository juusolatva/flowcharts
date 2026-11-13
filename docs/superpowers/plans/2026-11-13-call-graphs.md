# Call Graphs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every chart records its calls (owning node, callee text, candidate targets, resolved target), and each run writes one call graph picture, `OUTDIR/callgraph.<ext>`.

**Architecture:** The Python frontend attaches `CallSite`s (text plus candidate `CallRef`s) to model statements. The `cfg` builder turns them into `Call`s on the nodes it creates. A language-neutral linker (`calls.py`) sets each call's `target` against all documents in the run. `backends/callgraph.py` draws the graph, and the CLI writes it.

**Tech Stack:** Python ≥ 3.12, tree-sitter / tree-sitter-python, graphviz, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-11-13-call-graphs-design.md`. Read it before starting. It is the source of truth for the ownership table, the resolution rules and the messages quoted below.

## Global Constraints

- Use `uv run pytest` and `uv run ruff check` / `uv run ruff format`; never bare `pip`, `python` or `pytest`. Both must pass before every commit.
- Layering:
  - `cfg/`, `calls.py`, `backends/`, `cli.py`, `inputs.py` and `output.py` must not import `ast`, tree-sitter or `frontends/python/`.
  - `cfg/model.py` may import `CallRef` from `ir.py`.
- No new runtime dependencies.
- Output is deterministic: no set iteration in any output order.
- Node IDs never contain `:`.
- `SCHEMA_VERSION = 3`; `from_json` reads 1, 2 and 3.
- Keep modules under ~300 lines. `statements.py` is already 339 lines: put new logic in `frontends/python/calls.py` and add only the call-site plumbing to `statements.py`.
- TDD: each step's failing test comes first. CFG-shape tests assert on `flow(chart)`.
- Conventional Commits, one logical change each, on branch `feat/call-graphs`. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Calls inside f-strings (`print(f"{fmt(x)}")`) are recorded on the statement's node, with `fmt` resolved like any other call. Test in Task 4.
2. `await g()` and `async with open_conn():` record `g` and `open_conn`. Test in Task 4.
3. Nested calls of the same function, `g(g(x))`, give two `Call`s on one node but a single call-graph edge. Tests in Task 4 and Task 7.
4. A call to a function defined later in the file (forward reference) resolves, because statement order is ignored. Test in Task 5.
5. Non-ASCII qualnames (`def größe(): …`) produce valid DOT and Mermaid call graphs. Test in Task 7.

---

### Task 1: IR v3 (`CallRef`, `Call`, `Chart.calls`, `Document.module_name`)

**Files:**
- Modify: `src/pyflowcharts/ir.py`, `src/pyflowcharts/serialize.py`
- Modify tests: `tests/test_serialize.py`, `tests/test_frontend.py` (`test_document_metadata`), `tests/test_python_frontend.py` (schema version)

**Interfaces:**
- Produces (`ir.py`):
  - `SCHEMA_VERSION = 3`.
  - `@dataclass(frozen=True) class CallRef(module: str, qualname: str)`.
  - `@dataclass(frozen=True) class Call(node: str, text: str, candidates: list[CallRef], target: CallRef | None)`.
  - `Chart` gains `calls: list[Call] = field(default_factory=list, kw_only=True)` after `edges`.
  - `Document` gains `module_name: str = ""` after `functions` and before `module`.
- Produces (`serialize.py`): `from_json` accepts versions `(1, 2, 3)`. Versions 1 and 2 are read with `module_name=""` and `calls=[]`.

- [ ] **Step 1: Write failing tests** in `tests/test_serialize.py`:

```python
def test_json_shape(doc):  # update the existing test
    data = json.loads(to_json(doc))
    assert data["schema_version"] == 3
    assert list(data) == ["source", "language", "functions", "module_name", "module", "schema_version"]
    assert list(data["functions"][0]) == ["qualname", "location", "nodes", "edges", "calls",
                                          "name", "is_async", "parameters", "returns"]
    # keep the existing "start" / "positional_or_keyword" kind assertions

def test_round_trip_with_calls(doc):
    f = doc.functions[0]
    f.calls = [Call(node="f#L2C4", text="g", candidates=[CallRef("m", "g"), CallRef("m", "g.__init__")],
                    target=CallRef("m", "g")),
               Call(node="f#L2C4", text="print", candidates=[], target=None)]
    doc.module_name = "pkg.m"
    assert from_json(to_json(doc)) == doc
    assert json.loads(to_json(doc))["functions"][0]["calls"][0] == {
        "node": "f#L2C4", "text": "g",
        "candidates": [{"module": "m", "qualname": "g"}, {"module": "m", "qualname": "g.__init__"}],
        "target": {"module": "m", "qualname": "g"}}

@pytest.mark.parametrize("version", [1, 2])
def test_reads_older_versions(doc, version):
    data = json.loads(to_json(doc))
    data["schema_version"] = version
    del data["module_name"]
    for chart in data["functions"]:
        del chart["calls"]
    if version == 1:
        del data["module"]
    old = from_json(json.dumps(data))
    assert (old.schema_version, old.module_name, old.functions[0].calls) == (version, "", [])
```

  Change the rejection test's `match` to `r"expected 1, 2 or 3"`. In `test_frontend.py` and `test_python_frontend.py`, change the expected schema version to `3`.

- [ ] **Step 2: Run** `uv run pytest tests/test_serialize.py -v`. Expected: FAIL (`Call` / `CallRef` import errors).
- [ ] **Step 3: Implement** the Interfaces. In `serialize.py`:
  - `SUPPORTED_VERSIONS = (1, 2, 3)`, with the message `unsupported schema_version {version!r} (expected 1, 2 or 3)`.
  - Add `_calls(data) -> list[Call]` that reads `data.get("calls", [])`. Candidates and target are built with `CallRef(**…)`, and the target may be `None`.
  - Pass `calls=` in `_module_chart` and `_function_chart`, and `module_name=data.get("module_name", "")` to `Document`.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(ir): add calls and module_name, bump schema to 3`

---

### Task 2: `cfg` carries call sites onto nodes

**Files:**
- Modify: `src/pyflowcharts/cfg/model.py`, `src/pyflowcharts/cfg/builder.py`, `src/pyflowcharts/cfg/finally_.py`, `src/pyflowcharts/frontends/python/frontend.py`, `src/pyflowcharts/frontends/python/module.py`
- Modify tests: `tests/test_builder.py` and `tests/test_python_statements.py` (their `chart` helpers unpack three values and pass `calls=calls`)
- Test: `tests/test_builder.py`

**Interfaces:**
- Consumes: `Call`, `CallRef` (Task 1).
- Produces:
  - `cfg.model.CallSite(text: str, candidates: tuple[CallRef, ...])`, frozen.
  - `calls: tuple[CallSite, ...] = ()` as the last field of `Step`, `Branch`, `Loop`, `Handler` and `Terminal`.
  - `ChartBuilder.add_node(loc, kind, label, suffix="", calls: tuple[CallSite, ...] = ()) -> str`, which appends `Call(node_id, site.text, list(site.candidates), None)` per site to `self.calls: list[Call]`.
  - `build_chart(...) -> tuple[list[Node], list[Edge], list[Call]]`.
  - The frontend's `_chart` and `module_chart` pass `calls=calls` into `FunctionChart` / `Chart`.

- [ ] **Step 1: Write failing tests** in `tests/test_builder.py`. Use the module's `at()` and `LOC` helpers; `S = CallSite`.

```python
def calls_of(body, **opts) -> list[tuple[str, str]]:
    nodes, edges, calls = build_chart("f", "def f()", LOC, body, ChartOptions(**opts))
    label = {n.id: n.label for n in nodes}
    return [(label[c.node], c.text) for c in calls]

def test_step_calls_land_on_its_node():
    body = (Step("x = g(h())", at(2), calls=(S("g", ()), S("h", ()))),)
    assert calls_of(body) == [("x = g(h())", "g"), ("x = g(h())", "h")]

def test_branch_loop_terminal_handler_carry_calls():
    body = (
        Branch("if ok()", at(2), (Arm("True", ()),), "False", calls=(S("ok", ()),)),
        Loop("for r in rows()", at(3), "next", "done", (), (), calls=(S("rows", ()),)),
        Try(at(4), (Step("a()", at(5), calls=(S("a", ()),)),),
            (Handler("except E(e())", at(6), (), calls=(S("e", ()),)),), (), None),
        Terminal(NodeKind.RETURN, "return z()", at(7), calls=(S("z", ()),)),
    )
    assert calls_of(body) == [("if ok()", "ok"), ("for r in rows()", "rows"), ("a()", "a"),
                              ("except E(e())", "e"), ("return z()", "z")]

def test_finally_copies_record_calls_on_each_copy():
    body = (Loop("for x in xs", at(2), "next", "done",
                 (Try(at(3), (Step("a()", at(4)), Break(at(5))), (), (),
                      (Step("cleanup()", at(6), calls=(S("cleanup", ()),)),)),), ()),)
    nodes, _, calls = build_chart("f", "def f()", LOC, body, ChartOptions())
    ids = [c.node for c in calls if c.text == "cleanup"]
    assert len(ids) == len(set(ids)) == 2  # normal path + `finally (break)` copy
    assert all(any(n.id == i for n in nodes) for i in ids)

def test_candidates_are_copied_into_calls():
    ref = CallRef("m", "g")
    _, _, calls = build_chart("f", "def f()", LOC, (Step("g()", at(2), calls=(S("g", (ref,)),)),),
                              ChartOptions())
    assert calls == [Call("f#L2C4", "g", [ref], None)]
```

  Adjust `test_finally_copies_record_calls_on_each_copy` to the actual number of finally copies if the builder draws a different set for this body. The assertion that matters is "one call per copy node, all ids distinct and existing".

- [ ] **Step 2: Run** `uv run pytest tests/test_builder.py -v`. Expected: FAIL (`CallSite` missing, unexpected `calls` keyword).
- [ ] **Step 3: Implement** the Interfaces.
  - `ChartBuilder._step` passes `stmt.calls` to `add_node`, and so do `branch` and `loop`.
  - `finally_.emit_try` passes `handler.calls`.
  - The `try` node and `finally` markers pass none.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(cfg): record call sites as calls on the nodes they belong to`

---

### Task 3: Frontend protocol `key`, module name and package

**Files:**
- Modify: `src/pyflowcharts/frontends/base.py`, `src/pyflowcharts/frontends/python/frontend.py`, `src/pyflowcharts/cli.py` (`_parse_file` passes `item.key`)
- Create: `src/pyflowcharts/frontends/python/calls.py` (only `ModuleInfo` and `module_info` in this task)
- Test: `tests/test_python_calls.py` (new)

**Interfaces:**
- Produces:
  - `Frontend.parse(self, source: bytes, path: str, options: ChartOptions, key: PurePosixPath | None = None) -> ParseResult`. When `key` is `None`, it defaults to `PurePosixPath(PurePath(path).stem)`.
  - `frontends/python/calls.py`:
    - `@dataclass(frozen=True) class ModuleInfo(name: str, package: tuple[str, ...])`.
    - `module_info(key: PurePosixPath) -> ModuleInfo`.
  - `PythonFrontend.parse` sets `Document.module_name = module_info(key).name`.
  - `cli._parse_file(path, options, key)` forwards the key.

- [ ] **Step 1: Write failing tests** in `tests/test_python_calls.py`:

```python
@pytest.mark.parametrize("key, name, package", [
    ("pkg/io/load", "pkg.io.load", ("pkg", "io")),
    ("pkg/io/__init__", "pkg.io", ("pkg", "io")),
    ("pkg/__init__", "pkg", ("pkg",)),
    ("util", "util", ()),
    ("__init__", "", ()),
])
def test_module_info(key, name, package):
    assert module_info(PurePosixPath(key)) == ModuleInfo(name, package)

def test_document_module_name_from_key_and_default():
    fe = PythonFrontend()
    assert fe.parse(b"", "src/pkg/a.py", ChartOptions(), PurePosixPath("pkg/a")).document.module_name == "pkg.a"
    assert fe.parse(b"", "src/pkg/a.py", ChartOptions()).document.module_name == "a"
```

  Add to `tests/test_cli.py`:

```python
def test_json_has_module_name_from_walk(tmp_path):
    write(tmp_path / "src/pkg", "mod.py", "def f(): pass\n")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert from_json((tmp_path / "o/pkg/mod.json").read_text()).module_name == "pkg.mod"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_python_calls.py tests/test_cli.py::test_json_has_module_name_from_walk -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the Interfaces. For `module_info`, `parts = key.parts`:
  - For an `__init__` key: `package = parts[:-1]`, `name = ".".join(package)`.
  - Otherwise: `package = parts[:-1]`, `name = ".".join(parts)`.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(frontends): pass the output key to parse and record the module name`

---

### Task 4: Call extraction and ownership (no resolution yet)

**Files:**
- Modify: `src/pyflowcharts/frontends/python/calls.py`, `src/pyflowcharts/frontends/python/statements.py`, `src/pyflowcharts/frontends/python/frontend.py`, `src/pyflowcharts/frontends/python/module.py`
- Test: `tests/test_python_calls.py`

**Interfaces:**
- Consumes: `CallSite` (Task 2), `ModuleInfo` (Task 3), `Found` (`discovery.py`).
- Produces (`frontends/python/calls.py`):
  - `class Resolver`:
    - `Resolver(root: Node, functions: list[Found], info: ModuleInfo, src: Source)`.
    - `.sites(roots: Sequence[Node], scope: Found | None) -> tuple[CallSite, ...]`. `scope` is the owning chart's function, or `None` for the module chart.
    - In this task, every `CallSite` has `candidates=()`.
  - `call_roots(stmt: Node) -> list[Node]`: the subtrees whose calls a statement node owns. Rows of the spec's ownership table:

    | Statement | Roots |
    |---|---|
    | `if_statement` / `elif_clause` | `condition` |
    | `match_statement` | its subject node(s), then each `case_clause`'s `guard` |
    | `for_statement` | `left`, `right` |
    | `while_statement` | `condition` |
    | `with_statement` | the `with_clause` |
    | `except_clause` / `except_group_clause` | its children except the `block` |
    | `decorated_definition` | its `decorator`s, then the roots of its `definition` |
    | `function_definition` | `type_parameters`, `parameters`, `return_type` (those present) |
    | `class_definition` | the whole node |
    | anything else (expression, assignment, `return`, `raise`, `assert`, `del`, …) | the statement node |

  - `Resolver.sites` walks the roots in pre-order and yields every `call` node. It never descends into the `body` field of a `function_definition`, so method bodies inside a class stay out while method signatures are included.
  - Each site's `text` is `src.source_text(call.child_by_field_name("function"))`.
- `statements._Converter` takes an optional `resolver: Resolver | None` and `scope: Found | None`. Where it builds a `Step`, `Branch`, `Loop`, `Handler` or `Terminal`, it passes `calls=resolver.sites(call_roots(node), scope)`.
  - With no resolver, it passes `()`, so `tests/test_python_statements.py` keeps working.
  - The `decorated_definition` case passes the wrapper's roots to the `def`/`class` `Step`.
  - `convert_body` and `convert_statements` take `resolver` and `scope` keywords, defaulting to `None`.
- `PythonFrontend.parse` builds one `Resolver` per file after `find_functions` and passes it, with the chart's `Found` (or `None` for the module chart), into `convert_body` and `module_chart`.

- [ ] **Step 1: Write failing tests** in `tests/test_python_calls.py`. Helpers:

```python
def doc_of(src, key="t", **opts):
    return PythonFrontend().parse(textwrap.dedent(src).encode(), "t.py", ChartOptions(**opts),
                                  PurePosixPath(key)).document

def owned(chart) -> list[tuple[str, str]]:
    label = {n.id: n.label for n in chart.nodes}
    return [(label[c.node], c.text) for c in chart.calls]

def fn(doc, qualname):
    return next(c for c in doc.functions if c.qualname == qualname)
```

```python
def test_statement_kinds_own_their_calls():
    d = doc_of("""
        def f(xs):
            g(1)
            y = load()
            if ok(y):
                pass
            elif other():
                pass
            for r in rows(xs):
                pass
            while more():
                pass
            with open_(p) as fh:
                pass
            try:
                pass
            except make_exc() as e:
                pass
            match subj():
                case 1 if guard():
                    pass
            return done()
        """)
    assert owned(fn(d, "f")) == [
        ("g(1)", "g"), ("y = load()", "load"), ("if ok(y)", "ok"), ("if other()", "other"),
        ("for r in rows(xs)", "rows"), ("while more()", "more"), ("with open_(p) as fh", "open_"),
        ("except make_exc() as e", "make_exc"), ("match subj()", "subj"), ("match subj()", "guard"),
        ("return done()", "done")]
```

  Adjust the expected labels to the frontend's existing ones (e.g. how `elif` is labelled) after a first run. The `(owner, text)` pairs are what this test pins.

```python
def test_raise_and_nested_calls_preorder():
    d = doc_of("def f():\n    raise Err(msg(a().b()))\n")
    assert [t for _, t in owned(fn(d, "f"))] == ["Err", "msg", "a().b", "a"]

def test_nested_def_signature_on_parent_body_in_child():
    d = doc_of("""
        def outer():
            @deco(arg())
            @bare
            def inner(x=default(), y: ann() = 1) -> ret():
                body()
        """)
    assert [t for _, t in owned(fn(d, "outer"))] == ["deco", "arg", "default", "ann", "ret"]
    assert [t for _, t in owned(fn(d, "outer.inner"))] == ["body"]

def test_class_subtree_on_class_node_method_bodies_in_methods():
    d = doc_of("""
        def outer():
            @cdeco()
            class C(Base(), metaclass=meta()):
                x = a()
                def m(self, y=b()):
                    c()
        """)
    assert [t for _, t in owned(fn(d, "outer"))] == ["cdeco", "Base", "meta", "a", "b"]
    assert [t for _, t in owned(fn(d, "outer.C.m"))] == ["c"]

def test_top_level_definitions_own_calls_only_with_a_module_chart():
    src = "@deco()\ndef f(x=d()): pass\nmain()\n"
    assert [t for _, t in owned(doc_of(src).module)] == ["deco", "d", "main"]
    assert doc_of("@deco()\ndef f(x=d()): pass\n").module is None

def test_lambdas_and_comprehensions_belong_to_the_statement():
    d = doc_of("def f(xs):\n    out = [h(x) for x in xs if keep(x)]\n    k = lambda: z()\n")
    assert owned(fn(d, "f")) == [("out = [h(x) for x in xs if keep(x)]", "h"),
                                 ("out = [h(x) for x in xs if keep(x)]", "keep"),
                                 ("k = lambda: z()", "z")]

def test_calls_ignore_label_options():
    src = "def f(a=d()):\n    return g()\n"
    assert owned(fn(doc_of(src, show_returns=False), "f")) == [("return", "g")]

def test_hidden_assignment_records_calls_only_when_shown():
    src = "def f():\n    x[g()] = 1\n    h()\n"
    assert [t for _, t in owned(fn(doc_of(src), "f"))] == ["h"]
    assert [t for _, t in owned(fn(doc_of(src, show_variables=True), "f"))] == ["g", "h"]

def test_fstring_calls_are_recorded():  # Review Focus 1
    d = doc_of('def f(x):\n    print(f"{fmt(x)}")\n')
    assert [t for _, t in owned(fn(d, "f"))] == ["print", "fmt"]

def test_await_and_async_with_calls():  # Review Focus 2
    d = doc_of("async def f():\n    await g()\n    async with open_conn():\n        pass\n")
    assert [t for _, t in owned(fn(d, "f"))] == ["g", "open_conn"]

def test_same_function_nested_gives_two_calls():  # Review Focus 3
    d = doc_of("def f(x):\n    g(g(x))\n")
    assert owned(fn(d, "f")) == [("g(g(x))", "g"), ("g(g(x))", "g")]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_python_calls.py -v`. Expected: the new tests FAIL (charts have no calls).
- [ ] **Step 3: Implement** the Interfaces. Keep the additions to `statements.py` to passing `calls=` and the two new keywords; all other logic lives in `calls.py`.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`, and check `wc -l src/pyflowcharts/frontends/python/*.py`. Expected: pass; `statements.py` has grown by no more than ~25 lines.
- [ ] **Step 5: Commit** `feat(python): record each statement's calls on the node that owns them`

---

### Task 5: Resolution rules

**Files:**
- Modify: `src/pyflowcharts/frontends/python/calls.py`
- Test: `tests/test_python_calls.py`

**Interfaces:**
- Consumes: `Resolver` (Task 4).
- Produces: `Resolver.sites` fills `CallSite.candidates` per the spec's "Resolution rules" section. Internals are up to the implementer, but the structure the spec implies is:
  - one `_Scope` per function (`Found`) and one for the module, each holding `definitions: dict[str, tuple[str, str]]` (name → `("def" | "class", qualname)`, first wins) and `imports: dict[str, list[_Binding]]` (source order). Both are collected by walking the scope's body without entering nested `function_definition` / `class_definition` nodes.
  - a map from each function to the class whose body directly contains it, for `self.m` / `cls.m`. Class qualnames are built like discovery's: the enclosing prefix plus the class name.
  - the scope chain for `scope=Found` is `Found`, `Found.enclosing`, …, then the module. For `scope=None` it is the module only.
  - candidates deduplicated, keeping the first occurrence.

- [ ] **Step 1: Write failing tests** in `tests/test_python_calls.py`. Helpers:

```python
def cands(src, qualname, text, key="pkg/mod"):
    d = doc_of(src, key=key)
    chart = d.module if qualname == "<module>" else fn(d, qualname)
    call = next(c for c in chart.calls if c.text == text)
    return [(r.module, r.qualname) for r in call.candidates]
```

```python
@pytest.mark.parametrize("src, qualname, text, expected", [
    # bare names: innermost scope first; the owning chart's own scope first
    ("def h(): pass\ndef f():\n    def h(): pass\n    h()\n", "f", "h", [("pkg.mod", "f.h")]),
    ("def f():\n    def g():\n        h()\n    def h(): pass\n", "f.g", "h", [("pkg.mod", "f.h")]),
    ("def f():\n    g()\ndef g(): pass\n", "f", "g", [("pkg.mod", "g")]),  # Review Focus 4
    ("class C:\n    def h(self): pass\n    def m(self):\n        h()\n", "C.m", "h", []),  # class scope invisible
    ("class C: pass\ndef f():\n    C()\n", "f", "C", [("pkg.mod", "C.__init__")]),
    ("from a.b import g\ndef f():\n    g()\n", "f", "g", [("a.b", "g"), ("a.b", "g.__init__")]),
    ("from a import g as k\ndef f():\n    k()\n", "f", "k", [("a", "g"), ("a", "g.__init__")]),
    ("import os as g\ndef f():\n    g()\n", "f", "g", []),
    ("def f():\n    print(len(x))\n", "f", "print", []),
    # local import shadows module-level def and module-level import
    ("def foo(): pass\ndef bar():\n    from other import foo\n    foo()\n", "bar", "foo",
     [("other", "foo"), ("other", "foo.__init__")]),
    ("from first import foo\ndef bar():\n    from other import foo\n    foo()\n", "bar", "foo",
     [("other", "foo"), ("other", "foo.__init__")]),
    # try/except bindings both count, deduplicated
    ("try:\n    from a import g\nexcept ImportError:\n    from b import g\n    from a import g\ndef f():\n    g()\n",
     "f", "g", [("a", "g"), ("a", "g.__init__"), ("b", "g"), ("b", "g.__init__")]),
    # self / cls, including a class nested in a function
    ("class C:\n    def m(self):\n        self.o()\n", "C.m", "self.o", [("pkg.mod", "C.o")]),
    ("class C:\n    @classmethod\n    def m(cls):\n        cls.o()\n", "C.m", "cls.o", [("pkg.mod", "C.o")]),
    ("def outer():\n    class C:\n        def m(self):\n            self.o()\n", "outer.C.m", "self.o",
     [("pkg.mod", "outer.C.o")]),
    ("class C:\n    def m(self):\n        self.x.o()\n", "C.m", "self.x.o", []),
    # Class.method: local, enclosing-function, imported
    ("class C:\n    def s(): pass\ndef f():\n    C.s()\n", "f", "C.s", [("pkg.mod", "C.s")]),
    ("def outer():\n    class C:\n        def s(): pass\n    C.s()\n", "outer", "C.s", [("pkg.mod", "outer.C.s")]),
    ("from m import C\ndef f():\n    C.s()\n", "f", "C.s", [("m.C", "s"), ("m", "C.s")]),
    # module imports
    ("import x.y\ndef f():\n    x.y.g()\n", "f", "x.y.g", [("x.y", "g")]),
    ("import x.y\ndef f():\n    x.g()\n", "f", "x.g", [("x", "g")]),
    ("import x.y as z\ndef f():\n    z.C.m()\n", "f", "z.C.m", [("x.y", "C.m")]),
    ("import x.y as z\ndef f():\n    x.g()\n", "f", "x.g", []),
    ("from p import x as a\ndef f():\n    a.g()\n", "f", "a.g", [("p.x", "g"), ("p", "x.g")]),
    ("from __future__ import annotations\nfrom m import *\ndef f():\n    annotations()\n", "f", "annotations", []),
    ("def f():\n    g()().h()\n", "f", "g()().h", []),
    # function-local import is scoped to that function
    ("def a():\n    from m import g\ndef b():\n    g()\n", "b", "g", []),
    # the owning node decides the scope chain: a default runs in outer
    ("def outer():\n    def helper(): pass\n    def inner(x=helper()): pass\n", "outer", "helper",
     [("pkg.mod", "outer.helper")]),
    # a skipped (syntax error) nested function still gives its candidate, no outer fallback
    ("def helper(): pass\ndef f():\n    def helper(:\n        pass\n    helper()\n", "f", "helper",
     [("pkg.mod", "f.helper")]),
    # a definition and an import in one scope: definition first, then imports
    ("from m import g\ndef g(): pass\ndef f():\n    g()\n", "f", "g",
     [("pkg.mod", "g"), ("m", "g"), ("m", "g.__init__")]),
])
def test_resolution(src, qualname, text, expected):
    assert cands(src, qualname, text) == expected

@pytest.mark.parametrize("key, src, expected", [
    ("pkg/io/load", "from . import x\nx.f()\n", [("pkg.io.x", "f"), ("pkg.io", "x.f")]),
    ("pkg/io/load", "from .util import g\ng()\n", [("pkg.io.util", "g"), ("pkg.io.util", "g.__init__")]),
    ("pkg/io/load", "from ..core import g\ng()\n", [("pkg.core", "g"), ("pkg.core", "g.__init__")]),
    ("pkg/io/__init__", "from .util import g\ng()\n", [("pkg.io.util", "g"), ("pkg.io.util", "g.__init__")]),
    ("pkg/io/load", "from ... import g\ng()\n", []),     # above the top
    ("a", "from . import g\ng()\n", []),                  # top-level file has no package
])
def test_relative_imports(key, src, expected):
    call = doc_of(src, key=key).module.calls[0]
    assert [(r.module, r.qualname) for r in call.candidates] == expected
```

  Check the skipped-function case by hand on the first run: `f.helper` must appear in `warnings` with that qualname, and `f` must still be charted.

- [ ] **Step 2: Run** `uv run pytest tests/test_python_calls.py -v`. Expected: the resolution tests FAIL (candidates are empty).
- [ ] **Step 3: Implement** the rules from the spec.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`, and check `wc -l src/pyflowcharts/frontends/python/calls.py`. Expected: pass. If `calls.py` passes ~300 lines, split the scope and import tables into `frontends/python/scopes.py`.
- [ ] **Step 5: Commit** `feat(python): resolve calls to candidate targets through scopes and imports`

---

### Task 6: Linker

**Files:**
- Create: `src/pyflowcharts/calls.py`
- Test: `tests/test_calls.py` (new)

**Interfaces:**
- Consumes: `Document`, `Chart`, `Call`, `CallRef` (Task 1).
- Produces: `calls.link(documents: list[Document]) -> list[Document]`, following the spec's "Linker" section. It indexes `(module_name, qualname)` for function charts only. It skips documents with an empty module name, and drops every module name that appears in more than one document. It returns `dataclasses.replace`d documents, charts and calls, and never mutates its input.

- [ ] **Step 1: Write failing tests** in `tests/test_calls.py`. Build documents with the real frontend: `parse(src, key)` → `PythonFrontend().parse(src.encode(), f"{key}.py", ChartOptions(), PurePosixPath(key)).document`.

```python
def targets(doc, qualname=None):
    chart = doc.module if qualname is None else next(c for c in doc.functions if c.qualname == qualname)
    return [(c.text, c.target and (c.target.module, c.target.qualname)) for c in chart.calls]

def test_first_existing_candidate_wins_across_documents():
    a = parse("from p import x\ndef f():\n    x.g()\n", "app")
    p = parse("def unused(): pass\n", "p/__init__")
    px = parse("def g(): pass\n", "p/x")
    linked = link([a, p, px])
    assert targets(linked[0], "f") == [("x.g", ("p.x", "g"))]

def test_falls_back_to_later_candidate_and_none():
    a = parse("from p import x\ndef f():\n    x.g()\n    print()\n", "app")
    p = parse("class x:\n    def g(): pass\n", "p/__init__")
    assert targets(link([a, p])[0], "f") == [("x.g", ("p", "x.g")), ("print", None)]

def test_module_chart_calls_are_linked_and_never_targets():
    d = parse("def main(): pass\nif __name__ == '__main__':\n    main()\n", "app")
    linked = link([d])[0]
    assert targets(linked) == [("main", ("app", "main"))]

def test_independent_of_document_order():
    a = parse("from b import g\ndef f():\n    g()\n", "a")
    b = parse("def g(): pass\n", "b")
    assert link([a, b])[0] == link([b, a])[1]

def test_empty_and_duplicate_module_names_are_not_indexed():
    caller = parse("from a.b import g\ndef f():\n    g()\n    h()\n", "c")
    f = caller.functions[0]
    # no resolution rule produces module "", so build that candidate by hand
    h_call = replace(f.calls[1], candidates=[CallRef("", "h")])
    caller = replace(caller, functions=[replace(f, calls=[f.calls[0], h_call])])
    one = parse("def g(): pass\n", "a.b")       # module name "a.b"
    two = parse("def g(): pass\n", "a/b")       # module name "a.b" too
    init = parse("def h(): pass\n", "__init__")  # module name ""
    assert targets(link([caller, one, two, init])[0], "f") == [("g", None), ("h", None)]

def test_input_is_not_mutated():
    a = parse("def f():\n    f()\n", "a")
    link([a])
    assert a.functions[0].calls[0].target is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_calls.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `link`.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(calls): link call candidates to charts across the run`

---

### Task 7: Call graph backend

**Files:**
- Create: `src/pyflowcharts/backends/callgraph.py`
- Modify: `src/pyflowcharts/backends/mermaid.py` (export its label escaping as `escape` if it is private)
- Test: `tests/test_callgraph.py` (new)

**Interfaces:**
- Consumes: linked `Document`s (Task 6).
- Produces:
  - `to_callgraph_digraph(documents: list[Document]) -> graphviz.Digraph`
  - `to_callgraph_dot(documents) -> str`
  - `render_callgraph(documents, fmt: Literal["svg", "png"]) -> bytes`, which raises `graphviz.ExecutableNotFound` like `render`
  - `to_callgraph_mermaid(documents) -> str`
  - Rules are in the spec's "Picture" section:
    - Clusters are `cluster_{i}` (DOT) and `s{i}` (Mermaid), with no cluster for a document without charts. The label is the module name, or the source when the name is empty.
    - DOT node IDs are `{i}#{qualname}`; Mermaid node IDs are `n{k}`.
    - Labels are qualnames, `<module>` for the module chart, escaped.
    - Edges are deduplicated, drawn only to drawn charts, and sorted.
    - `rankdir=LR`; the graph name goes through `graphviz.nohtml`.

- [ ] **Step 1: Write failing tests** in `tests/test_callgraph.py`. Use `parse` as in Task 6 and `link`.

```python
def run(*files):  # files: (src, key)
    return link([parse(src, key) for src, key in files])

APP = ("from lib import g\ndef f():\n    g(g(1))\n    f()\nif __name__ == '__main__':\n    f()\n", "app")
LIB = ("def g(): pass\n", "lib")
EMPTY = ("", "pkg/__init__")

def test_dot_clusters_nodes_and_edges():
    dot = to_callgraph_dot(run(APP, LIB, EMPTY))
    assert "subgraph cluster_0" in dot and "subgraph cluster_1" in dot and "cluster_2" not in dot
    assert 'label=app' in dot and 'label=lib' in dot
    assert '"0#f" -> "1#g"' in dot and dot.count('"0#f" -> "1#g"') == 1   # Review Focus 3
    assert '"0#f" -> "0#f"' in dot                                       # recursion self-loop
    assert '"0#<module>" -> "0#f"' in dot
    assert "rankdir=LR" in dot

def test_module_label_escaped_and_source_fallback_without_colon_ids():
    docs = run(APP, LIB)
    docs[0] = replace(docs[0], module_name="", source="C:/x/app.py")
    dot = to_callgraph_dot(docs)
    assert 'label="<module>"' in dot          # quoted, never an HTML-like label
    assert 'label="C:/x/app.py"' in dot       # cluster falls back to the source path
    assert all(":" not in line for line in dot.splitlines() if "->" in line)

def test_duplicate_module_names_get_distinct_nodes():
    docs = [parse("def f(): pass\n", "a.b"), parse("def f(): pass\n", "a/b")]
    dot = to_callgraph_dot(link(docs))
    assert '"0#f"' in dot and '"1#f"' in dot

def test_only_drawn_targets_get_edges():
    docs = run(APP, LIB)
    docs[1] = replace(docs[1], functions=[])  # as if --function dropped g
    dot = to_callgraph_dot(docs)
    assert "1#g" not in dot and "cluster_1" not in dot

def test_mermaid_generated_ids_and_keyword_safe():
    mmd = to_callgraph_mermaid(run(APP, LIB, ("def g(): pass\n", "end")))
    assert mmd.startswith("flowchart LR")
    assert 'subgraph s0 ["app"]' in mmd and "subgraph end" not in mmd
    assert "#60;module#62;" in mmd or "&lt;module&gt;" in mmd

def test_non_ascii_qualnames():  # Review Focus 5
    docs = run(("def größe(): pass\ndef f():\n    größe()\n", "m"))
    assert '"0#f" -> "0#größe"' in to_callgraph_dot(docs)
    assert "größe" in to_callgraph_mermaid(docs)

def test_deterministic():
    docs = run(APP, LIB)
    assert to_callgraph_dot(docs) == to_callgraph_dot(copy.deepcopy(docs))
    assert to_callgraph_mermaid(docs) == to_callgraph_mermaid(copy.deepcopy(docs))

@needs_dot
def test_svg_renders():
    assert b"<svg" in render_callgraph(run(APP, LIB), "svg")
```

  Tune the exact quoting in the assertions (`label=app` versus `label="app"`) to what `graphviz` emits on the first run. Keep the structural meaning: clusters, IDs, one deduplicated edge, the self-loop, and no HTML label.

- [ ] **Step 2: Run** `uv run pytest tests/test_callgraph.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the backend.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`. Expected: pass.
- [ ] **Step 5: Commit** `feat(backends): draw the run's call graph clustered by file`

---

### Task 8: CLI, writer and the reserved `callgraph` key

**Files:**
- Modify: `src/pyflowcharts/cli.py`, `src/pyflowcharts/output.py`, `src/pyflowcharts/inputs.py`
- Test: `tests/test_cli.py`, `tests/test_output.py`, `tests/test_inputs.py`; update the exact output-set assertions in existing CLI and output tests

**Interfaces:**
- Consumes: `link` (Task 6), the call-graph backend (Task 7).
- Produces:
  - `inputs.collision_error(inputs: list[Input], reserved: Mapping[str, str] = {}) -> str | None`. Reserved keys are checked first: an input whose `key.as_posix()` is a reserved key gives `f"error: output name collision: {path} maps to '{key}'; {reason}"`.
  - `output.py` imports `render_callgraph`, `to_callgraph_dot` and `to_callgraph_mermaid` by name, as it does `render`, so tests can monkeypatch `pyflowcharts.output.render_callgraph`.
  - `output.Writer.write_callgraph(documents: list[Document]) -> None`. It writes `OUTDIR/callgraph.<ext>` for each selected format among `dot`, `svg`, `png` and `mermaid`, and nothing when no document has a chart. Graphviz-missing and write failures are handled as in `_chart`.
  - CLI:
    - `--no-call-graph` (`store_true`), help `"do not write the run's call graph picture"`.
    - `main` calls `link` on all parsed documents before `_select`.
    - It passes `reserved={} if args.no_call_graph else {"callgraph": CALLGRAPH_RESERVED}` to `collision_error`, with `CALLGRAPH_RESERVED = "it is reserved for the call graph; rename the file, chart its parent directory instead, or pass --no-call-graph"`.
    - After writing the documents, it calls `writer.write_callgraph([doc for _, result in results])` unless `--no-call-graph` is given.

- [ ] **Step 1: Write failing tests.**
  - `tests/test_inputs.py`:

```python
def test_reserved_key_collision(tmp_path):
    tree(tmp_path, "callgraph.py", "sub/callgraph.py")
    msg = collision_error(expand([tmp_path], []).inputs, reserved={"callgraph": "it is reserved"})
    assert msg == f"error: output name collision: {tmp_path / 'callgraph.py'} maps to 'callgraph'; it is reserved"
    assert collision_error(expand([tmp_path / "sub"], []).inputs) is None  # no reservation given
```

  - `tests/test_output.py`:

```python
def test_write_callgraph(tmp_path):
    docs = link([parse("def f():\n    f()\n", "a")])
    Writer(tmp_path, ["json", "dot", "mermaid"]).write_callgraph(docs)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["callgraph.dot", "callgraph.mmd"]

def test_no_callgraph_without_charts(tmp_path):
    Writer(tmp_path / "o", ["dot"]).write_callgraph([parse("", "a")])
    assert not (tmp_path / "o").exists()
```

  - `tests/test_cli.py`:

```python
def test_directory_run_writes_call_graph_with_cross_file_edge(tmp_path):
    write(tmp_path / "src/pkg", "__init__.py", "")
    write(tmp_path / "src/pkg", "lib.py", "def g(): pass\n")
    write(tmp_path / "src/pkg", "app.py", "from .lib import g\ndef f():\n    g()\n")
    assert main([str(tmp_path / "src"), "-o", str(tmp_path / "o"), "-f", "json", "dot"]) == 0
    dot = (tmp_path / "o/callgraph.dot").read_text()
    assert "label=pkg.app" in dot.replace('"', "") and "-> " in dot
    call = from_json((tmp_path / "o/pkg/app.json").read_text()).functions[0].calls[0]
    assert (call.target.module, call.target.qualname) == ("pkg.lib", "g")

def test_json_only_writes_no_call_graph(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 0
    assert not (tmp_path / "o/callgraph.dot").exists()

def test_no_call_graph_option(tmp_path):
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "dot", "--no-call-graph"]) == 0
    assert not (tmp_path / "o/callgraph.dot").exists()

def test_function_filter_limits_picture_but_not_targets(tmp_path):
    src = write(tmp_path, "m.py", "def g(): pass\ndef f():\n    g()\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "dot", "--function", "f"]) == 0
    assert "0#g" not in (tmp_path / "o/callgraph.dot").read_text()
    call = from_json((tmp_path / "o/m.json").read_text()).functions[0].calls[0]
    assert call.target.qualname == "g"

def test_reserved_callgraph_key(tmp_path, capsys):
    src = write(tmp_path, "callgraph.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o")]) == 1
    assert "reserved for the call graph" in capsys.readouterr().err and not (tmp_path / "o").exists()
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--no-call-graph"]) == 0

def test_missing_graphviz_still_writes_text_call_graph(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise graphviz.ExecutableNotFound(["dot"])
    monkeypatch.setattr("pyflowcharts.output.render", boom)
    monkeypatch.setattr("pyflowcharts.output.render_callgraph", boom)
    src = write(tmp_path, "m.py", "def f(): pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "svg", "dot"]) == 2
    assert (tmp_path / "o/callgraph.dot").exists()
    assert len(capsys.readouterr().err.splitlines()) == 1  # reported once
```

  Update the existing exact output-set assertions (e.g. `test_directory_input_mirrors_tree`, `test_text_formats`) to include `callgraph.dot` / `callgraph.mmd` where the run selects those formats.

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py tests/test_output.py tests/test_inputs.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the Interfaces.
- [ ] **Step 4: Run** `uv run pytest && uv run ruff check`, and check `wc -l src/pyflowcharts/cli.py`. Expected: pass; `cli.py` stays under 300 lines.
- [ ] **Step 5: Smoke test**: `rm -rf /tmp/pyflowcharts-self && uv run pyflowcharts src -o /tmp/pyflowcharts-self -f json dot`. Expected:
  - exit 0
  - `/tmp/pyflowcharts-self/callgraph.dot` exists
  - `pyflowcharts/cli.json` has a call in `main` whose target is `pyflowcharts.inputs` / `expand`. Check with a one-line `uv run python -c` that loads it via `from_json`.
- [ ] **Step 6: Commit** `feat(cli): link calls and write the run's call graph`

---

### Task 9: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`, `AGENTS.md`, `README.md`, `docs/superpowers/specs/2026-11-13-call-graphs-design.md` (status line)

- [ ] **Step 1: Main spec.** Fold in the spec's Documentation section:
  - Status line
  - Scope (call graphs in scope)
  - IR v3 (`CallRef`, `Call`, `calls`, `module_name`)
  - The frontend protocol argument
  - A summary of call ownership and resolution, with the limits
  - Output layout with `callgraph.<ext>`
  - CLI synopsis with `--no-call-graph`
  - The error table row
- [ ] **Step 2: `AGENTS.md`.**
  - Architecture: `calls.py`, `backends/callgraph.py`, `frontends/python/calls.py`.
  - The `Frontend.parse` signature.
  - Known simplifications: replace "Call graphs are out of scope for now." with the resolution limits.
- [ ] **Step 3: `README.md`.**
  - Intro: call graphs.
  - Usage: `--no-call-graph` in the options table.
  - Output layout: `callgraph.svg`.
  - Schema version 3.
  - A short "Call graphs" subsection: what is resolved, the limits, and "walk the import root (`src/`)".
  - Known simplifications: replace the call-graph bullet with the resolution limits.
- [ ] **Step 4: New spec status.** Set it to "Implemented; folded into the main spec."
- [ ] **Step 5: Verify** with `uv run pytest && uv run ruff check`, then `grep -in "schema version 2\|(= 2)\|call graphs are out of scope\|call graphs between functions are not drawn" README.md AGENTS.md docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`. Expected: tests pass and grep prints nothing.
- [ ] **Step 6: Commit** `docs: describe call graphs`
