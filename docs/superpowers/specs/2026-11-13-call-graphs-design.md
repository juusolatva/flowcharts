# Call graphs: design

Status: approved in brainstorming on 2026-11-13. Extends `2026-11-11-python-flowcharts-design.md` (the "main spec"). Where they disagree, this document wins, and the last implementation step folds it into the main spec.

## Goal

Record which functions each chart calls, and draw one call graph per run.

- **Navigation:** every call is stored in the JSON with the chart node it belongs to and, when it can be resolved, the chart it calls. The future GUI can then jump from a call to the called function's flowchart.
- **Structure:** a single picture per run shows every charted function and the resolved calls between them, clustered by file.

Success means `pyflowcharts src/` writes `OUTDIR/callgraph.svg` with edges across files (for this repository, `cli.main` → `inputs.expand`), each file's JSON lists its calls with resolved targets, and output stays deterministic.

## Decisions

| Question | Decision |
|---|---|
| Purpose | Both: call data in the IR for navigation, and a picture. |
| Resolution scope | Within the file, and through `import` / `from … import` (absolute and relative) to other files in the same run. Static and best-effort. |
| Where resolution happens | The frontend produces candidate references; a language-neutral linker matches them against the run. |
| Pictures | One per run, `OUTDIR/callgraph.<ext>`, clustered by file. No per-file call graphs. |
| Default | On. `--no-call-graph` turns the picture off; the JSON always carries the call data. |
| IR | `CallRef`, `Call`, `Chart.calls`, `Document.module_name`. `SCHEMA_VERSION` becomes 3. `Node` is unchanged. |

## IR and JSON

`ir.py`:

```python
@dataclass(frozen=True)
class CallRef:
    module: str     # dotted module name, e.g. "pkg.io.load"
    qualname: str   # chart qualname in that module, e.g. "Loader.run"

@dataclass(frozen=True)
class Call:
    node: str                    # id of the chart node the call is written in
    text: str                    # the callee's source text, e.g. "self.load", "json.dumps"
    candidates: list[CallRef]    # where it may go, most likely first, no duplicates; [] if unknown
    target: CallRef | None       # the first candidate charted in this run, set by the linker

@dataclass
class Chart:
    qualname: str
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]
    calls: list[Call] = field(default_factory=list, kw_only=True)

@dataclass
class Document:
    source: str
    language: str
    functions: list[FunctionChart]
    module_name: str = ""        # e.g. "pkg.io.load"
    module: Chart | None = None
    schema_version: int = SCHEMA_VERSION  # 3
```

- `Chart.calls` is keyword-only with a default, so `FunctionChart(Chart)` can still add its required fields and existing constructors keep working. `asdict` keeps definition order, so a chart's JSON keys become `qualname`, `location`, `nodes`, `edges`, `calls`, then a function chart's signature fields.
- `Call` is frozen but holds a list, so it is not hashable; nothing needs to hash it.
- `calls` are ordered by node (in `nodes` order), then by source position within a node. Nested calls are in pre-order: for `a().b()`, the outer call (`text` `a().b`) comes before the inner one (`a`).
- `from_json` accepts versions 1, 2 and 3 and keeps the version it read. Versions 1 and 2 are read with `module_name = ""` and `calls = []` on every chart. The error message becomes `unsupported schema_version X (expected 1, 2 or 3)`.
- `candidates` stay in the JSON even when `target` is set. They show what resolution tried, and let a later GUI link calls into modules outside the run (e.g. the standard library).

## Which node owns a call

A call belongs to the chart node of the statement it is written in:

| Statement | Node |
|---|---|
| expression statement, shown assignment (`g(x)`, `x = load()`) | its process node |
| `if` / `elif` condition | that decision node (each `elif` is its own decision node) |
| `match` subject and `case` guards | the `match` decision node |
| `for` iterable, `while` condition | the loop node |
| `return …`, `raise …` | the return or raise node |
| `with` items | the `with` node |
| `except` expression | the handler node |
| a `def` (nested, or top-level in a module chart): calls in its decorators (`@deco(f())`; a bare `@deco` is not a call), parameter defaults and annotations, and return annotation | the `def` process node of the enclosing chart (they run when that chart reaches the `def`) |
| a `class` (nested, or top-level in a module chart): calls in its decorators, bases and keyword arguments, class-body statements, nested classes, and its methods' decorators, defaults and annotations | the `class` process node of the enclosing chart |
| lambdas, comprehensions, generator expressions | the enclosing statement's node |

- Calls inside a function's body belong to that function's chart, never to the parent. Concretely, a `class` node's calls come from its whole `class_definition` subtree (and the `decorated_definition` wrapper's decorators), stopping at the `body` of each `function_definition` inside it.
- Top-level `def`/`class` statements own calls only when the file has a module chart; without one they have no node, and their decorator, default and class-body calls are not recorded.
- Calls are extracted from the source nodes, not from labels, so `--no-returns` and `--no-parameters` do not change them.
- **Hidden steps record no calls.** A hidden step gets no node, so its calls have nothing to belong to. Assignments whose final value contains a call are always shown, but an assignment whose only calls are in its targets or annotation (`x[g()] = 1`, `x: Ann[g()] = 1`, `x[g()] += 1`) stays hidden, as today, and its calls are recorded only when `--variables` or the reveal rule shows it. This is the one way a display option changes `calls`, and it follows from the option changing which nodes exist.
- A statement inside a `finally` body that is drawn several times records its calls on every copy node, each `Call` naming its copy's node id.
- The `try` node itself, `else`/`finally` markers, `start` and `end` own no calls.
- `text` is the callee expression's source text (the `function` field of the tree-sitter `call` node), produced with `Source.source_text`, never truncated.

## Model and builder (`cfg/`)

- `cfg/model.py` gets `@dataclass(frozen=True) class CallSite(text: str, candidates: tuple[CallRef, ...])`. It imports `CallRef` from `ir.py`.
- `Step`, `Branch`, `Loop`, `Handler` and `Terminal` get `calls: tuple[CallSite, ...] = ()` as their last field.
- `ChartBuilder.add_node` takes an optional `calls: tuple[CallSite, ...] = ()` and records one `Call(node_id, text, list(candidates), None)` per site for the node it creates. Every call of `add_node` for those statements passes the statement's calls, including the handler nodes in `cfg/finally_.py`. Finally copies need no extra plumbing: `_finally_copy` re-emits the body through `builder.block`, which calls `add_node` again with the copy's suffix.
- `build_chart` returns `(nodes, edges, calls)`.
- `cfg/` stays language-neutral: it imports nothing from tree-sitter or `frontends/`.

## Frontend protocol and module names

- `Frontend.parse(source: bytes, path: str, options: ChartOptions, key: PurePosixPath | None = None) -> ParseResult`. The CLI passes the output key from `inputs.py`. When `key` is omitted (tests, direct callers), it defaults to `PurePosixPath(PurePath(path).stem)`, the key of an explicitly named file.
- The Python frontend derives `module_name` from the key: its parts joined with `.`, with a final `__init__` dropped (`pkg/io/load` → `pkg.io.load`, `pkg/__init__` → `pkg`). A key `__init__` on its own (an explicitly named `__init__.py`) gives `module_name = ""`.
- The resolver also needs the file's **package**, which the module name alone does not give (`pkg.py` and `pkg/__init__.py` both have module name `pkg`): the key's parent parts, or all of the module name's parts for an `__init__` key. `pkg/io/load` → package `("pkg", "io")`; `pkg/io/__init__` → `("pkg", "io")`; `a` → `()`.
- Module names depend on which directory is walked: for absolute imports to resolve, walk the directory that is the import root (`pyflowcharts src/`, not `pyflowcharts src/pyflowcharts/`, for a `src` layout). This is documented in the README.

## Resolution rules (Python frontend)

The resolver lives in `frontends/python/calls.py`. It is static and best-effort and never raises: anything not covered gives `candidates = []`. "Own" means the file's `module_name`. Candidates are deduplicated, keeping the first occurrence. When the module name is empty (an explicitly named `__init__.py`), no candidate in the own module is produced, since `""` is not a module name; import candidates are unaffected.

### Scopes and bindings

The resolver builds one table of bindings per **scope**: the module, and each function. A scope's bindings are:

- **definitions**: the `def`s and `class`es directly in it (including inside its `if`/`try`/`with`/loop blocks, but not inside nested functions or classes), each mapped to its qualname (`outer.inner`, `outer.C`). Definitions come from discovery, so they include functions skipped for syntax errors; calls to those still resolve to a candidate, and stay unresolved only because the linker does not index them.
- **imports** in it (same block rule): each bound name maps to a list of import bindings in source order, so `try: import a` / `except ImportError: import b as a` keeps both. A binding is one of:
  - `from m import n` → binds `n` to *name* `(m, n)`; `from m import n as a` binds `a` to the same.
  - `import x.y.z` → binds `x` to *module* `x`, and records the dotted prefixes `x.y` and `x.y.z` as modules reachable through `x`.
  - `import x.y as z` → binds `z` to *module* `x.y` only (not `x`).
  - `from __future__ import …` and `from m import *` bind nothing.
  - Relative imports: `from .m import n`, `from . import n`, `from ..a import b`. One leading dot means the package itself; each extra dot drops one part from the end of the package. If there are more dots than package parts (e.g. `from .. import x` in `pkg/a.py`, package `("pkg",)`; `from . import x` in a top-level `a.py`, package `()`), the import is above the top and binds nothing. `from . import n` binds `n` to *name* `(package, n)`, and `from .m import n` to `(package.m, n)`.

The **scope chain** of a call is the function scopes enclosing the node that owns it, innermost first, then the module. It is decided by the owning node, not by the call's position in the tree: a default `def inner(x=helper())` inside `outer` is owned by `outer`'s `def inner` node, so its chain starts at `outer`. A call owned by chart `Q` starts at `Q`'s own scope (so `outer` calling `inner()` finds `outer.inner`). Class bodies are never in the chain, as in Python.

### Bare name `n(…)`

Walk the scope chain. In the first scope that binds `n`:

- a `def` → `(own, qualname)`;
- a `class` → `(own, qualname.__init__)`;
- import bindings → for each, in source order: a *name* `(m, x)` gives `(m, x)` then `(m, x.__init__)`; a *module* gives nothing (modules are not called).

Outer scopes are not consulted once a scope binds `n` (Python's lookup stops there), so a function-local `from other import foo` shadows a module-level `def foo`. A scope may bind `n` both by a definition and by imports; then the definition comes first, then the imports in source order. Nothing found → `[]` (builtins, runtime names).

### Attribute calls `a.b.….m(…)`

Split the callee chain `a.b.….m` at its first part `a`:

- **`self.m(…)` / `cls.m(…)`**, exactly two parts, in a function defined directly in a class body: `(own, C.m)` where `C` is that class's full qualname (`outer.C` for a class inside `outer`). Longer chains (`self.x.m()`) give nothing. Base classes are not followed.
- Otherwise look up `a` along the scope chain as for a bare name. In the first scope that binds `a`:
  - a `class` with qualname `C` → `(own, C.rest)`, where `rest` is the chain after `a` (`C.m`, `C.Inner.m`);
  - a `def` → nothing;
  - import bindings, each in source order:
    - *module* `x` from `import x.y.z`: the longest recorded module prefix that is a proper prefix of the chain (`x.y.z`, `x.y`, then `x`) wins; the rest is the qualname: `x.y.f()` → `(x.y, f)`; `x.f()` → `(x, f)`; `x.y()` → nothing (a module is not called).
    - *module* `x.y` from `import x.y as z`: `z.f()` → `(x.y, f)`; `z.C.m()` → `(x.y, C.m)`.
    - *name* `(m, x)` from `from m import x [as a]`: `x` may be a submodule or a name in `m`, so `a.rest(…)` gives `(m.x, rest)` then `(m, x.rest)`, using the original name `x`, not the alias. (`from . import x` in package `p`: `(p.x, rest)` then `(p, x.rest)`.)
- A chain that does not start with a plain identifier (calls on call results, subscripts, literals) gives nothing.

### Not handled (documented limits)

Shadowing by local assignment (`f = other; f()` still resolves to `def f`), inheritance, decorators that replace a function, `getattr` and other dynamic calls, star imports, `global`/`nonlocal` rebinding, and calls through instance attributes other than `self.m`/`cls.m`. Duplicate qualnames (`A.x@L9`) resolve to the first definition (`A.x`).

## Linker (`calls.py`)

- New language-neutral module `src/pyflowcharts/calls.py`: `link(documents: list[Document]) -> list[Document]`.
- It indexes every function chart as `(document.module_name, chart.qualname)`. Module charts are not indexed, so they are never targets. Documents with `module_name == ""` are not indexed. A module name shared by several documents (possible: `a.b.py` beside `a/b.py`) is ambiguous: none of its charts are indexed, so the result never depends on document order.
- It returns new documents (`dataclasses.replace`) in which each call's `target` is its first candidate found in the index, or `None`. This covers the calls of function charts and of the module chart.
- The CLI calls it after parsing every file and before `--function` selection, so targets cover the whole run even when only some charts are written.

## Picture (`backends/callgraph.py`)

- `to_callgraph_digraph(documents: list[Document]) -> graphviz.Digraph`, `to_callgraph_dot(documents) -> str`, `render_callgraph(documents, fmt: Literal["svg", "png"]) -> bytes`, `to_callgraph_mermaid(documents) -> str`.
- **Clusters:** one per document that has at least one chart, in input order; documents without charts are left out (no empty cluster). DOT subgraphs are named `cluster_{i}` by document index; Mermaid subgraphs get generated ids (`s0`, `s1`, …) so a module named like a keyword (`end`) cannot break them. The cluster label is the document's `module_name`, or its `source` when the module name is empty.
- **Nodes:** one per chart: function charts in document order, then the module chart if any. A node is labelled with its qualname; the module chart shows as `<module>`. DOT node IDs are `{i}#{qualname}` (document index and qualname; qualnames never contain `:`), so they are unique even when two documents share a module name and never contain a path. Mermaid node ids are generated (`n0`, `n1`, …). DOT labels go through `graphviz.escape`, which also stops `<module>` from being read as HTML; Mermaid labels go through the flowchart backend's escaping. The graph name is passed through `graphviz.nohtml`.
- **Edges:** one per (caller chart, target chart) pair with at least one resolved call whose target chart is among the drawn nodes, without labels. A recursive call draws a self-loop. Unresolved calls, and calls whose target was filtered out by `--function`, are not drawn.
- `rankdir=LR`. Order is deterministic: documents in input order, charts in document order, edges sorted by (caller id, target id).

## CLI and output

- After parsing, `cli.py` calls `link`, then selects (`--function`), then writes.
- `OUTDIR/callgraph.<ext>` is written once per run for each selected format among `dot`, `svg`, `png` and `mermaid`. With only `json` selected no picture is written; the call data is still in each file's JSON.
- It is written for a single-file run too. It is not written when no document has a chart left after selection.
- With `--function`, the picture shows only the selected charts and the edges between them. The JSON keeps each selected chart's full `calls`, with targets anywhere in the run.
- `--no-call-graph` skips the picture. Calls are still extracted and linked.
- While the call graph is enabled, `callgraph` is a reserved output key. `collision_error(inputs, reserved: dict[str, str])` takes reserved keys mapped to the message tail the caller supplies, so `inputs.py` knows nothing about call graphs. The CLI passes `{"callgraph": "it is reserved for the call graph; rename the file, chart its parent directory instead, or pass --no-call-graph"}`, and an input whose key is exactly `callgraph` (an explicit `callgraph.py`, or one at the top of a walk) is reported before anything is written: `error: output name collision: PATH maps to 'callgraph'; it is reserved for the call graph; rename the file, chart its parent directory instead, or pass --no-call-graph`. A different `--output` does not help, so it is not suggested.
- `output.Writer` gets `write_callgraph(documents: list[Document]) -> None`, using the same Graphviz-missing handling (report once, skip images, exit 2) and write-failure reporting as other outputs.

## Errors and exit codes

No new warnings and no new exit codes beyond the collision row. Unresolved calls are normal. A skipped function or file has no chart, so calls to it stay unresolved; a file that fails to read has no document and is not indexed.

| Situation | Behaviour | Exit |
|---|---|---|
| A file's output key is `callgraph` while the call graph is enabled | collision error before anything is written | 1 |

## Code structure

- `frontends/python/calls.py` (new): scope and import tables per file, and `candidates(call_node, …) -> tuple[CallRef, ...]`. `statements.py` asks it for the call sites of each statement it converts, so `statements.py` grows by only a few lines.
- `calls.py` (new): the linker.
- `backends/callgraph.py` (new): the picture.
- `cli.py`, `inputs.py` (`reserved`), `output.py` (`write_callgraph`), `serialize.py`, `ir.py`, `cfg/model.py`, `cfg/builder.py`, `cfg/finally_.py` (handler calls), the frontend protocol change, and `statements.py`, whose `decorated_definition` case must keep the wrapper's decorators for the `def`/`class` node.

## Testing

Test-first; chart shapes with `flow(chart)`.

- **cfg:** a `Step` with call sites gives `Call`s on its node; a statement in a `finally` body records its calls on every copy; `Branch`, `Loop`, `Handler` and `Terminal` nodes carry their calls.
- **Call ownership (Python):** each row of the ownership table, including `@deco(f())` and bare `@deco` on a decorated `def` and `class`, defaults and annotations on the enclosing `def` node, a whole `class` subtree (bases, body, method signatures) on the `class` node while method bodies stay in their charts, top-level `def`/`class` calls only with a module chart, a nested function's body calls in its own chart, lambdas and comprehensions on the enclosing node; pre-order for `a().b()`; calls unchanged by `--no-returns`/`--no-parameters`; a hidden `x[g()] = 1` records no call, and does with `--variables`; `text` values.
- **Resolution (Python):** innermost scope first, with definitions and imports per scope (a local import shadows a module-level `def`; a local import beats a module-level import); the owning node decides the chain (`def inner(x=helper())` resolves in `outer`); the owning chart's own scope is first; class scopes not visible; skipped functions still give their candidate, not an outer fallback; a class call gives `__init__`; `from m import n [as a]`; `self.m` / `cls.m` with a nested class's full qualname, and `self.x.m()` giving nothing; `C.m` for local, enclosing-function and imported classes; `import x.y` binding `x` (`x.f()` → `(x, f)`); `import x.y as z` not binding `x`; longest module prefix; the two candidates for `from p import x as a; a.f()` using `x`; relative imports, from `__init__`, and above the top (nothing, and no link to an empty module name); `__future__` and star imports ignored; a function-local import scoped to that function; both `try`/`except` bindings, deduplicated; builtins and dynamic calls give `[]`.
- **Module name and package:** `pkg/io/load` → `pkg.io.load`, package `("pkg", "io")`; `pkg/__init__` → `pkg`, package `("pkg",)`; an explicit stem → package `()`; a bare `__init__` → `""`; the default key when `parse` gets none.
- **Linker:** first existing candidate wins; a missing one gives `None`; cross-document links; module chart calls are linked too; independent of document order; module charts are never targets; empty and duplicated module names are not indexed.
- **IR/JSON:** version 3 round trip; versions 1 and 2 still load with `calls = []` and `module_name = ""`; determinism.
- **Backend:** clusters per document, named by index; no cluster for a document without charts; node IDs `{i}#{qualname}`, unique for duplicated module names, no `:` even for a source path with `:`; edges deduplicated; recursion self-loop; only resolved calls with a drawn target; `<module>` label escaped in DOT and Mermaid; a module named `end` in Mermaid; deterministic DOT and Mermaid; SVG when Graphviz is installed.
- **CLI:** a directory run writes `OUTDIR/callgraph.<ext>` with a cross-file edge; JSON-only writes no picture; `--no-call-graph`; `--function` limits the picture while JSON targets still reach unselected charts; the reserved-key collision, and none with `--no-call-graph`; missing Graphviz still writes the DOT/Mermaid call graph and exits 2.
- **Smoke:** `uv run pyflowcharts src -o /tmp/pyflowcharts-self -f json dot` gives a `callgraph.dot`, and `pyflowcharts/cli.json` has a call in `main` whose `target` is `pyflowcharts.inputs` / `expand`.

Existing tests that change:

- `build_chart` returns three values: `tests/test_builder.py` and `tests/test_python_statements.py` (their `chart` helpers).
- `schema_version` 2 → 3: `tests/test_serialize.py`, `tests/test_frontend.py`, `tests/test_python_frontend.py`.
- `test_json_shape` in `tests/test_serialize.py`: the document keys gain `module_name`, and the chart keys gain `calls`.
- Default-on call graph output adds `callgraph.dot` (and `.mmd`) to multi-format CLI runs: `test_directory_input_mirrors_tree`, `test_text_formats` and any other exact output-set assertions in `tests/test_cli.py` and `tests/test_output.py`.
- `parse` and `Chart`/`Document` constructors need no changes thanks to the defaults above.

## Documentation

- The main spec: scope (call graphs in scope), IR v3, the frontend protocol argument, a summary of call ownership and resolution, the output layout with `callgraph.<ext>`, the CLI synopsis with `--no-call-graph`, the error table.
- `AGENTS.md`: architecture (`calls.py`, `backends/callgraph.py`, `frontends/python/calls.py`), the frontend protocol signature, known simplifications: remove "call graphs are out of scope" and add the resolution limits.
- `README.md`: call graphs in the intro, `--no-call-graph`, `callgraph.svg` in the output layout, schema version 3, the resolution limits, and walking the import root (`src/`) so absolute imports resolve.

## Out of scope

Inheritance-aware method resolution, type inference, star imports, resolving into modules outside the run (the candidates are kept for a later GUI), per-file call-graph pictures.
