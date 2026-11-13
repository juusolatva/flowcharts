# flowcharts — Design

**Date:** 2026-11-11
**Status:** Implemented. Amended on 2026-11-12 by `2026-11-12-tree-sitter-frontend-design.md` (tree-sitter frontend, shared CFG engine, per-function syntax errors), which wins where the two disagree. Amended on 2026-11-13 by `2026-11-13-exception-edges-design.md` (per-statement exception edges, `return`/`raise` through `finally`) and `2026-11-13-directories-and-module-code-design.md` (directory inputs, module-level charts, schema version 2), both folded in below.

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

**Out of scope (for now)**
- Other languages. The architecture allows them (see "Frontends"), but none are built.
- The GUI explorer. Only its input format (JSON) is built now.
- Class bodies beyond their methods, `.gitignore` support, call graphs between functions.

## Architecture

```
source file ──► Frontend (per language) ──► cfg (shared engine) ──► IR (Document) ──► Backends (shared)
                 PythonFrontend (tree-sitter)  model + builder                          json | dot → svg/png | mermaid
```

- **Frontend**: turns one source file into a `ParseResult` (a `Document` plus warnings). It's selected by file extension through a small registry, so a new language means adding a module, not a new project. Frontends produce language-neutral `cfg.model` statements; the shared `cfg.builder` turns them into nodes and edges.
- **IR**: plain dataclasses, language-neutral. This is the contract between frontends and backends, and it's what the JSON file contains.
- **Backends**: depend only on the IR.

## IR

- `Document`: `source` (path as given or as reached by a directory walk), `language` (`"python"`), `functions: list[FunctionChart]`, `module: Chart | null`, `schema_version` (= 2).
- `Chart`: `qualname`, `location`, `nodes`, `edges`. The module chart is a `Chart` with qualname `<module>`.
- `FunctionChart(Chart)`: adds `name`, `is_async`, `parameters: list[Parameter]`, `returns` (annotation text or null). `qualname` is unique within the document. In JSON its keys come in the order `qualname`, `location`, `nodes`, `edges`, `name`, `is_async`, `parameters`, `returns`.
- `Parameter`: `name`, `annotation`, `default` (source text or null), `kind` (`positional_only | positional_or_keyword | var_positional | keyword_only | var_keyword`).
- `Node`: `id`, `kind`, `label`, `location` (`line`, `column`, `end_line`, `end_column`, or null for synthetic nodes).
- `Edge`: `source`, `target`, `label` (null or e.g. `"True"`, `"False"`, `"next"`, `"done"`, `"exception"`, `"case …"`).

Rules:
- Schema version 2 added `Chart`, `Document.module` and the key order above. `from_json` still reads version 1 documents (as `module = null`) and keeps the version it read.
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
- No module chart is built when there is a syntax error outside every function. A tree-sitter error outside every function that `ast` accepts (newer syntax) skips it with `unsupported syntax in module code; module chart skipped`, and a top-level `break`/`continue` with `syntax error in module code; module chart skipped`. Those two warnings carry the qualname `<module>`, so `--function` treats them like a skipped function.

**Known simplifications** (documented, not bugs): handlers are assumed to catch whatever reaches them, so the uncaught path out of a `try` that has handlers is not drawn. The `try` node itself has no exception edges, so a `try` whose body has no nodes leaves its handlers unreachable. Class bodies are charted only through their methods.

## Labels

- Source text is the original source of the statement or expression, so literals keep their written form (`0xD800`, quote style, `1_000`). Comments and `\` continuations are removed and multi-line code is joined (see the tree-sitter spec's Labels section for the whitespace rule). Whitespace runs collapse to one space, and text is truncated to `max_label_length` (default 60) with `…`.
- Start: `def name(<params>) -> <ret>` (prefixed `async ` when async). With parameters hidden: `def name(...)`.
- Return: `return <expr>`, or just `return` with returns hidden.
- Duplicate qualnames (property setters, redefinitions) get a suffix on the later definitions: `A.x@L9`.

## Output layout & CLI

```
pyflowcharts PATH [PATH ...] [-o OUTDIR] [-f FORMAT ...] [--variables]
             [--no-parameters] [--no-returns] [--no-module]
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
- `--function` restricts all outputs to the given qualnames; `<module>` selects module charts. It accepts several names (`--function a b`) and can be repeated (`--function a --function b`). The list of available names is deduplicated across files. Put the input paths before options that take several values.

## Errors and exit codes

| Situation | Behaviour | Exit |
|---|---|---|
| Syntax error in a function (including `break`/`continue` outside a loop) | `path:line: warning: syntax error in 'qualname'; function skipped`; the other functions are still written | 1 |
| Syntax error outside every function | `path:line: warning: syntax error outside functions; nearby code may be missing`; functions still written, no module chart | 1 |
| Undecodable source, null bytes, missing file, unsupported extension | `path[:line]: error: message` on stderr; other files still processed | 1 |
| Unknown `--function` name | error listing the available qualnames | 1 |
| Two inputs with the same output key, or one key a directory prefix of another (`pkg/mod.py` beside `pkg/mod/`) | `error: output name collision: …` before anything is written | 1 |
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
