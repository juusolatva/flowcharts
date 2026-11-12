# Tree-sitter Python Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stdlib-`ast` Python frontend with a tree-sitter frontend that charts every valid function in a file, skipping broken ones with a warning, on top of a language-neutral CFG engine.

**Architecture:** A new `pyflowcharts/cfg/` package holds a frozen statement model and the shared chart builder (frontier walk, reveal rule, node IDs, `finally` copies). The existing `ast` frontend is first turned into an adapter for that engine so every test stays green, then `frontends/python/` is built on tree-sitter with `ast.parse` as the validity oracle, and `python_ast/` is deleted last.

**Tech Stack:** Python ≥ 3.12, `tree-sitter` 0.26.x, `tree-sitter-python` 0.25.x, stdlib `ast` (validation only), `uv`, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-11-12-tree-sitter-frontend-design.md` (overrides `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md` where they disagree).

## Global Constraints

- All work on branch `feat/tree-sitter-frontend`, merged through a PR. Small Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`), each ending with the attribution line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Use `uv` for everything: `uv run pytest`, `uv run ruff check`, `uv run ruff format`. Both pytest and ruff must pass before every commit.
- Python ≥ 3.12, full type hints, `match` statements for node dispatch, modules under roughly 300 lines.
- `cfg/` imports neither tree-sitter nor anything from `frontends/`. Backends and the CLI import no `ast` and nothing from `frontends/python/`.
- Node IDs: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}[~suffix]`, suffixes `~finally`, `~break@L{line}C{col}`, `~continue@L{line}C{col}`; unique per chart; never contain `:`.
- Output is deterministic: no sets, hashes or timestamps decide order.
- No `SCHEMA_VERSION` bump: the IR and JSON shape do not change.
- Dependencies: `tree-sitter>=0.26`, `tree-sitter-python>=0.25` in `pyproject.toml`; `uv.lock` pins tree-sitter 0.26.0 and tree-sitter-python 0.25.0 (released ≥ two weeks before 2026-11-12).
- Warning format: `path[:line]: warning: message`. Any syntax-error warning gives exit 1; other output is still written.
- CFG tests assert on `flow(chart)` triples, never on node ordering.

## Review Focus

Inputs the spec implies but did not list, each pinned by a test in the owning task:

1. A nested `def` inside a loop whose body contains `break`: the nested function is skipped as a syntax error, the outer function is still charted (Task 10).
2. A decorator with a syntax error: the outside-functions warning is printed and the decorated function itself is still charted (Task 9).
3. An indented method that is the last thing in a file without a trailing newline: validated and charted, no false warning (Task 9).
4. Two statements on one line (`x = g(); y = h()`): two nodes with distinct column-based IDs (Task 7).
5. A file starting with a UTF-8 BOM: columns on line 1 exclude the BOM and the function is found (Task 6).

---

### Task 1: CFG model and builder core

**Files:**

- Create: `src/pyflowcharts/cfg/__init__.py` (empty docstring module)
- Create: `src/pyflowcharts/cfg/model.py`
- Create: `src/pyflowcharts/cfg/builder.py`
- Test: `tests/test_builder.py`

**Interfaces:**

- Consumes: `pyflowcharts.ir` (`ChartOptions`, `Edge`, `Node`, `NodeKind`, `SourceLocation`), `pyflowcharts.labels.shorten`.
- Produces, in `model.py` (all `@dataclass(frozen=True)`):
  - `Block = tuple["Stmt", ...]`
  - `Step(label: str, loc: SourceLocation, body: Block = (), hidden: bool = False)`
  - `Arm(edge_label: str, body: Block)`; `Branch(label: str, loc: SourceLocation, arms: tuple[Arm, ...], default: str | None)`
  - `Loop(label: str, loc: SourceLocation, enter: str, exit: str | None, body: Block, orelse: Block)`
  - `Handler(label: str, loc: SourceLocation, body: Block)`; `Try(loc: SourceLocation, body: Block, handlers: tuple[Handler, ...], orelse: Block, finalbody: Block | None)`
  - `Terminal(kind: NodeKind, label: str, loc: SourceLocation)`; `Break(loc: SourceLocation)`; `Continue(loc: SourceLocation)`
  - `Stmt = Step | Branch | Loop | Try | Terminal | Break | Continue`
- Produces, in `builder.py`:
  - `Frontier = list[tuple[str, str | None]]`
  - `build_chart(qualname: str, start_label: str, start_loc: SourceLocation, body: Block, options: ChartOptions) -> tuple[list[Node], list[Edge]]`
  - `class ChartBuilder` with public attributes `qualname`, `options`, `nodes`, `edges`, `end_id`, `loops: list[LoopContext]`, `pending: list[FinallyContext]`, `copy_suffix: str`, and methods `block(stmts: Block, frontier: Frontier) -> Frontier`, `add_node(loc: SourceLocation, kind: NodeKind, label: str, suffix: str = "") -> str`, `connect(frontier: Frontier, target_id: str) -> None`, `label(text: str) -> str`. Loops, `Try` and `StrayLoopTransfer` are added in Tasks 2 and 3; in this task `Loop`/`Try`/`Break`/`Continue` may raise `NotImplementedError`.
  - `@dataclass class LoopContext(loop_id: str, breaks: Frontier)`; `@dataclass class FinallyContext(loop_depth: int, breaks: Frontier, continues: Frontier)` (defined here so `finally_.py` can import them without a cycle).

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/tree-sitter-frontend main
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_builder.py`, a helper that builds a `FunctionChart` so `conftest.flow` works on it:

```python
LOC = SourceLocation(1, 0, 1, 10)

def at(line: int, col: int = 4) -> SourceLocation:
    return SourceLocation(line, col, line, col + 1)

def chart(body: Block, **opts) -> FunctionChart:
    nodes, edges = build_chart("f", "def f()", LOC, body, ChartOptions(**opts))
    return FunctionChart("f", "f", False, [], None, LOC, nodes, edges)
```

Tests:

```python
def test_sequence_and_terminal():
    c = chart((Step("a()", at(2)), Terminal(NodeKind.RETURN, "return 1", at(3))))
    assert flow(c) == {("def f()", "a()", None), ("a()", "return 1", None), ("return 1", "end", None)}
    assert [n.id for n in c.nodes] == ["f#start", "f#end", "f#L2C4", "f#L3C4"]
    assert c.nodes[0].kind is NodeKind.START and c.nodes[1].location is None

def test_hidden_steps_need_variables_option():
    body = (Step("n = 0", at(2), hidden=True), Step("g()", at(3)))
    assert "n = 0" not in {n.label for n in chart(body).nodes}
    assert "n = 0" in {n.label for n in chart(body, show_variables=True).nodes}

def test_reveal_rule_per_block():
    inner = (Step("n = 0", at(3), hidden=True),)
    body = (Branch("if a", at(2), (Arm("True", inner), Arm("False", (Step("n = 1", at(5), hidden=True), Step("g()", at(6)))),), None),)
    labels = {n.label for n in chart(body).nodes}
    assert "n = 0" in labels and "n = 1" not in labels

def test_branch_default_falls_through():
    body = (Branch("if x", at(2), (Arm("True", (Step("a()", at(3)),)),), "False"), Step("b()", at(4)))
    assert flow(chart(body)) == {("def f()", "if x", None), ("if x", "a()", "True"), ("a()", "b()", None), ("if x", "b()", "False"), ("b()", "end", None)}

def test_step_with_body():
    body = (Step("with x", at(2), body=(Step("a()", at(3)),)),)
    assert flow(chart(body)) == {("def f()", "with x", None), ("with x", "a()", None), ("a()", "end", None)}

def test_labels_and_edge_labels_are_shortened():
    body = (Branch("if " + "x" * 100, at(2), (Arm("case " + "y" * 100, ()),), None),)
    c = chart(body, max_label_length=10)
    assert "if xxxxxx…" in {n.label for n in c.nodes}
    assert {e.label for e in c.edges} == {"case yyyy…"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: pyflowcharts.cfg`.

- [ ] **Step 4: Implement `model.py` and `builder.py`**

Port the frontier walk, `_block` reveal logic, `_if`/`_match` (now one `Branch` handler: one `block` per arm from `(node_id, label(arm.edge_label))`, plus `(node_id, default)` if `default is not None`), `_chain`, `_terminal`, `_add_node`, `_connect` and `_label` from `src/pyflowcharts/frontends/python_ast/cfg.py` onto the model types. Visibility of a `Step` is `not hidden or options.show_variables`; the reveal rule is `not any(visible(s) for s in stmts)`. `add_node` uses `loc.line`/`loc.column` for the ID and stores `None` as location when `suffix` is non-empty, as today.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder.py -v && uv run ruff check && uv run ruff format --check`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/pyflowcharts/cfg tests/test_builder.py
git commit -m "feat: language-neutral CFG model and builder core"
```

---

### Task 2: Loops, break and continue in the builder

**Files:**

- Modify: `src/pyflowcharts/cfg/builder.py`
- Test: `tests/test_builder.py`

**Interfaces:**

- Produces: `class StrayLoopTransfer(Exception)` in `builder.py` with attributes `kind: str` (`"break"` or `"continue"`) and `loc: SourceLocation`; `ChartBuilder.route_break(frontier: Frontier) -> None` and `route_continue(frontier: Frontier) -> None`, which consult `pending` (a `FinallyContext` whose `loop_depth == len(loops)`) before `loops[-1]`, exactly as today's `_break`/`_continue`/`_pending_finally`.

- [ ] **Step 1: Write the failing tests**

```python
def test_loop_enter_exit_else_and_break():
    body = (Loop("for x in xs", at(2), "next", "done",
                 (Branch("if x", at(3), (Arm("True", (Break(at(4)),)),), "False"), Step("work(x)", at(5))),
                 (Step("nobreak()", at(7)),)), Step("after()", at(8)))
    assert flow(chart(body)) == {
        ("def f()", "for x in xs", None), ("for x in xs", "if x", "next"), ("if x", "after()", "True"),
        ("if x", "work(x)", "False"), ("work(x)", "for x in xs", None), ("for x in xs", "nobreak()", "done"),
        ("nobreak()", "after()", None), ("after()", "end", None)}

def test_continue_goes_to_loop_head():
    body = (Loop("while c", at(2), "True", "False", (Continue(at(3)), Step("dead()", at(4))), ()),)
    assert ("while c", "while c", "True") in flow(chart(body))

def test_loop_without_exit():
    body = (Loop("while True", at(2), "True", None, (Step("poll()", at(3)),), ()), Step("after()", at(4)))
    f = flow(chart(body))
    assert ("while True", "after()", "False") not in f and not any(t == "after()" for _, t, _ in f)

def test_stray_break_raises():
    with pytest.raises(StrayLoopTransfer) as e:
        chart((Break(at(2)),))
    assert (e.value.kind, e.value.loc) == ("break", at(2))
    with pytest.raises(StrayLoopTransfer) as e:
        chart((Continue(at(3)),))
    assert e.value.kind == "continue"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder.py -v -k "loop or continue or stray"`
Expected: FAIL with `NotImplementedError` / `ImportError: StrayLoopTransfer`.

- [ ] **Step 3: Implement loops and routing**

Port `_loop`, `_break`, `_continue`, `_pending_finally`, `_innermost_loop` from the old `cfg.py`; `_innermost_loop` raises `StrayLoopTransfer(kind, loc)` when `loops` is empty instead of `RuntimeError`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg/builder.py tests/test_builder.py
git commit -m "feat: loops, break and continue in the shared builder"
```

---

### Task 3: `try`/`finally` in the builder

**Files:**

- Create: `src/pyflowcharts/cfg/finally_.py`
- Modify: `src/pyflowcharts/cfg/builder.py` (dispatch `Try` to `emit_try`)
- Test: `tests/test_builder.py`

**Interfaces:**

- Produces: `emit_try(builder: ChartBuilder, stmt: Try, frontier: Frontier) -> Frontier` in `finally_.py`. It imports `ChartBuilder`, `Frontier`, `FinallyContext` from `builder.py` under `TYPE_CHECKING` only (runtime import of `FinallyContext` is fine, the class has no dependency on `finally_`); `builder.py` imports `emit_try` at module level. The `try` node is `add_node(stmt.loc, PROCESS, "try")`; handlers `add_node(h.loc, PROCESS, h.label)` reached by `(try_id, "exception")`; finally copies `add_node(stmt.loc, PROCESS, label, suffix="~finally")` with `copy_suffix` extended by `~{kind}@L{stmt.loc.line}C{stmt.loc.column}`, exactly as today's `_try`/`_finally_copy`.

- [ ] **Step 1: Write the failing tests**

```python
def try_stmt(line, body, handlers=(), orelse=(), finalbody=None):
    return Try(at(line), body, handlers, orelse, finalbody)

def test_try_except_else_finally():
    body = (try_stmt(2, (Step("load()", at(3)),),
                     (Handler("except E", at(4), (Terminal(NodeKind.RETURN, "return", at(5)),)),),
                     (Step("use()", at(7)),), (Step("cleanup()", at(9)),)), Step("after()", at(10)))
    assert flow(chart(body)) == {
        ("def f()", "try", None), ("try", "load()", None), ("try", "except E", "exception"),
        ("except E", "return", None), ("return", "end", None), ("load()", "use()", None),
        ("use()", "finally", None), ("finally", "cleanup()", None), ("cleanup()", "after()", None),
        ("after()", "end", None)}

def test_empty_finalbody_still_gets_a_node():
    c = chart((try_stmt(2, (Step("a()", at(3)),), finalbody=()),))
    assert ("finally", "end", None) in flow(c) and any(n.id == "f#L2C4~finally" for n in c.nodes)

def test_no_finally_clause():
    c = chart((try_stmt(2, (Step("a()", at(3)),), (Handler("except", at(4), ()),)),))
    assert flow(c) == {("def f()", "try", None), ("try", "a()", None), ("try", "except", "exception"), ("a()", "end", None), ("except", "end", None)}

def test_break_runs_its_own_finally_copy():
    loop = Loop("for x in xs", at(2), "next", "done",
                (try_stmt(3, (Branch("if x", at(4), (Arm("True", (Break(at(5)),)),), "False"), Step("work()", at(6))),
                          finalbody=(Step("cleanup()", at(8)),)),), ())
    c = chart((loop, Step("after()", at(9))))
    f = flow(c)
    assert {("if x", "finally (break)", "True"), ("work()", "finally", None), ("finally (break)", "cleanup()", None), ("for x in xs", "after()", "done")} <= f
    ids = {n.id for n in c.nodes}
    assert "f#L3C4~finally" in ids and "f#L3C4~finally~break@L3C4" in ids and "f#L8C4~break@L3C4" in ids
    assert ("cleanup()", "after()", None) in f and ("cleanup()", "for x in xs", None) in f

def test_finally_continue_overrides_break():
    loop = Loop("while True", at(2), "True", None, (try_stmt(3, (Break(at(4)),), finalbody=(Continue(at(6)),)),), ())
    f = flow(chart((loop, Step("after()", at(7)))))
    assert ("finally (break)", "while True", None) in f and not any(t == "after()" for _, t, _ in f)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder.py -v -k "try or finally"`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `emit_try`**

Port `_try` and `_finally_copy` from the old `cfg.py` onto the model; `finalbody is None` returns the normal frontier without a finally node, `finalbody == ()` still creates one.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg tests/test_builder.py
git commit -m "feat: try/finally handling in the shared builder"
```

---

### Task 4: Turn the `ast` frontend into an adapter (no behaviour change)

**Files:**

- Modify: `src/pyflowcharts/frontends/python_ast/cfg.py` (becomes `ast` → model conversion only)
- Modify: `src/pyflowcharts/frontends/python_ast/frontend.py:95-110` (`_chart` calls `build_chart`)

**Interfaces:**

- Consumes: everything from Tasks 1–3.
- Produces, in `python_ast/cfg.py`: `function_body(func: FunctionNode, source: SourceText, options: ChartOptions) -> Block` (drops a leading docstring, applies the statement rules of the main spec), plus the existing `location_of` and `start_label_for`. `CfgBuilder` is deleted.

- [ ] **Step 1: Run the whole suite as the baseline**

Run: `uv run pytest -q`
Expected: all PASS (this is the test for the task; nothing new is written).

- [ ] **Step 2: Rewrite `python_ast/cfg.py` as a converter**

One `match` over `ast.stmt` producing model statements: assignments → `Step(text, loc, hidden=not _contains_call(stmt.value))`; `Return`/`Raise` → `Terminal`; `If` → `Branch` with `elif` as a nested `Branch` in the `False` arm, `default="False"` when `orelse` is empty; `Match` → `Branch` with `default="no match"` unless the last case is irrefutable (same test as today); `For`/`While` → `Loop` (`exit=None` for constant-true `while`); `Try`/`TryStar` → `Try` with `finalbody=None` when `stmt.finalbody` is empty; `With` → `Step(body=...)`; nested def/class → `Step`; `Break`/`Continue`; skipped statements produce nothing. `frontend._chart` calls `build_chart(qualname, start_label_for(func, options), location_of(func), function_body(func, source, options), options)`. Catch `StrayLoopTransfer` nowhere: `compile()` validation still makes it unreachable here.

- [ ] **Step 3: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all PASS, byte-identical behaviour (no test changed).

- [ ] **Step 4: Commit**

```bash
git add src/pyflowcharts/frontends/python_ast
git commit -m "refactor: build ast frontend charts through the shared CFG engine"
```

---

### Task 5: Frontend protocol change (`ParseResult`, `Diagnostic`)

**Files:**

- Modify: `src/pyflowcharts/frontends/base.py`
- Modify: `src/pyflowcharts/frontends/python_ast/frontend.py` (`parse` returns `ParseResult(document, ())`)
- Modify: `src/pyflowcharts/cli.py:51-80` (documents become `list[tuple[Path, ParseResult]]`; warnings printed; any warning → exit 1)
- Modify: `tests/conftest.py`, `tests/test_frontend.py`, `tests/test_cli.py`, `tests/test_cfg_try_with.py`, `tests/test_graph_invariants.py` (every `.parse(...)` result gains `.document`)
- Test: `tests/test_frontend.py`

**Interfaces:**

- Produces, in `base.py`: `@dataclass(frozen=True) class Diagnostic(path: str, line: int | None, message: str, qualname: str | None)` with `__str__` → `f"{path}:{line}: warning: {message}"` or `f"{path}: warning: {message}"`; `@dataclass(frozen=True) class ParseResult(document: Document, warnings: tuple[Diagnostic, ...])`; `Frontend.parse(...) -> ParseResult`.
- Produces, in `cli.py`: `_parse_file(path, options) -> ParseResult`; a `_report(results)` step that prints every warning to stderr in order and returns whether any was printed.

- [ ] **Step 1: Write the failing test**

```python
def test_diagnostic_renders_like_errors():
    assert str(Diagnostic("a.py", 3, "boom", "f")) == "a.py:3: warning: boom"
    assert str(Diagnostic("a.py", None, "boom", None)) == "a.py: warning: boom"

def test_parse_returns_result_without_warnings():
    result = PythonFrontend().parse(b"def f(): pass\n", "t.py", ChartOptions())
    assert isinstance(result, ParseResult) and result.warnings == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_frontend.py -v -k "diagnostic or parse_returns"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the protocol change and adapt callers**

Add the dataclasses and change the protocol; wrap the `ast` frontend's `Document` in `ParseResult`; in the CLI print `str(w)` for each warning after a file is parsed and set `status = EXIT_ERROR` if any; in `conftest.chart_of` and the listed tests use `.document`.

- [ ] **Step 4: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat: frontends return a ParseResult with diagnostics"
```

---

### Task 6: Dependencies and the `Source` module

**Files:**

- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `src/pyflowcharts/frontends/python/__init__.py` (empty for now)
- Create: `src/pyflowcharts/frontends/python/source.py`
- Test: `tests/test_python_source.py`

**Interfaces:**

- Produces, in `source.py`:
  - `class Source` with `@classmethod from_bytes(raw: bytes, path: str) -> Source`, raising `SourceError(path, message)` for a bad coding cookie, undecodable bytes or null bytes (`"source code cannot contain null bytes"`). Decodes with `importlib.util.decode_source` (cookie, BOM, newline normalisation), stores `text: str`, `data: bytes` (`text.encode()`), `lines: list[bytes]` (`data.split(b"\n")`) and `tree: tree_sitter.Tree` from a module-level `Parser(Language(tree_sitter_python.language()))`.
  - `Source.source_text(node: Node) -> str`: leaves in order, `comment` and `line_continuation` dropped, `string` treated as a leaf; a whitespace gap between leaves becomes `" "` unless the previous leaf text ends with one of `([{` or the next starts with one of `)]},.`.
  - `Source.location(node: Node) -> SourceLocation`: `line = start_point.row + 1`, `column = start_point.column`; end taken from the last descendant leaf that is not a `comment` (`end_line`, `end_column` likewise 1-based row / byte column).

- [ ] **Step 1: Add the dependencies**

```bash
uv add --exclude-newer 2026-10-29 "tree-sitter>=0.26" "tree-sitter-python>=0.25"
grep -A1 -E '^name = "tree-sitter(-python)?"$' uv.lock
```

Expected: `pyproject.toml` lists both with the lower bounds; `uv.lock` shows `version = "0.26.0"` and `version = "0.25.0"`.

- [ ] **Step 2: Write the failing tests**

```python
def src(text: str | bytes) -> Source:
    return Source.from_bytes(text if isinstance(text, bytes) else text.encode(), "t.py")

def first_stmt(text):  # first statement of the first function body
    s = src(text)
    return s, s.tree.root_node.children[0].child_by_field_name("body").children[0]

def test_coding_cookie_and_bom():
    assert src(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n").text.endswith("x = 'é'\n")
    s = src(b"\xef\xbb\xbfdef f():\n    pass\n")
    assert s.text.startswith("def f") and s.location(s.tree.root_node.children[0]).column == 0

def test_crlf_is_normalised():
    s = src(b"def f():\r\n    g()\r\n")
    assert "\r" not in s.text and s.location(s.tree.root_node.children[0]).end_line == 2

def test_bad_sources_are_file_level_errors():
    for raw in (b"# coding: nope\nx = 1\n", b"x = 1\x00\n", b"\xff\xfe\n"):
        with pytest.raises(SourceError):
            src(raw)

def test_source_text_joins_wrapped_code():
    s, node = first_stmt("def f():\n    g(\n        1,  # note\n        0x2)\n")
    assert s.source_text(node) == "g(1, 0x2)"
    s, node = first_stmt("def f():\n    (df\n     .filter()\n     .select())\n")
    assert s.source_text(node) == "(df.filter().select())"
    s, node = first_stmt("def f():\n    x = 1 + \\\n        2\n")
    assert s.source_text(node) == "x = 1 + 2"

def test_strings_are_verbatim():
    s, node = first_stmt('def f():\n    g(f"{ x }", """a\n  b""")\n')
    assert s.source_text(node) == 'g(f"{ x }", """a\n  b""")'

def test_locations_use_byte_columns_and_skip_trailing_comments():
    s = src("def f():\n    s = 'é'; g()\n    # trailing\n")
    func = s.tree.root_node.children[0]
    g = func.child_by_field_name("body").children[-2]
    assert (s.location(g).line, s.location(g).column) == (2, 14)
    assert s.location(func).end_line == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_python_source.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `source.py`**

Catch `SyntaxError`/`LookupError`/`UnicodeDecodeError` from `decode_source` and `b"\x00" in raw` into `SourceError`. For `source_text`, walk with a cursor or recursion over `node.children`, stopping at `string`/leaf nodes, and join with `data[prev.end_byte:cur.start_byte]` inspected for whitespace.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_python_source.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/pyflowcharts/frontends/python tests/test_python_source.py
git commit -m "feat: tree-sitter source decoding, labels and locations"
```

---

### Task 7: Statement conversion (tree-sitter → model)

**Files:**

- Create: `src/pyflowcharts/frontends/python/statements.py`
- Test: `tests/test_python_statements.py`

**Interfaces:**

- Consumes: `Source` (Task 6), `cfg.model` (Task 1), `build_chart` (Task 1).
- Produces, in `statements.py`:
  - `convert_body(func: Node, src: Source, options: ChartOptions) -> Block`: the function's `body` block with a leading docstring dropped (first statement is an `expression_statement` whose only child is `string` or `concatenated_string` whose first `string_start` text has no `f`/`F`/`b`/`B` character).
  - `convert_block(block: Node | None, src: Source, options: ChartOptions) -> Block` (`None` or empty block → `()`).
  - `signature_label(func: Node, src: Source, options: ChartOptions) -> str`: `[async ]def name(<source_text(parameters)>)[ -> <source_text(return_type)>]`, or `[async ]def name(...)` when `show_parameters` is false.
  - `always_true(cond: str) -> bool`: `ast.parse(cond, mode="eval").body` is an `ast.Constant` with truthy value; `False` on `SyntaxError`/`ValueError`.
  - Handler label: `"except" + ("*" if the clause has a `*` child else "") + (" " + source_text joined over the named children before the colon, if any)`.

- [ ] **Step 1: Write the failing tests**

Helper: parse, take the first `function_definition`, `convert_body`, `build_chart("f", "def f()", loc, body, options)` into a `FunctionChart`, assert on `flow`/labels/IDs. Tests focused on tree-sitter-specific rules (the existing CFG tests cover the rest after Task 11):

```python
def test_docstring_variants():
    assert flow(chart("def f():\n    'a' 'b'\n")) == {("def f()", "end", None)}
    assert "f'x'" in labels(chart("def f():\n    f'x'\n"))          # not a docstring
    assert "'late'" in labels(chart("def f():\n    g()\n    'late'\n"))

def test_assignment_hidden_unless_right_side_calls():
    c = chart("def f():\n    x[g()] = 1\n    y = h()\n    z: int\n    a = b = k()\n")
    assert labels(c) == {"def f()", "end", "y = h()", "a = b = k()"}

def test_two_statements_on_one_line_get_distinct_ids():
    c = chart("def f():\n    x = g(); y = h()\n")
    assert {n.id for n in c.nodes} >= {"f#L2C4", "f#L2C13"}

def test_if_elif_located_at_elif():
    c = chart("def f(x):\n    if x:\n        a()\n    elif x > 1:\n        b()\n")
    assert next(n.id for n in c.nodes if n.label == "if x > 1") == "f#L4C4"
    assert ("if x > 1", "end", "False") in flow(c)

@pytest.mark.parametrize("case,irrefutable", [("case y:", True), ("case (y):", True), ("case _:", True), ("case Foo.bar:", False), ("case y if g:", False), ("case [a]:", False), ("case 1, 2:", False)])
def test_match_irrefutable_last_case(case, irrefutable):
    f = flow(chart(f"def f(x):\n    match x:\n        case 0:\n            a()\n        {case}\n            b()\n"))
    assert (("match x", "end", "no match") in f) is (not irrefutable)
    assert any(lbl == case[:-1] for _, _, lbl in f)

@pytest.mark.parametrize("cond,exits", [("True", False), ("1.0", False), ('"x"', False), ('b"x"', False), ("(1)", False), ("...", False), ("0.0", True), ('""', True), ("(1,)", True), ("n > 0", True)])
def test_while_constant_conditions(cond, exits):
    f = flow(chart(f"def f(n):\n    while {cond}:\n        g()\n    after()\n"))
    assert ((f"while {cond}", "after()", "False") in f) is exits

def test_handler_labels_from_source():
    c = chart("def f():\n    try:\n        a()\n    except (A, B) as e:\n        b()\n    except* C:\n        c()\n    except:\n        d()\n")
    assert {"except (A, B) as e", "except* C", "except"} <= labels(c)

def test_with_keeps_parentheses_and_async():
    assert "with (open(p) as fh, lock)" in labels(chart("def f(p):\n    with (open(p) as fh, lock):\n        a()\n"))
    assert "async with x" in labels(chart("async def f(x):\n    async with x:\n        a()\n"))

def test_return_labels():
    assert "return" in labels(chart("def f():\n    return\n"))
    assert "return" in labels(chart("def f():\n    return 1\n", show_returns=False))
    assert "return {'k': 1_000}" in labels(chart("def f():\n    return {'k': 1_000}\n"))

def test_nested_definitions_are_steps_located_at_def():
    c = chart("def f():\n    @deco\n    def g(a, b=1) -> int:\n        pass\n    class C:\n        pass\n")
    assert {"def g(a, b=1) -> int", "class C"} <= labels(c)
    assert next(n.id for n in c.nodes if n.label.startswith("def g")) == "f#L3C4"

def test_signature_label_keeps_source_spacing():
    c = chart("def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool: ...", max_label_length=200)
    assert c.nodes[0].label == "def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool"
    assert chart("async def f(a):\n    pass\n", show_parameters=False).nodes[0].label == "async def f(...)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_python_statements.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `statements.py`**

One `match node.type` over `expression_statement` (look inside for `assignment`/`augmented_assignment`/`string`/`ellipsis`), `pass_statement`, `global_statement`, `nonlocal_statement`, `return_statement`, `raise_statement`, `if_statement` (+ `elif_clause`/`else_clause` children), `match_statement` (`case_clause` children with `case_pattern`s and `guard`), `for_statement`, `while_statement`, `try_statement` (`except_clause`, `except_group_clause` if the grammar emits it, `else_clause`, `finally_clause`), `with_statement`, `function_definition`, `class_definition`, `decorated_definition` (recurse into its `definition` field for label and location), `break_statement`, `continue_statement`, default `Step(src.source_text(node), src.location(node))`. Irrefutable test per the spec's `match` row.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_python_statements.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/frontends/python/statements.py tests/test_python_statements.py
git commit -m "feat: convert tree-sitter statements to the CFG model"
```

---

### Task 8: Function discovery and signatures

**Files:**

- Create: `src/pyflowcharts/frontends/python/discovery.py`
- Test: `tests/test_python_discovery.py`

**Interfaces:**

- Produces, in `discovery.py`:
  - `@dataclass(frozen=True) class Found(node: Node, qualname: str, name: str, is_async: bool, enclosing: Found | None)` (`enclosing` is the nearest enclosing *function*, `None` for an outermost one).
  - `find_functions(root: Node) -> list[Found]`: depth-first source order over every node including `ERROR`; prefix built from `class_definition`/`function_definition` ancestors' names; later duplicates get `@L{line}`.
  - `parameters(func: Node, src: Source) -> list[Parameter]` per the spec's parameter-kind rules; `annotation`/`default` are `src.source_text(...)` or `None`.
  - `returns(func: Node, src: Source) -> str | None` from the `return_type` field.

- [ ] **Step 1: Write the failing tests**

```python
def found(text): 
    s = Source.from_bytes(textwrap.dedent(text).encode(), "t.py"); return s, find_functions(s.tree.root_node)

def test_qualnames_duplicates_and_async():
    _, fs = found("""
        def top(): pass
        class A:
            def m(self):
                def inner(): pass
            @property
            def x(self): return 1
            @x.setter
            def x(self, v): pass
        async def co(): pass
        if True:
            def under_if(): pass
    """)
    assert [f.qualname for f in fs] == ["top", "A.m", "A.m.inner", "A.x", "A.x@L9", "co", "under_if"]
    assert fs[-2].is_async and fs[2].enclosing is fs[1] and fs[1].enclosing is None

def test_functions_inside_error_regions():
    _, fs = found("class A(:\n    def m(self):\n        pass\n\ndef g():\n    pass\n")
    assert [f.qualname for f in fs] == ["A.m", "g"]
    _, fs = found("def f()\n    pass\n\ndef g():\n    pass\n")
    assert [f.qualname for f in fs] == ["g"]   # unrecoverable header: not found

def test_parameters_and_returns():
    s, (f,) = found("def f(a: int, /, b=2, *args, c, d: str = \"a  b\", **kw) -> list[int]: ...")
    P, K = Parameter, ParamKind
    assert parameters(f.node, s) == [
        P("a", "int", None, K.POSITIONAL_ONLY), P("b", None, "2", K.POSITIONAL_OR_KEYWORD),
        P("args", None, None, K.VAR_POSITIONAL), P("c", None, None, K.KEYWORD_ONLY),
        P("d", "str", '"a  b"', K.KEYWORD_ONLY), P("kw", None, None, K.VAR_KEYWORD)]
    assert returns(f.node, s) == "list[int]"
    s, (g,) = found("def g(*, k, **kw: int): pass")
    assert [p.kind for p in parameters(g.node, s)] == [K.KEYWORD_ONLY, K.VAR_KEYWORD]
    assert parameters(g.node, s)[1].annotation == "int"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_python_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `discovery.py`**

Recursive walk carrying `(prefix, enclosing)`; `class_definition` extends the prefix with its `name` field; `function_definition` records `Found` and recurses into its body with `qualname + "."`. Parameter kinds: iterate `parameters` children, switching to keyword-only after `keyword_separator` or `list_splat_pattern`; a `typed_parameter` whose first child is `list_splat_pattern`/`dictionary_splat_pattern` is the typed splat.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_python_discovery.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/frontends/python/discovery.py tests/test_python_discovery.py
git commit -m "feat: discover functions and signatures in tree-sitter trees"
```

---

### Task 9: Validation with `ast.parse`

**Files:**

- Create: `src/pyflowcharts/frontends/python/validate.py`
- Test: `tests/test_python_validate.py`

**Interfaces:**

- Consumes: `Source`, `Found`, `Diagnostic`.
- Produces, in `validate.py`:
  - `@dataclass(frozen=True) class Validation(skipped: dict[str, Diagnostic], outside: Diagnostic | None)` (`skipped` keyed by qualname, insertion order = source order).
  - `validate(src: Source, functions: list[Found], path: str) -> Validation` implementing spec steps 1–5 and the tree-sitter `ERROR`/`MISSING` check (own subtree, nested `function_definition` subtrees excluded). Messages exactly: `syntax error in '{qualname}'; function skipped`, with ` (not valid for Python {major}.{minor})` appended when the function's subtree has no error node; `syntax error outside functions; nearby code may be missing`.
  - `stub(lines: list[bytes], func: Node) -> list[bytes]` helper: replaces from the function's `:` child through the end of its subtree with `b" pass"` and spaces, newlines kept.
  - May raise `RecursionError`/`MemoryError` from `ast.parse`; the frontend (Task 10) turns those into `SourceError`.

- [ ] **Step 1: Write the failing tests**

```python
def check(text: str) -> Validation:
    s = Source.from_bytes(textwrap.dedent(text).encode(), "t.py")
    return validate(s, find_functions(s.tree.root_node), "t.py")

def test_clean_file():
    v = check("def f():\n    return 1\n")
    assert v == Validation({}, None)

@pytest.mark.parametrize("body,line", [("", 1), ("    try:\n        x()\n", 3), ("    x()\n      y()\n", 3), ("    if x:\n", 2), ("    for a in b:\n", 2), ("    with a:\n", 2), ("    try:\n        x()\n    except:\n", 4)])
def test_invalid_python_tree_sitter_accepts(body, line):
    v = check(f"def f():\n{body}\n\ndef g():\n    pass\n")
    assert list(v.skipped) == ["f"] and v.skipped["f"].line == line and v.outside is None
    assert v.skipped["f"].message == "syntax error in 'f'; function skipped"

def test_indented_method_line_mapping_and_eof_without_newline():
    v = check("class A:\n    def m(self):\n        x = = 1\n    def n(self):\n        return 1")
    assert v.skipped["A.m"].line == 3 and "A.n" not in v.skipped

def test_nested_function_errors_stay_nested():
    v = check("def outer():\n    def inner():\n    return 1\n")           # empty nested body
    assert list(v.skipped) == ["outer.inner"] and v.skipped["outer.inner"].line == 2
    v = check("def outer():\n    x = 1\n    def inner():\n        nonlocal x\n        x = 2\n")
    assert v == Validation({}, None)
    v = check("def outer():\n    def inner():\n        x = 1\n      y = 2\n    return 1\n")  # under-indent
    assert list(v.skipped) == ["outer"]

def test_outside_errors():
    v = check("x = = 1\nclass A:\n    y = = 2\n    def m(self):\n        z = = 3\n")
    assert list(v.skipped) == ["A.m"] and v.outside is not None and v.outside.line == 1
    assert v.outside.message == "syntax error outside functions; nearby code may be missing"
    v = check("@(\ndef f():\n    pass\n")
    assert v.skipped == {} and v.outside is not None           # decorator error; tree-sitter still finds f
    v = check("def f()\n    pass\n\ndef g():\n    pass\n")
    assert v.skipped == {} and v.outside is not None and v.outside.line == 1

def test_tree_sitter_only_errors_and_version_skew():
    v = check("def f(:\n    pass\n")
    assert v.skipped["f"].line == 1 and "not valid for" not in v.skipped["f"].message
    try:
        ast.parse("try:\n    pass\nexcept A, B:\n    pass\n")
    except SyntaxError:
        v = check("def f():\n    try:\n        pass\n    except A, B:\n        pass\n")
        assert v.skipped["f"].message.endswith(f"(not valid for Python {sys.version_info.major}.{sys.version_info.minor})")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_python_validate.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `validate.py`**

Work on `src.lines` (bytes). Step 1: `ast.parse(src.text)`. Step 2: stub every `Found` with `enclosing is None`, join, decode, parse. Step 3 per function: slice rows `node.start_point.row .. node.end_point.row`, stub each `Found` whose `enclosing` is this function, prepend `b"if 1:"` when `node.start_point.column > 0`, parse; map `e.lineno - header + start_row + 1`, clamp to `[start_row + 1, end_row + 1]`. Step 4: `has_error` walk skipping nested `function_definition`; first error node's row for the line when `ast` passed. Validate every function even when step 1 passed, for the tree-sitter check.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_python_validate.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/frontends/python/validate.py tests/test_python_validate.py
git commit -m "feat: per-function syntax validation with ast.parse"
```

---

### Task 10: The tree-sitter `PythonFrontend`

**Files:**

- Create: `src/pyflowcharts/frontends/python/frontend.py`
- Modify: `src/pyflowcharts/frontends/python/__init__.py` (export `PythonFrontend`)
- Test: `tests/test_python_frontend.py`

**Interfaces:**

- Produces: `class PythonFrontend` with `language = "python"`, `extensions = (".py",)`, `parse(source: bytes, path: str, options: ChartOptions) -> ParseResult`. Composes `Source.from_bytes`, `find_functions`, `validate`, `convert_body`, `parameters`, `returns`, `signature_label`, `build_chart`. A `StrayLoopTransfer` from the builder adds `Diagnostic(path, loc.line, "syntax error in '<qualname>'; function skipped", qualname)` and drops the chart. `RecursionError`/`MemoryError` anywhere → `SourceError(path, "code is too deeply nested to chart")`. Warnings are ordered by line; the outside diagnostic first when present.

- [ ] **Step 1: Write the failing tests**

```python
def parse(text, **opts):
    return PythonFrontend().parse(textwrap.dedent(text).encode(), "t.py", ChartOptions(**opts))

def test_broken_neighbour_is_skipped_and_others_charted():
    r = parse("def good():\n    return 1\n\ndef broken(:\n    pass\n\ndef also_good():\n    return 2\n")
    assert [c.qualname for c in r.document.functions] == ["good", "also_good"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(4, "broken")]
    assert str(r.warnings[0]) == "t.py:4: warning: syntax error in 'broken'; function skipped"

def test_nested_error_keeps_outer_chart():
    r = parse("def outer():\n    def inner():\n        x = = 1\n    return 1\n")
    assert [c.qualname for c in r.document.functions] == ["outer"]
    assert "def inner()" in {n.label for n in r.document.functions[0].nodes}

def test_break_outside_loop_is_a_skipped_function():
    r = parse("def f(xs):\n    for x in xs:\n        def g():\n            break\n    return 1\n")
    assert [c.qualname for c in r.document.functions] == ["f"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(4, "f.g")]
    r = parse("def f():\n    continue\n")
    assert r.document.functions == [] and r.warnings[0].line == 2

def test_outside_error_is_one_warning_without_qualname():
    r = parse("x = = 1\ndef g():\n    pass\n")
    assert [c.qualname for c in r.document.functions] == ["g"]
    assert [(w.line, w.qualname) for w in r.warnings] == [(1, None)]
    r = parse("@(\ndef f():\n    pass\n")                      # decorator error: f is still charted
    assert [c.qualname for c in r.document.functions] == ["f"] and len(r.warnings) == 1

def test_metadata_is_complete_and_option_independent():
    for n in (5, 60, 200):
        (c,) = parse('def f(a: list[int] = "a  b") -> dict[str, int]:\n    pass\n', max_label_length=n).document.functions
        assert c.parameters[0].default == '"a  b"' and c.returns == "dict[str, int]"

def test_document_metadata_and_locations():
    raw = b"# -*- coding: latin-1 -*-\ndef f():\n    print('\xe9')\n    # trailing\n"
    r = PythonFrontend().parse(raw, "t.py", ChartOptions())
    c = r.document.functions[0]
    assert (r.document.language, r.document.schema_version) == ("python", 1)
    assert c.nodes[2].label == "print('é')" and c.location.end_line == 3

def test_too_deeply_nested_is_a_source_error():
    deep = "+".join(["1"] * 20000)
    with pytest.raises(SourceError, match="too deeply nested"):
        parse(f"def f():\n    x = {deep}\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_python_frontend.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `frontend.py`**

For each `Found` not in `validation.skipped`: build `FunctionChart(qualname, name, is_async, parameters(...), returns(...), src.location(node), *build_chart(...))`, catching `StrayLoopTransfer`. Return `ParseResult(Document(path, "python", charts), tuple(warnings))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_python_frontend.py -v && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/frontends/python tests/test_python_frontend.py
git commit -m "feat: tree-sitter Python frontend with per-function skipping"
```

---

### Task 11: Switch the registry and the test suite to the new frontend

**Files:**

- Modify: `src/pyflowcharts/frontends/__init__.py` (`FRONTENDS = (PythonFrontend(),)` from `frontends.python`)
- Modify: `tests/conftest.py` (import from `pyflowcharts.frontends.python`)
- Modify: `tests/test_frontend.py`, `tests/test_cfg_try_with.py`, `tests/test_graph_invariants.py`, `tests/test_cli.py` (imports; intentional output changes)

**Interfaces:** none new.

- [ ] **Step 1: Switch imports and run the suite**

Run: `uv run pytest -q 2>&1 | tail -30`
Expected: failures only in the tests listed in Step 2; everything else passes. Any other failure is a bug in Tasks 6–10: write a regression test there and fix it before continuing.

- [ ] **Step 2: Update tests for intentional differences**

In `tests/test_frontend.py`:
- `test_signature_recorded`: start label becomes `def f(a: int, /, b=2, *args, c, d: str = 'x', **kw) -> bool`.
- `test_multiline_labels_fall_back_to_unparse` → rename `test_multiline_labels_keep_source`, expect `g(1, 0x2)`.
- `test_source_errors`: `def f(:` is now a `ParseResult` with one warning (`line == 1`, `qualname == "f"`) and no functions; the null-byte case still raises `SourceError`.
- `test_compiler_only_syntax_errors`: `break`/`continue` cases become warnings with the given line; drop the `nonlocal` case (not checked any more, per spec).
- `test_too_deeply_nested_source_is_a_source_error`: keep the first case; the second (multi-line `ast.unparse` fallback) no longer applies, replace with the test from Task 10.
- `test_registry`: `frontend_for_path(Path("x.PY"))` is the new `PythonFrontend`.

In `tests/test_cli.py::test_bad_file_does_not_stop_others`: expect `f"{bad}:1: warning:"` and exit 1; `good.json` still written.

- [ ] **Step 3: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/pyflowcharts/frontends/__init__.py tests
git commit -m "feat: chart Python through the tree-sitter frontend

Intentional output changes: signatures keep source spacing, multi-line
statements keep their written form, syntax errors in a function skip that
function with a warning instead of failing the file, and compiler-only
errors other than break/continue outside a loop are no longer rejected."
```

---

### Task 12: CLI warnings, exit codes and `--function` with skipped names

**Files:**

- Modify: `src/pyflowcharts/cli.py:51-80`
- Test: `tests/test_cli.py`

**Interfaces:**

- Produces: in `main`, after parsing all files: `available` = charted qualnames + `w.qualname` of warnings with a qualname (in that order per file); with `--function`, unknown names abort listing `available` with skipped ones rendered `name (skipped)`; selected documents keep only wanted charts and only warnings whose `qualname is None or qualname in wanted`; then every remaining warning is printed and makes `status = EXIT_ERROR`; the `no functions found` warning is printed only when a document has no charts *and* no skipped-function warning was printed for it.

- [ ] **Step 1: Write the failing tests**

```python
BROKEN = "def good():\n    return 1\n\ndef broken(:\n    pass\n"

def test_skipped_function_warns_exits_1_and_writes_the_rest(tmp_path, capsys):
    src = write(tmp_path, "m.py", BROKEN)
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "mermaid"]) == 1
    assert f"{src}:4: warning: syntax error in 'broken'; function skipped" in capsys.readouterr().err
    assert [c.qualname for c in from_json((tmp_path / "o/m.json").read_text()).functions] == ["good"]
    assert (tmp_path / "o/m/good.mmd").exists()

def test_all_functions_skipped_writes_empty_json_without_no_functions_warning(tmp_path, capsys):
    src = write(tmp_path, "m.py", "def broken(:\n    pass\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json"]) == 1
    err = capsys.readouterr().err
    assert "function skipped" in err and "no functions found" not in err
    assert from_json((tmp_path / "o/m.json").read_text()).functions == []

def test_function_selection_with_skipped_names(tmp_path, capsys):
    src = write(tmp_path, "m.py", BROKEN)
    assert main([str(src), "-o", str(tmp_path / "o1"), "-f", "json", "--function", "good"]) == 0
    assert capsys.readouterr().err == ""
    assert main([str(src), "-o", str(tmp_path / "o2"), "-f", "json", "--function", "good", "broken"]) == 1
    assert "function skipped" in capsys.readouterr().err
    assert [c.qualname for c in from_json((tmp_path / "o2/m.json").read_text()).functions] == ["good"]
    assert main([str(src), "-o", str(tmp_path / "o3"), "--function", "zzz"]) == 1
    assert "available: good, broken (skipped)" in capsys.readouterr().err and not (tmp_path / "o3").exists()

def test_outside_error_warns_even_with_function_filter(tmp_path, capsys):
    src = write(tmp_path, "m.py", "x = = 1\ndef good():\n    return 1\n")
    assert main([str(src), "-o", str(tmp_path / "o"), "-f", "json", "--function", "good"]) == 1
    assert "syntax error outside functions" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k "skipped or outside"`
Expected: FAIL (wrong exit codes / listings).

- [ ] **Step 3: Implement the CLI changes**

Restructure `main` as: parse files → resolve `--function` (abort on unknown) → filter charts and warnings → print warnings → write → compute status. Keep `_Writer` unchanged.

- [ ] **Step 4: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cli.py tests/test_cli.py
git commit -m "feat: report skipped functions and honour them in --function"
```

---

### Task 13: Comparison run against the stdlib

**Files:**

- Create (scratch, not committed): `/tmp/claude-1000/-home-excali-github-flowcharts/8246d5d3-1444-4970-9c30-6e164357860e/scratchpad/compare.py`
- Possibly modify: `src/pyflowcharts/frontends/python/*.py` with regression tests in the matching `tests/test_python_*.py`

**Interfaces:** uses both `pyflowcharts.frontends.python_ast.PythonFrontend` (still present) and `pyflowcharts.frontends.python.PythonFrontend`.

- [ ] **Step 1: Write the comparison script**

For every `*.py` under `sysconfig.get_paths()["stdlib"]` (skip `test`, `tests`, `lib2to3`, `site-packages`), for `ChartOptions()` and `ChartOptions(show_variables=True)`: parse with both frontends (skip files where the `ast` frontend raises `SourceError`); per qualname compare the `flow()` triple set, the sorted node ID list, each node's `location` and the chart `location`. Print one line per difference category with a count and up to three examples (`file:qualname`), and the total of files, functions, and functions skipped by the new frontend.

- [ ] **Step 2: Run it**

Run: `uv run python /tmp/claude-1000/-home-excali-github-flowcharts/8246d5d3-1444-4970-9c30-6e164357860e/scratchpad/compare.py`
Expected: every function the new frontend skips is explained (the stdlib ships files that are deliberately invalid for the running interpreter), and the only other differences are the intentional ones from Task 11's commit message (label text of multi-line statements and signatures, `with` parentheses). Node IDs and start positions must match everywhere; end positions may differ only where a trailing comment is involved.

- [ ] **Step 3: For every unexplained difference, write a failing regression test, fix, commit**

One `fix:` commit per bug, test first, in the test file of the module at fault.

- [ ] **Step 4: Record the outcome**

Add a short "Comparison run" paragraph to the spec's Migration step 4 noting the date, file/function counts and the difference categories found (`docs:` commit).

---

### Task 14: Remove `python_ast` and update the documentation

**Files:**

- Delete: `src/pyflowcharts/frontends/python_ast/`
- Modify: `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md` (Scope: tree-sitter; Architecture diagram; Labels; Python control-flow mapping references; Errors and exit codes table: per-function warnings, exit 1; remove the `compile()` paragraph; Future work)
- Modify: `AGENTS.md` (architecture diagram with `cfg/`; "Stay within the standard library plus `graphviz`" → plus `tree-sitter` and `tree-sitter-python`; layering rule: `cfg/` imports neither tree-sitter nor `frontends/`; replace `frontends/python_ast/` references; add the `break`/`continue` and syntax-error behaviour to Known simplifications or Rules)
- Modify: `README.md` (installation note that no extra system dependency is needed for parsing; exit code table row for syntax warnings; a sentence on skipped functions)

- [ ] **Step 1: Delete the old frontend and confirm nothing imports it**

```bash
git rm -r src/pyflowcharts/frontends/python_ast
grep -rn "python_ast" src tests docs AGENTS.md README.md
```

Expected: grep finds only the two spec documents' historical mentions (main spec gets updated in Step 2) and the plan files.

- [ ] **Step 2: Update the main spec, AGENTS.md and README as listed**

- [ ] **Step 3: Run the whole suite and lint**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all PASS.

- [ ] **Step 4: Commit and open the PR**

```bash
git add -A
git commit -m "refactor: remove the ast frontend and document the tree-sitter frontend"
git push -u origin feat/tree-sitter-frontend
gh pr create --title "Tree-sitter Python frontend" --body-file -
```

PR body: goal, the intentional output differences, the new warning/exit-code behaviour, and the comparison-run summary, ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
