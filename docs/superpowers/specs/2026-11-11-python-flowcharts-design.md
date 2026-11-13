# flowcharts — Design

**Date:** 2026-11-11
**Status:** Implemented. Amended on 2026-11-12 by `2026-11-12-tree-sitter-frontend-design.md` (tree-sitter frontend, shared CFG engine, per-function syntax errors), which wins where the two disagree. Amended on 2026-11-13 by `2026-11-13-exception-edges-design.md` (per-statement exception edges, `return`/`raise` through `finally`) and `2026-11-13-directories-and-module-code-design.md` (directory inputs, module-level charts, schema version 2), and by `2026-11-13-call-graphs-design.md` (call data in the IR, one call graph per run, schema version 3), all folded in below.

## Purpose

A Python CLI tool that reads Python source files and produces a **control-flow flowchart for each function**. The start node shows the parameters and return nodes show the returned value. Variable assignments can optionally be shown too. Output is static images (SVG/PNG) for people and JSON for machines. A future GUI explorer will read the JSON.

## Scope

**In scope (MVP)**
- Python source files (`.py`) parsed with tree-sitter (`tree-sitter-python`), validated with the standard-library `ast` module.
- Files and directories as inputs. A directory is walked recursively and its output mirrors the source tree.
- One flowchart per function: module-level functions, methods (`Class.method`), nested functions (`outer.inner`), and `async def`.
- One module-level chart per file whose top level does work (see "Module-level charts").
- Output formats: `json`, `dot`, `svg`, `png`, `mermaid`.
- Detail options: show/hide parameters, return values and variable assignments.
- Calls: every chart records its calls with candidate targets, resolved within the run, and each run draws one call graph (see "Call graphs").

**Out of scope (for now)**
- Other languages. The architecture allows them (see "Frontends"), but none are built.
- The GUI explorer. Only its input format (JSON) is built now.
- Class bodies beyond their methods, `.gitignore` support.
- Inheritance-aware method resolution, type inference, resolving calls into modules outside the run, per-file call-graph pictures.

## Architecture

```
source file ──► Frontend (per language) ──► cfg (shared engine) ──► IR (Document) ──► Backends (shared)
                 PythonFrontend (tree-sitter)  model + builder                          json | dot → svg/png | mermaid
```

- **Frontend**: turns one source file into a `ParseResult` (a `Document` plus warnings). It's selected by file extension through a small registry, so a new language means adding a module, not a new project. Its signature is `parse(source: bytes, path: str, options: ChartOptions, key: PurePosixPath | None = None) -> ParseResult`; `key` is the file's output key, from which the module name is derived (the file's stem when omitted). Frontends produce language-neutral `cfg.model` statements; the shared `cfg.builder` turns them into nodes and edges.
- **IR**: plain dataclasses, language-neutral. This is the contract between frontends and backends, and it's what the JSON file contains.
- **Linker** (`calls.py`): language-neutral; sets each call's target against all documents of the run.
- **Backends**: depend only on the IR.

## IR

- `Document`: `source` (path as given or as reached by a directory walk), `language` (`"python"`), `functions: list[FunctionChart]`, `module_name` (dotted, e.g. `pkg.io.load`; `""` when the file has none), `module: Chart | null`, `schema_version` (= 3).
- `Chart`: `qualname`, `location`, `nodes`, `edges`, `calls: list[Call]`. The module chart is a `Chart` with qualname `<module>`.
- `FunctionChart(Chart)`: adds `name`, `is_async`, `parameters: list[Parameter]`, `returns` (annotation text or null). `qualname` is unique within the document. In JSON its keys come in the order `qualname`, `location`, `nodes`, `edges`, `calls`, `name`, `is_async`, `parameters`, `returns`.
- `Parameter`: `name`, `annotation`, `default` (source text or null), `kind` (`positional_only | positional_or_keyword | var_positional | keyword_only | var_keyword`).
- `Node`: `id`, `kind`, `label`, `location` (`line`, `column`, `end_line`, `end_column`, or null for synthetic nodes).
- `Edge`: `source`, `target`, `label` (null or e.g. `"True"`, `"False"`, `"next"`, `"done"`, `"exception"`, `"case …"`).
- `Call`: `node` (id of the node the call is written in), `text` (the callee's source text, never truncated), `candidates: list[CallRef]` (most likely first, no duplicates), `target: CallRef | null` (the first candidate charted in the run). Calls are ordered by node, then pre-order within a node.
- `CallRef`: `module` (dotted module name), `qualname`.

Rules:
- Schema version 2 added `Chart`, `Document.module` and the key order above. `from_json` still reads version 1 documents (as `module = null`) and keeps the version it read.
- Schema version 3 added `Call`, `CallRef`, `Chart.calls` and `Document.module_name`. Versions 1 and 2 are read with `calls = []` and `module_name = ""`.
- The IR always holds the full signature data. Display options only change node labels, plus which assignment nodes exist.
- **No layout in the IR** (no x/y). Layout belongs to Graphviz or the GUI.
- **Stable node IDs**: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}` for statements, with the suffix `~finally` for synthetic nodes and `~break@L{line}C{col}`, `~continue@…`, `~return@…` or `~exception@…` (naming the owning `try`) for nodes in duplicated finally bodies, so nested copies stay unique. IDs never contain `:`, because DOT reads it as port syntax. The module chart's IDs use the qualname `<module>` (`<module>#start`, `<module>#L3C0`), which no function qualname can equal; the DOT backend quotes the graph name with `graphviz.nohtml` so the brackets survive.
- Output is deterministic: the same input gives byte-identical JSON, DOT and Mermaid.

## Node kinds and shapes

| Kind | Used for | DOT shape | Mermaid |
|---|---|---|---|
| `start` | `def f(a, b=1) -> int` | oval | `(["…"])` |
| `end` | implicit end of function | oval | `(["…"])` |
| `process` | simple statements, `try`, `with`, `except …`, `finally`, nested `def`/`class` | box | `["…"]` |
| `decision` | `if`, `match` | diamond | `{"…"}` |
| `loop` | `for`, `while` (async too) | hexagon | `{{"…"}}` |
| `return` | `return …` | parallelogram | `[/"…"/]` |
| `raise` | `raise …` | octagon | `>"…"]` |

## Python control-flow mapping

- Sequential statements are chained. A function body's last statements flow to `end`.
- `if` is a decision with `True`/`False` edges. `elif` is a nested decision. Without `else`, the `False` edge goes to the next statement.
- `match` is a decision with one `case <pattern>[ if <guard>]` edge per case. A `no match` edge is added unless the last case is irrefutable (`_` or a bare capture without a guard).
- `for`/`while`: a loop node. The body is entered via `next` (for) or `True` (while), and the body's end flows back to the loop node. The exit is `done` (for) or `False` (while). A `while` with a constant-true test has no exit edge except `break`s. Loop `else` runs from the exit edge, and `break` skips it. `break` and `continue` get no nodes. They redirect the incoming edge to the loop exit or the loop node.
- `try`: a `try` node, then the body. Every node in the body has an `exception` edge to each `except` handler node (the `try` node itself has none). `else` follows the body. Handler and `else` nodes point at the `finally (exception)` copy if there is a `finally`, else at the enclosing `try`'s handlers. A `raise` inside a `try` is drawn only through those exception edges. With a `finally`, the finally body is drawn once per path that reaches it (`finally`, `finally (break)`, `finally (continue)`, `finally (return)`, `finally (exception)`), and each copy continues to its own target: the next statement, the loop exit, the loop head, `end`, or the enclosing handlers. Copies nobody reaches are not drawn. If the finally body ends the path itself (e.g. with its own `continue`), that overrides the pending transfer. `except*` works the same way.
- `with`: a node labelled `with <items>`, then the body.
- `return` and `raise` end the current path. Outside any `try` they go to `end`; inside one, `return` runs the enclosing finally bodies first and `raise` leaves only through its exception edges (see `try`).
- A nested `def`/`class` becomes a process node in its parent, and nested functions also get their own chart.
- Skipped statements (no node): a docstring as the first statement, `pass`, `...`, `global`, `nonlocal`. Paths flow through them.
- Variable assignments (`=`, `+=`, annotated) get nodes only with `--variables`, **unless** the assigned value contains a call (then they're always shown). They're also shown when every statement in a block (a function body, branch, case, loop body, `with`/`try` body, handler or `finally`) would otherwise get no node, so a branch never looks empty just because its assignments are hidden. This is decided per block.
- Code after `return`/`raise`/`break`/`continue` (unreachable) is still emitted as nodes with no incoming edges.
- Any statement type without its own rule becomes a process node labelled with its source text.

## Module-level charts

- A file gets a module chart when its top level (not class or function bodies) has a statement other than a docstring, `import`/`from … import`, `def`/`class` (decorated or not), an assignment (`=`, augmented, annotated, even with a call in the value), a `type` alias, `pass`, `...` or `global`. Library modules that only import and define things get none. `--no-module` turns module charts off.
- The chart holds all top-level statements (a leading docstring dropped) with the same rules as a function body: imports and definitions become process nodes, plain assignments are hidden unless `--variables`, and so on. Its start node is `module <stem>`. Its location runs from the first statement (leading comments such as a shebang excluded) to the last token.
- No module chart is built when there is a syntax error outside every function. When the top level does work, a tree-sitter error outside every function that `ast` accepts (newer syntax) skips it with `unsupported syntax in module code; module chart skipped`, and a top-level `break`/`continue` with `syntax error in module code; module chart skipped`. Those two warnings carry the qualname `<module>`, so `--function` treats them like a skipped function. A file without top-level work gets no warning for such an error, since no module chart would be drawn (a top-level `ERROR` node counts as work).

**Known simplifications** (documented, not bugs): handlers are assumed to catch whatever reaches them, so the uncaught path out of a `try` that has handlers is not drawn. The `try` node itself has no exception edges, so a `try` whose body has no nodes leaves its handlers unreachable. Class bodies are charted only through their methods.

## Call graphs

- **Ownership:** a call belongs to the node of the statement it is written in: conditions, loop headers, `with` items, `except` expressions, `match` subjects and guards, `return`/`raise`. Calls in a `def`'s decorators, defaults and annotations belong to the enclosing chart's `def` node; a `class` node owns its whole subtree (decorators, bases, body, method signatures) except method bodies. Lambdas and comprehensions belong to the enclosing statement. Top-level `def`/`class` statements own calls only when there is a module chart. Hidden steps (plain assignments) record no calls; a statement in a duplicated `finally` body records them on every copy.
- **Resolution (Python, static, best-effort):** bare names walk the scopes of the owning node (innermost function first, then the module; class bodies are not scopes), where the first scope that binds the name by a `def`, `class`, import or parameter wins (a parameter resolves to nothing). A class call gives `C.__init__`. `self.m()`/`cls.m()` in a method gives `C.m`. `C.m()` follows a class binding. `import x.y` binds `x` and makes `x.y` reachable; `import x.y as z` binds `z` only; `from m import x` gives `(m, x)` or, for `x.f()`, `(m.x, f)` then `(m, x.f)`. Relative imports resolve against the file's package; `__future__` and star imports bind nothing.
- **Module names** come from the output key (`pkg/io/load` → `pkg.io.load`, `pkg/__init__` → `pkg`), so absolute imports resolve when the import root is walked (`pyflowcharts src/`).
- **Linker:** each call's target is its first candidate that names a function chart in the run. Module charts are never targets; documents with an empty or shared module name are not indexed.
- **Picture:** `OUTDIR/callgraph.<ext>` for each selected picture format: one cluster per file with charts, one node per chart, one edge per caller/callee pair with a resolved call between drawn charts, `rankdir=LR`.
- **Limits:** shadowing by local assignment or `for`/`with`/`except` targets, inheritance, decorators that replace functions, `getattr` and other dynamic calls, star imports, `global`/`nonlocal` rebinding, and calls through instance attributes other than `self.m`/`cls.m` are not handled. Duplicate qualnames resolve to the first definition.

## Labels

- Source text is the original source of the statement or expression, so literals keep their written form (`0xD800`, quote style, `1_000`). Comments and `\` continuations are removed and multi-line code is joined (see the tree-sitter spec's Labels section for the whitespace rule). Whitespace runs collapse to one space, and text is truncated to `max_label_length` (default 60) with `…`.
- Start: `def name(<params>) -> <ret>` (prefixed `async ` when async). With parameters hidden: `def name(...)`.
- Return: `return <expr>`, or just `return` with returns hidden.
- Duplicate qualnames (property setters, redefinitions) get a suffix on the later definitions: `A.x@L9`.

## Output layout & CLI

```
pyflowcharts PATH [PATH ...] [-o OUTDIR] [-f FORMAT ...] [--variables]
             [--no-parameters] [--no-returns] [--no-module] [--no-call-graph]
             [--function QUALNAME ...] [--exclude GLOB ...] [--max-label N]
```

- Defaults: `-o flowcharts`, `-f svg json`.
- Only the selected formats are written (e.g. `-f mermaid` writes no JSON).
- Each `PATH` is a file or a directory. A directory is walked recursively: only files with a supported extension, no hidden files or directories (below the argument), no `__pycache__`, directory symlinks not followed, only regular files, sorted by relative path. A file reached twice is charted once, and counts as named explicitly if any mention was explicit.
- `--exclude GLOB` (several values, repeatable) applies only to walked files: a pattern without `/` matches any file or directory name, one with `/` the POSIX path relative to the directory argument, and a trailing `/` restricts it to directories. Matching is `fnmatchcase`; a matched directory is not walked.
- Each file has an output key `K`: its stem when named explicitly, or its path relative to the directory argument without extension when walked.
- `OUTDIR/K.json`: one JSON document per source file (when `json` is selected).
- `OUTDIR/K.<ext>`: the module chart for `dot`, `svg`, `png`, `mermaid` (`.mmd`).
- `OUTDIR/K/<qualname>.<ext>`: one file per function. Directories are created only for files that are written.
- `OUTDIR/callgraph.<ext>`: the run's call graph for `dot`, `svg`, `png`, `mermaid`, unless `--no-call-graph` is given or no document has a chart. With `--function` it shows only the selected charts, while the JSON keeps each chart's full calls. The output key `callgraph` is reserved while the call graph will be written.
- `--function` restricts all outputs to the given qualnames; `<module>` selects module charts. It accepts several names (`--function a b`) and can be repeated (`--function a --function b`). The list of available names is deduplicated across files. Put the input paths before options that take several values.

## Errors and exit codes

| Situation | Behaviour | Exit |
|---|---|---|
| Syntax error in a function (including `break`/`continue` outside a loop) | `path:line: warning: syntax error in 'qualname'; function skipped`; the other functions are still written | 1 |
| Syntax error outside every function | `path:line: warning: syntax error outside functions; nearby code may be missing`; functions still written, no module chart | 1 |
| Undecodable source, null bytes, missing file, unsupported extension | `path[:line]: error: message` on stderr; other files still processed | 1 |
| Unknown `--function` name | error listing the available qualnames | 1 |
| Two inputs with the same output key, or one key a directory prefix of another (`pkg/mod.py` beside `pkg/mod/`) | `error: output name collision: …` before anything is written | 1 |
| A file's output key is `callgraph` while the call graph will be written | `error: output name collision: PATH maps to 'callgraph'; it is reserved for the call graph; …` before anything is written | 1 |
| Top-level `break`/`continue` outside a loop | `path:line: warning: syntax error in module code; module chart skipped`; other charts still written | 1 |
| Tree-sitter misreads top-level syntax that `ast` accepts | `path:line: warning: unsupported syntax in module code; module chart skipped`; other charts still written | 1 |
| Directory that cannot be read | `DIR: error: cannot read directory: reason`; the rest of the walk continues | 1 |
| Directory with no source files | `warning: DIR: no source files found` | 0 |
| Code too deeply nested to parse or chart | `path: error: code is too deeply nested …`; other files still processed | 1 |
| An output file or directory cannot be written | `error: cannot write PATH: reason`; other outputs still written | 1 |
| `dot` binary missing while `svg`/`png` requested | error explaining how to install Graphviz; non-image outputs still written | 2 |
| File named on the command line with nothing to chart (no function charts, no module chart, no warnings) | `warning: PATH: nothing to chart`; JSON written if `json` is selected. Not printed for walked files, nor because of `--function` filtering | 0 |

Source files are read as bytes so that PEP 263 coding cookies and BOMs are honoured. Validity is decided per function by `ast.parse` as described in the tree-sitter spec; compiler-only errors other than `break`/`continue` outside a loop are not checked.

Mermaid labels escape `#` as `#35;` before any other entity substitution, so literal text like `#34;` in source code isn't turned into a quotation mark.

## Future work this design prepares for

- **GUI explorer** reading the JSON: source locations enable click-to-source, stable IDs enable linking and diffing, and `schema_version` enables format evolution.
- **More languages**: implement the `Frontend` protocol with a tree-sitter grammar, produce `cfg.model` statements, and register the file extensions.
