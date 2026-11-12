# Exception Edges and `return`/`raise` Through `finally` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw an `exception` edge from every node inside a `try` body to its handlers, and run the finally body for `return` and for propagating exceptions, using the existing finally-copy machinery.

**Architecture:** `ChartBuilder` gains a stack of exception scopes; `add_node` attaches an `exception` edge per scope target to every statement node it creates. `emit_try` pushes scopes for the body (targets: handler nodes) and for `else`/handlers (target: a pending frontier), and draws two new finally copies, `finally (return)` and `finally (exception)`, next to the existing `break`/`continue` copies. Backends draw `exception` edges dashed. No IR change.

**Tech Stack:** Python 3.12, stdlib dataclasses, `graphviz`, pytest via `uv`.

**Spec:** `docs/superpowers/specs/2026-11-13-exception-edges-design.md`

## Global Constraints

- `cfg/` imports nothing from `frontends/` or tree-sitter; backends import only the IR.
- Node IDs stay `{qualname}#L{line}C{col}[~suffix][~copy@L{line}C{col}]`, unique per chart, never containing `:`. New copy suffixes: `~return@L{line}C{col}` and `~exception@L{line}C{col}`, naming the owning `try`.
- No `SCHEMA_VERSION` bump; the IR does not change.
- Output stays deterministic: edges are appended in creation order, never from sets.
- CFG tests assert on `flow(chart)` triples from `tests/conftest.py`; `uv run pytest` and `uv run ruff check` pass before each commit.
- Branch: `feat/exception-edges` (already created, spec committed). Conventional Commit messages ending with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

- A `try` with a `finally` but no handlers, whose body only `pass`es: nothing points at any finally copy, so the chart must have no finally node at all and no dangling edge (Task 2 test `test_try_finally_with_empty_body_draws_no_finally`).
- `return` inside a `for` loop inside `try … finally`: the return must go through `finally (return)` to `end` and must not be routed like a `break` (Task 4 test `test_return_in_loop_inside_try_finally`).
- A `raise` in a finally body of a top-level `try`: no scope is active any more, so it must go to `end` (Task 3 test `test_raise_in_finally_body_goes_to_end`).
- Two handlers plus a `finally`: handler nodes themselves point at `finally (exception)`, so a handler whose body is empty still flows there (Task 2 test `test_handler_nodes_point_at_finally_exception`).
- Nested finally copies: a `return` passing two nested `try … finally` blocks gets one copy per try (`…~return@L<inner>`, `…~return@L<outer>`), and a `try` inside a finally body stacks suffixes (`…~return@L<a>~exception@L<b>`); all unique and `:`-free (Task 4 test, plus the invariants corpus in Task 6).

---

### Task 1: Per-node exception edges to handlers

**Files:**

- Modify: `src/pyflowcharts/cfg/builder.py` (`ChartBuilder.__init__`, `add_node`, new `node_id`, new `exception_scope`)
- Modify: `src/pyflowcharts/cfg/finally_.py` (new `ExceptionScope`, `emit_try`)
- Test: `tests/test_builder.py`, `tests/test_cfg_try_with.py`

**Interfaces:**

- Produces in `builder.py`:
  - `ChartBuilder.scopes: list[ExceptionScope]`
  - `ChartBuilder.node_id(self, loc: SourceLocation, suffix: str = "") -> str` returns `f"{self.qualname}#L{loc.line}C{loc.column}{suffix}{self.copy_suffix}"`; `add_node` uses it.
  - `ChartBuilder.exception_scope(self, scope: ExceptionScope | None) -> contextmanager` pushes `scope` onto `self.scopes` for the block and pops it after; `None` pushes nothing.
  - `add_node` attaches `[(node_id, "exception")]` to `self.scopes[-1]` (if any) when `suffix == ""` (statement nodes only, never synthetic finally nodes).
- Produces in `finally_.py`:
  - `@dataclass class ExceptionScope: handler_ids: list[str]; pending: Frontier | None` with `attach(self, builder: ChartBuilder, frontier: Frontier) -> None`: with `handler_ids`, append `Edge(source, handler_id, label)` for every frontier entry and every handler (frontier order outer, handler order inner); otherwise `pending.extend(frontier)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_builder.py`, replace the expected set of `test_try_except_else_finally` (the `("try", "except E", "exception")` line becomes `("load()", "except E", "exception")`) and of `test_no_finally_clause` (becomes `("a()", "except", "exception")`), then add:

```python
def test_every_body_node_points_at_every_handler():
    body = (
        try_stmt(
            2,
            (Branch("if x", at(3), (Arm("True", (Step("a()", at(4)),)),), "False"),),
            (Handler("except A", at(5), ()), Handler("except B", at(6), ())),
        ),
    )
    f = flow(chart(body))
    assert {(s, h, "exception") for s in ("if x", "a()") for h in ("except A", "except B")} <= f
    assert not any(s == "try" and lbl == "exception" for s, _, lbl in f)


def test_nested_try_body_points_only_at_inner_handlers():
    inner = try_stmt(3, (Step("a()", at(4)),), (Handler("except I", at(5), (Step("h()", at(6)),)),))
    outer = try_stmt(2, (inner,), (Handler("except O", at(7), ()),))
    f = flow(chart((outer,)))
    assert ("a()", "except I", "exception") in f and ("a()", "except O", "exception") not in f
    assert {("except I", "except O", "exception"), ("h()", "except O", "exception")} <= f
    assert ("try", "except O", "exception") in f  # the inner try node is a statement of the outer body


def test_try_pass_leaves_handlers_unreachable():
    c = chart((try_stmt(2, (), (Handler("except E", at(3), ()),)),))
    assert not any(t == "except E" for _, t, _ in flow(c))
```

In `tests/test_cfg_try_with.py::test_try_except_else_finally`, replace the two `("try", "except …", "exception")` entries with `("data = load(path)", "except (OSError, ValueError) as e", "exception")` and `("data = load(path)", "except Exception", "exception")`. (This test changes again in Tasks 2 and 3; update it incrementally.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder.py tests/test_cfg_try_with.py -v`
Expected: the four new/changed builder tests and the try_with test FAIL on the exception edges.

- [ ] **Step 3: Implement**

In `builder.py`: add `self.scopes`, `node_id`, `exception_scope` (use `contextlib.contextmanager`), and the attach call at the end of `add_node`. Import `ExceptionScope` from `finally_` (it already imports `FinallyContext`).

In `finally_.py`: add `ExceptionScope`. In `emit_try`, compute `handler_ids = [builder.node_id(h.loc) for h in stmt.handlers]` before the body, run `builder.block(stmt.body, …)` inside `builder.exception_scope(ExceptionScope(handler_ids, None) if handler_ids else None)`, and delete the `builder.connect([(try_id, "exception")], handler_id)` line. The handler nodes are still created after the body; their IDs are known up front.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check`
Expected: all pass. `tests/test_graph_invariants.py` must stay green (edges may reference nodes appended later; `assert_graph_integrity` checks the final lists).

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg tests/test_builder.py tests/test_cfg_try_with.py
git commit -m "feat(cfg): draw exception edges from each try-body node to its handlers"
```

---

### Task 2: `finally (exception)` copy

**Files:**

- Modify: `src/pyflowcharts/cfg/finally_.py` (`FinallyContext`, `emit_try`, the copy loop)
- Modify: `src/pyflowcharts/cfg/builder.py` (new `route_exception`)
- Test: `tests/test_builder.py`, `tests/test_cfg_try_with.py`

**Interfaces:**

- `FinallyContext` gains `exceptions: Frontier` (and, for Task 4, `returns: Frontier`; add both fields now, in the order `breaks, continues, returns, exceptions`).
- `ChartBuilder.route_exception(self, frontier: Frontier) -> None`: `self.scopes[-1].attach(self, frontier)` if a scope is active, else `self.connect(frontier, self.end_id)`.
- In `emit_try`: body scope is `ExceptionScope(handler_ids, None)` when there are handlers, else `ExceptionScope([], context.exceptions)`. The `else` body and every handler (node and body) run inside `ExceptionScope([], context.exceptions)` when `stmt.finalbody is not None`, else inside no new scope. Push the handler scope before `add_node` for the handler.
- The copy loop becomes a tuple of `(kind, pending, route)` with `route: Callable[[Frontier], None]`, using `functools.partial(builder.route_break, loc=stmt.loc)` and the same for `continue`, plus `("exception", context.exceptions, builder.route_exception)`. Copy suffix `f"~{kind}@L{line}C{col}"` and label `f"finally ({kind})"` are unchanged in form. A copy is drawn only when its pending frontier is non-empty (already true for break/continue).

- [ ] **Step 1: Write the failing tests**

```python
def test_try_finally_without_handlers_draws_exception_copy():
    body = (try_stmt(2, (Step("a()", at(3)),), finalbody=(Step("c()", at(5)),)), Step("after()", at(6)))
    c = chart(body)
    f = flow(c)
    assert {("a()", "finally (exception)", "exception"), ("finally (exception)", "c()", None)} <= f
    assert ("c()", "end", None) in f and ("c()", "after()", None) in f
    assert {"f#L2C4~finally", "f#L2C4~finally~exception@L2C4", "f#L5C4~exception@L2C4"} <= {n.id for n in c.nodes}


def test_handler_nodes_point_at_finally_exception():
    body = (
        try_stmt(
            2,
            (Step("a()", at(3)),),
            (Handler("except A", at(4), ()), Handler("except B", at(5), (Step("h()", at(6)),))),
            (Step("e()", at(8)),),
            (Step("c()", at(10)),),
        ),
    )
    f = flow(chart(body))
    for src in ("except A", "except B", "h()", "e()"):
        assert (src, "finally (exception)", "exception") in f
    assert ("a()", "finally (exception)", "exception") not in f


def test_finally_exception_chains_to_outer_handlers():
    inner = try_stmt(3, (Step("a()", at(4)),), finalbody=(Step("c()", at(6)),))
    outer = try_stmt(2, (inner,), (Handler("except O", at(7), ()),))
    f = flow(chart((outer,)))
    assert ("c()", "except O", None) in f  # propagation keeps the frontier's own label
    assert ("c()", "end", None) in f  # the normal copy continues to the next statement


def test_try_finally_with_empty_body_draws_no_finally():
    c = chart((try_stmt(2, (), finalbody=(Step("c()", at(4)),)),))
    labels = {n.label for n in c.nodes}
    assert "finally (exception)" not in labels and "finally" in labels
```

In `tests/test_cfg_try_with.py::test_try_except_else_finally`, add `("except (OSError, ValueError) as e", "finally (exception)", "exception")`, `("log(e)", "finally (exception)", "exception")`, `("return None", "finally (exception)", "exception")`, `("except Exception", "finally (exception)", "exception")`, `("raise", "finally (exception)", "exception")`, `("use(data)", "finally (exception)", "exception")`, `("finally (exception)", "cleanup()", None)`, and `("cleanup()", "end", None)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_builder.py tests/test_cfg_try_with.py -v`
Expected: the five tests FAIL (no `finally (exception)` node).

- [ ] **Step 3: Implement** per the Interfaces block. Note that `_finally_copy` creates nodes with the body's own `add_node`, so the copy's body nodes pick up the enclosing scope automatically because the try's scopes are popped before the copies are drawn.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg tests/test_builder.py tests/test_cfg_try_with.py
git commit -m "feat(cfg): run the finally body on the exception path"
```

---

### Task 3: `raise` as a raising node

**Files:**

- Modify: `src/pyflowcharts/cfg/builder.py` (`_stmt`, `Terminal` arm)
- Test: `tests/test_builder.py`, `tests/test_cfg_try_with.py`

**Interfaces:**

- In the `Terminal` arm: after `add_node` and `connect(frontier, node_id)`, if `kind is NodeKind.RAISE and self.scopes` return `[]` without an edge to `end` (the exception edges were attached by `add_node`). Otherwise connect to `end` as today (Task 4 changes the `RETURN` case).

- [ ] **Step 1: Write the failing tests**

```python
def test_raise_in_try_body_goes_to_handler_not_end():
    body = (try_stmt(2, (Terminal(NodeKind.RAISE, "raise E", at(3)),), (Handler("except E", at(4), ()),)),)
    f = flow(chart(body))
    assert ("raise E", "except E", "exception") in f and ("raise E", "end", None) not in f


def test_reraise_in_handler_goes_outward():
    inner = try_stmt(3, (Step("a()", at(4)),), (Handler("except I", at(5), (Terminal(NodeKind.RAISE, "raise", at(6)),)),))
    outer = try_stmt(2, (inner,), (Handler("except O", at(7), ()),))
    f = flow(chart((outer,)))
    assert ("raise", "except O", "exception") in f and ("raise", "end", None) not in f


def test_raise_outside_try_goes_to_end():
    f = flow(chart((Terminal(NodeKind.RAISE, "raise E", at(2)),)))
    assert ("raise E", "end", None) in f


def test_raise_in_finally_body_goes_to_end():
    body = (try_stmt(2, (Step("a()", at(3)),), finalbody=(Terminal(NodeKind.RAISE, "raise E", at(5)),)),)
    f = flow(chart(body))
    assert ("raise E", "end", None) in f and not any(s == "raise E" and lbl == "exception" for s, _, lbl in f)
```

In `tests/test_cfg_try_with.py::test_try_except_else_finally`, remove `("raise", "end", None)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_builder.py tests/test_cfg_try_with.py -v`
Expected: the first two new tests and the try_with test FAIL; the other two already pass.

- [ ] **Step 3: Implement** the `Terminal` arm change.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg/builder.py tests/test_builder.py tests/test_cfg_try_with.py
git commit -m "feat(cfg): route raise through the enclosing handlers and finally"
```

---

### Task 4: `finally (return)` copy, and no empty plain copy

**Files:**

- Modify: `src/pyflowcharts/cfg/builder.py` (new `route_return`, `Terminal` arm)
- Modify: `src/pyflowcharts/cfg/finally_.py` (copy loop, plain copy condition)
- Test: `tests/test_builder.py`, `tests/test_cfg_try_with.py`

**Interfaces:**

- `ChartBuilder.route_return(self, frontier: Frontier) -> None`: if `self.pending`, `self.pending[-1].returns.extend(frontier)`; else `self.connect(frontier, self.end_id)`. No loop-depth condition.
- `Terminal` arm, `RETURN` kind: `self.route_return([(node_id, None)])` instead of connecting to `end`.
- Copy loop gains `("return", context.returns, builder.route_return)` between `continue` and `exception`.
- The plain copy: `result = _finally_copy(builder, stmt, normal, "finally") if normal else []`.

- [ ] **Step 1: Write the failing tests**

```python
def test_return_runs_finally_return_copy_and_omits_plain_copy():
    body = (try_stmt(2, (Terminal(NodeKind.RETURN, "return 1", at(3)),), finalbody=(Step("c()", at(5)),)),)
    c = chart(body)
    f = flow(c)
    assert {("return 1", "finally (return)", None), ("finally (return)", "c()", None), ("c()", "end", None)} <= f
    assert ("return 1", "end", None) not in f and "finally" not in {n.label for n in c.nodes}
    assert {"f#L2C4~finally~return@L2C4", "f#L5C4~return@L2C4"} <= {n.id for n in c.nodes}


def test_return_through_two_nested_finally_blocks():
    inner = try_stmt(3, (Terminal(NodeKind.RETURN, "return 1", at(4)),), finalbody=(Step("ci()", at(6)),))
    outer = try_stmt(2, (inner,), finalbody=(Step("co()", at(8)),))
    c = chart((outer,))
    f = flow(c)
    assert {("ci()", "finally (return)", None), ("co()", "end", None)} <= f
    assert {"f#L6C4~return@L3C4", "f#L8C4~return@L2C4"} <= {n.id for n in c.nodes}


def test_return_in_loop_inside_try_finally():
    loop = Loop("for x in xs", at(3), "next", "done", (Terminal(NodeKind.RETURN, "return x", at(4)),), ())
    body = (try_stmt(2, (loop,), finalbody=(Step("c()", at(6)),)),)
    f = flow(chart(body))
    assert ("return x", "finally (return)", None) in f and ("c()", "end", None) in f
    assert ("c()", "for x in xs", None) not in f


def test_finally_body_return_overrides_pending_return():
    body = (try_stmt(2, (Terminal(NodeKind.RETURN, "return 1", at(3)),), finalbody=(Terminal(NodeKind.RETURN, "return 2", at(5)),)),)
    f = flow(chart(body))
    assert ("return 2", "end", None) in f and ("return 1", "end", None) not in f
```

In `tests/test_cfg_try_with.py::test_try_except_else_finally`, replace `("return None", "end", None)` with `("return None", "finally (return)", None)`, `("finally (return)", "cleanup()", None)`; `("cleanup()", "end", None)` is already present from Task 2. Update `test_empty_finalbody_still_gets_a_node` only if it breaks (it should not: its body completes normally).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_builder.py tests/test_cfg_try_with.py -v`
Expected: the four new tests and the try_with test FAIL.

- [ ] **Step 3: Implement** per the Interfaces block.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/cfg tests/test_builder.py tests/test_cfg_try_with.py
git commit -m "feat(cfg): run the finally body before return and drop unreachable finally copies"
```

---

### Task 5: Dashed exception edges in DOT and Mermaid

**Files:**

- Modify: `src/pyflowcharts/backends/dot.py` (`to_digraph` edge loop)
- Modify: `src/pyflowcharts/backends/mermaid.py` (`to_mermaid` edge loop)
- Test: `tests/test_dot.py`, `tests/test_mermaid.py`

**Interfaces:**

- DOT: edges with `edge.label == "exception"` get `style="dashed"`; other edges unchanged.
- Mermaid: arrow `-.->|"exception"|` for those edges, `-->` / `-->|"label"|` otherwise.

- [ ] **Step 1: Write the failing tests**

```python
TRY_SRC = "def f():\n    try:\n        a()\n    except E:\n        h()\n"

# tests/test_dot.py
def test_exception_edges_are_dashed():
    src = to_dot(chart_of(TRY_SRC))
    dashed = [line for line in src.splitlines() if "style=dashed" in line]
    assert len(dashed) == 1 and "label=exception" in dashed[0]

# tests/test_mermaid.py
def test_exception_edges_are_dashed():
    out = to_mermaid(chart_of(TRY_SRC))
    assert out.count('-.->|"exception"|') == 1 and '-->|"exception"|' not in out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_dot.py tests/test_mermaid.py -v`
Expected: both new tests FAIL.

- [ ] **Step 3: Implement** the two edge-loop changes.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check`
Expected: all pass (`test_deterministic` and `test_renders_whole_fixture` still green; the SVG test is skipped without `dot`).

- [ ] **Step 5: Commit**

```bash
git add src/pyflowcharts/backends tests/test_dot.py tests/test_mermaid.py
git commit -m "feat(backends): draw exception edges dashed"
```

---

### Task 6: Invariants corpus and documentation

**Files:**

- Modify: `tests/test_graph_invariants.py` (`CORPUS`)
- Modify: `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md` ("Stable node IDs" rule, `try` bullet, "Known simplifications", the "Out of scope" line about exact exception edges)
- Modify: `AGENTS.md` ("IR and JSON format" node-ID rule, "Known simplifications")

- [ ] **Step 1: Add corpus entries** (they are integrity tests, so they pass as soon as they are added; run them anyway)

```python
    "return_and_raise_through_nested_finally": """
        def f():
            try:
                try:
                    if a:
                        return 1
                    raise E
                except E:
                    raise
                finally:
                    c1()
            except F:
                return 2
            finally:
                c2()
    """,
    "return_in_loop_in_try_finally_in_loop": """
        def f():
            while a:
                try:
                    for i in x:
                        if i:
                            return i
                        if j:
                            break
                        continue
                finally:
                    c()
    """,
```

Run: `uv run pytest tests/test_graph_invariants.py -v`
Expected: PASS for both new names.

- [ ] **Step 2: Update the main spec**

- "Out of scope": delete `- Exact exception edges (see "Known simplifications").`
- "Stable node IDs": list the copy suffixes as `~break@…`, `~continue@…`, `~return@…`, `~exception@…`.
- `try` bullet: replace with: a `try` node, then the body. Every node in the body has an `exception` edge to each `except` handler node (the `try` node itself has none). `else` follows the body. Handler and `else` nodes point at the `finally (exception)` copy if there is a `finally`, else at the enclosing `try`'s handlers. A `raise` inside a `try` is drawn only through those exception edges. With a `finally`, the finally body is drawn once per path that reaches it (`finally`, `finally (break)`, `finally (continue)`, `finally (return)`, `finally (exception)`), each continuing to its own target: the next statement, the loop exit, the loop head, `end`, or the enclosing handlers. Copies nobody reaches are not drawn. A finally body that ends the path itself overrides the pending transfer. `except*` works the same way.
- "Known simplifications": replace the paragraph with: handlers are assumed to catch whatever reaches them, so the uncaught path out of a `try` that has handlers is not drawn; and the `try` node itself has no exception edges, so a `try` whose body has no nodes leaves its handlers unreachable.

- [ ] **Step 3: Update AGENTS.md**

Node-ID rule: `(duplicated finally bodies add ~break@L{line}C{col}, ~continue@…, ~return@… or ~exception@… naming the owning try)`. "Known simplifications": replace the first two bullets with one: `Handlers are assumed to catch whatever reaches them: the uncaught path out of a try with handlers is not drawn, and the try node itself has no exception edges.` Keep the remaining two bullets.

- [ ] **Step 4: Verify**

Run: `uv run pytest -q && uv run ruff check && uv run pyflowcharts tests/fixtures/sample.py -o /tmp/claude-1000/-home-excali-github-flowcharts/6560237b-242c-402e-847f-5b2c33252bfe/scratchpad/out -f dot`
Expected: tests pass; the CLI exits 0.

- [ ] **Step 5: Commit**

```bash
git add tests/test_graph_invariants.py docs/superpowers/specs/2026-11-11-python-flowcharts-design.md AGENTS.md
git commit -m "docs: describe per-statement exception edges and finally copies for return and exceptions"
```
