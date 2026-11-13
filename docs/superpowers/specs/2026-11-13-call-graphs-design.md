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
    candidates: list[CallRef]    # where it may go, most likely first; [] if unknown
    target: CallRef | None       # the first candidate charted in this run, set by the linker

@dataclass
class Chart:
    qualname: str
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]
    calls: list[Call]            # in node order, then source order within a node

@dataclass
class Document:
    source: str
    language: str
    module_name: str             # e.g. "pkg.io.load"
    functions: list[FunctionChart]
    module: Chart | None = None
    schema_version: int = SCHEMA_VERSION  # 3
```

- `Call` is frozen but holds a list, so it is not hashable; nothing needs to hash it.
- `Document.module_name` is a required field placed before `functions`; existing keyword-argument constructors add it.
- JSON keys follow dataclass order (`dataclasses.asdict`). A chart's keys become `qualname`, `location`, `nodes`, `edges`, `calls`, then a function chart's signature fields.
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
| decorators, parameter defaults and annotations, return annotation of a nested `def` | the parent's `def` process node (they run when the parent reaches the `def`) |
| a nested `class` body outside its methods | the parent's `class` process node |
| lambdas, comprehensions, generator expressions | the enclosing statement's node |

- Calls inside a nested function's body belong to that function's chart, not to the parent.
- A statement that gets no node records no calls. Only hidden steps (plain assignments without a call) get no node, so in practice no call is lost; an assignment containing a call is always shown.
- A statement inside a `finally` body that is drawn several times records its calls on every copy node, each `Call` naming its copy's node id.
- The `try` node itself, `else`/`finally` markers, `start` and `end` own no calls. The `start` node's signature (defaults, annotations) belongs to the parent, as above.
- `text` is the callee expression's source text (the `function` field of the tree-sitter `call` node), produced with `Source.source_text`, never truncated.

## Model and builder (`cfg/`)

- `cfg/model.py` gets `@dataclass(frozen=True) class CallSite(text: str, candidates: tuple[CallRef, ...])`. It imports `CallRef` from `ir.py`.
- `Step`, `Branch`, `Loop`, `Handler` and `Terminal` get `calls: tuple[CallSite, ...] = ()` as their last field.
- `ChartBuilder.add_node` takes the statement's call sites and records one `Call(node_id, text, list(candidates), None)` per site for every node it creates, including finally copies.
- `build_chart` returns `(nodes, edges, calls)`.
- `cfg/` stays language-neutral: it imports nothing from tree-sitter or `frontends/`.

## Frontend protocol and module names

- `Frontend.parse(source: bytes, path: str, options: ChartOptions, key: PurePosixPath) -> ParseResult`. The key is the output key from `inputs.py`.
- The Python frontend derives `module_name` from the key: its parts joined with `.`, with a final `__init__` dropped (`pkg/io/load` → `pkg.io.load`, `pkg/__init__` → `pkg`). A file named explicitly has its stem as key, so its module name is the stem.
- A key `__init__` on its own (an explicitly named `__init__.py`) gives `module_name = ""`; relative imports from it resolve to nothing.

## Resolution rules (Python frontend)

The resolver lives in `frontends/python/calls.py`. It is static and best-effort and never raises: anything not covered gives `candidates = []`. "Own" means the file's `module_name`.

### Bare name `n(…)` called in chart `Q`

1. **Enclosing functions**, innermost first. For each function ancestor `F` of the call (classes are skipped, as in Python's scoping), if `F.n` is a charted qualname in this file, the candidate is `(own, F.n)`. A nested `def` is visible to its siblings and their descendants.
2. **Module level.** A module-level `def n` gives `(own, n)`. A module-level `class n` gives `(own, n.__init__)`.
3. **Import binding of `n`.** `from m import n [as alias]` (binding `alias` or `n`) gives `(m, n)` and then `(m, n.__init__)`. `import m as n` binds a module, which is never called, so it gives nothing.
4. Otherwise (builtins, names assigned at runtime) nothing.

The first rule that applies decides; later rules are not consulted, because Python name lookup stops at the first scope that defines the name. Within rule 3, several bindings of `n` (see "Where imports count") each contribute their candidates, in source order.

### Attribute calls `a.b.c(…)`

- **`self.m(…)` / `cls.m(…)`** in a function defined directly in class `C`'s body give `(own, C.m)`. Base classes are not followed.
- **`C.m(…)`** where `C` is a class defined in this file give `(own, C.m)`. Through `from m import C`, they give `(m, C.m)`.
- **`import x.y [as z]`.** The longest prefix of the call chain that names an imported module (`x.y`, or the alias `z`) wins, and the rest is the qualname: `x.y.f()` gives `(x.y, f)`, `z.f()` gives `(x.y, f)`, `x.y.C.m()` gives `(x.y, C.m)`. A plain `import x` makes `x` a module prefix.
- **`from p import x`, then `x.f(…)`.** `x` may be a submodule or a name in `p`, so this gives `(p.x, f)` and then `(p, x.f)`.
- Anything else (calls on call results, subscripts, unknown objects) gives nothing.

### Relative imports

`from . import x` and `from ..a import b` resolve against the file's package: the module name without its last part (`pkg.io.load` → `pkg.io`), or the module name itself for an `__init__` file (`pkg/io/__init__` → `pkg.io`). Each extra leading dot drops one more part. Going above the top (more dots than parts) resolves to nothing.

### Where imports count

- Imports anywhere at module level, or in an enclosing function, count, regardless of statement order.
- An import inside a function applies only to calls in that function and its nested functions.
- `try: import a` / `except ImportError: import b as a` records both bindings; calls get candidates from both, in source order.

### Not handled (documented limits)

Shadowing by local assignment (`f = other; f()` still resolves to `def f`), inheritance, decorators that replace a function, `getattr` and other dynamic calls, star imports (`from m import *`), and calls through instance attributes other than `self`/`cls`. Duplicate qualnames (`A.x@L9`) resolve to the first definition (`A.x`).

## Linker (`calls.py`)

- New language-neutral module `src/pyflowcharts/calls.py`: `link(documents: list[Document]) -> list[Document]`.
- It indexes every function chart as `(document.module_name, chart.qualname)`. Module charts are not indexed, so they are never targets.
- It returns new documents (`dataclasses.replace`) in which each call's `target` is its first candidate found in the index, or `None`.
- The result does not depend on document order.
- The CLI calls it after parsing every file and before `--function` selection, so targets cover the whole run even when only some charts are written.

## Picture (`backends/callgraph.py`)

- `to_callgraph_digraph(documents: list[Document]) -> graphviz.Digraph`, `to_callgraph_dot(documents) -> str`, `render_callgraph(documents, fmt: Literal["svg", "png"]) -> bytes`, `to_callgraph_mermaid(documents) -> str`.
- **Nodes:** one per chart (function charts, then the module chart if any), grouped into one cluster per document, labelled with the document's `module_name` (or its `source` when the module name is empty). A node is labelled with its qualname; the module chart shows as `<module>`.
- **Node IDs:** `{module_name}#{qualname}`, falling back to `{source}#{qualname}` when the module name is empty, so they never contain `:` unless the source path does. DOT IDs are quoted, and the graph name is passed through `graphviz.nohtml`. Mermaid uses generated ids (`n0`, `n1`, …) as the flowchart backend does.
- **Edges:** one per (caller chart, target) pair with at least one resolved call, without labels. A recursive call draws a self-loop. Unresolved calls are not drawn.
- `rankdir=LR`. Order is deterministic: documents in input order, charts in document order, edges sorted by (caller id, target id).

## CLI and output

- After parsing, `cli.py` calls `link`, then selects (`--function`), then writes.
- `OUTDIR/callgraph.<ext>` is written once per run for each selected format among `dot`, `svg`, `png` and `mermaid`. With only `json` selected no picture is written; the call data is still in each file's JSON.
- It is written for a single-file run too. It is not written when no document has a chart left after selection.
- With `--function`, the picture shows only the selected charts and the edges between them. The JSON keeps each selected chart's full `calls`, with targets anywhere in the run.
- `--no-call-graph` skips the picture. Calls are still extracted and linked.
- While the call graph is enabled, `callgraph` is a reserved output key: `collision_error(inputs, reserved=("callgraph",))` reports an input whose key is exactly `callgraph` (an explicit `callgraph.py`, or one at the top of a walk) before anything is written: `error: output name collision: PATH maps to 'callgraph', which is reserved for the call graph; rename it, use a different --output, or pass --no-call-graph`.
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
- `cli.py`, `inputs.py` (`reserved`), `output.py` (`write_callgraph`), `serialize.py`, `ir.py`, `cfg/model.py`, `cfg/builder.py`, `cfg/finally_.py` (passing calls through copies) and the frontend protocol change.

## Testing

Test-first; chart shapes with `flow(chart)`.

- **cfg:** a `Step` with call sites gives `Call`s on its node; a statement in a `finally` body records its calls on every copy; `Branch`, `Loop`, `Handler` and `Terminal` nodes carry their calls.
- **Call ownership (Python):** each row of the ownership table, including decorator, default and annotation calls on the parent's `def` node, a nested function's body calls in its own chart, class-body calls on the `class` node, lambdas and comprehensions on the enclosing node; `text` values.
- **Resolution (Python):** each rule: enclosing functions before module level; class scopes not visible; a class call gives `__init__`; `from m import n [as a]`; `self.m` / `cls.m`; `C.m` (local and imported); `import x.y as z`; longest module prefix; the two candidates for `from p import x; x.f()`; relative imports, from `__init__`, and above the top (nothing); a function-local import scoped to that function; both `try`/`except` bindings; builtins and dynamic calls give `[]`.
- **Module name:** `pkg/io/load` → `pkg.io.load`; `pkg/__init__` → `pkg`; an explicit stem; a bare `__init__` → `""`.
- **Linker:** first existing candidate wins; a missing one gives `None`; cross-document links; independent of document order; module charts are never targets.
- **IR/JSON:** version 3 round trip; versions 1 and 2 still load with `calls = []` and `module_name = ""`; determinism.
- **Backend:** clusters per document; node IDs without `:`; edges deduplicated; recursion self-loop; only resolved calls drawn; `<module>` label; deterministic DOT and Mermaid; SVG when Graphviz is installed.
- **CLI:** a directory run writes `OUTDIR/callgraph.<ext>` with a cross-file edge; JSON-only writes no picture; `--no-call-graph`; `--function` limits the picture while JSON targets still reach unselected charts; the reserved-key collision, and none with `--no-call-graph`; missing Graphviz still writes the DOT/Mermaid call graph and exits 2.
- **Smoke:** `uv run pyflowcharts src -o /tmp/pyflowcharts-self -f dot` gives a `callgraph.dot` with an edge `pyflowcharts.cli#main` → `pyflowcharts.inputs#expand`.

## Documentation

- The main spec: scope (call graphs in scope), IR v3, the frontend protocol argument, a summary of call ownership and resolution, the output layout with `callgraph.<ext>`, the CLI synopsis with `--no-call-graph`, the error table.
- `AGENTS.md`: architecture (`calls.py`, `backends/callgraph.py`, `frontends/python/calls.py`), the frontend protocol signature, known simplifications: remove "call graphs are out of scope" and add the resolution limits.
- `README.md`: call graphs in the intro, `--no-call-graph`, `callgraph.svg` in the output layout, schema version 3, the resolution limits.

## Out of scope

Inheritance-aware method resolution, type inference, star imports, resolving into modules outside the run (the candidates are kept for a later GUI), per-file call-graph pictures.
