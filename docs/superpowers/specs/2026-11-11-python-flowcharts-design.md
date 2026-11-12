# flowcharts — Design

**Date:** 2026-11-11
**Status:** Implemented. Amended on 2026-11-12 by `2026-11-12-tree-sitter-frontend-design.md` (tree-sitter frontend, shared CFG engine, per-function syntax errors), which wins where the two disagree.

## Purpose

A Python CLI tool that reads Python source files and produces a **control-flow flowchart for each function**. The start node shows the parameters and return nodes show the returned value. Variable assignments can optionally be shown too. Output is static images (SVG/PNG) for people and JSON for machines. A future GUI explorer will read the JSON.

## Scope

**In scope (MVP)**
- Python source files (`.py`) parsed with tree-sitter (`tree-sitter-python`), validated with the standard-library `ast` module.
- One flowchart per function: module-level functions, methods (`Class.method`), nested functions (`outer.inner`), and `async def`.
- Output formats: `json`, `dot`, `svg`, `png`, `mermaid`.
- Detail options: show/hide parameters, return values and variable assignments.

**Out of scope (for now)**
- Other languages. The architecture allows them (see "Frontends"), but none are built.
- The GUI explorer. Only its input format (JSON) is built now.
- Directory recursion, module-level (non-function) code, call graphs between functions.

## Architecture

```
source file ──► Frontend (per language) ──► cfg (shared engine) ──► IR (Document) ──► Backends (shared)
                 PythonFrontend (tree-sitter)  model + builder                          json | dot → svg/png | mermaid
```

- **Frontend**: turns one source file into a `ParseResult` (a `Document` plus warnings). It's selected by file extension through a small registry, so a new language means adding a module, not a new project. Frontends produce language-neutral `cfg.model` statements; the shared `cfg.builder` turns them into nodes and edges.
- **IR**: plain dataclasses, language-neutral. This is the contract between frontends and backends, and it's what the JSON file contains.
- **Backends**: depend only on the IR.

## IR

- `Document`: `schema_version` (= 1), `language` (`"python"`), `source` (path as given), `functions: list[FunctionChart]`.
- `FunctionChart`: `qualname` (unique within the document), `name`, `is_async`, `parameters: list[Parameter]`, `returns` (annotation text or null), `location`, `nodes`, `edges`.
- `Parameter`: `name`, `annotation`, `default` (source text or null), `kind` (`positional_only | positional_or_keyword | var_positional | keyword_only | var_keyword`).
- `Node`: `id`, `kind`, `label`, `location` (`line`, `column`, `end_line`, `end_column`, or null for synthetic nodes).
- `Edge`: `source`, `target`, `label` (null or e.g. `"True"`, `"False"`, `"next"`, `"done"`, `"exception"`, `"case …"`).

Rules:
- The IR always holds the full signature data. Display options only change node labels, plus which assignment nodes exist.
- **No layout in the IR** (no x/y). Layout belongs to Graphviz or the GUI.
- **Stable node IDs**: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}` for statements, with the suffix `~finally` for synthetic nodes and `~break@L{line}C{col}`, `~continue@…`, `~return@…` or `~exception@…` (naming the owning `try`) for nodes in duplicated finally bodies, so nested copies stay unique. IDs never contain `:`, because DOT reads it as port syntax.
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
- `return` and `raise` go to `end` and end the current path.
- A nested `def`/`class` becomes a process node in its parent, and nested functions also get their own chart.
- Skipped statements (no node): a docstring as the first statement, `pass`, `...`, `global`, `nonlocal`. Paths flow through them.
- Variable assignments (`=`, `+=`, annotated) get nodes only with `--variables`, **unless** the assigned value contains a call (then they're always shown). They're also shown when every statement in a block (a function body, branch, case, loop body, `with`/`try` body, handler or `finally`) would otherwise get no node, so a branch never looks empty just because its assignments are hidden. This is decided per block.
- Code after `return`/`raise`/`break`/`continue` (unreachable) is still emitted as nodes with no incoming edges.
- Any statement type without its own rule becomes a process node labelled with its source text.

**Known simplifications** (documented, not bugs): handlers are assumed to catch whatever reaches them, so the uncaught path out of a `try` that has handlers is not drawn. The `try` node itself has no exception edges, so a `try` whose body has no nodes leaves its handlers unreachable.

## Labels

- Source text is the original source of the statement or expression, so literals keep their written form (`0xD800`, quote style, `1_000`). Comments and `\` continuations are removed and multi-line code is joined (see the tree-sitter spec's Labels section for the whitespace rule). Whitespace runs collapse to one space, and text is truncated to `max_label_length` (default 60) with `…`.
- Start: `def name(<params>) -> <ret>` (prefixed `async ` when async). With parameters hidden: `def name(...)`.
- Return: `return <expr>`, or just `return` with returns hidden.
- Duplicate qualnames (property setters, redefinitions) get a suffix on the later definitions: `A.x@L9`.

## Output layout & CLI

```
pyflowcharts FILE [FILE ...] [-o OUTDIR] [-f FORMAT ...] [--variables]
             [--no-parameters] [--no-returns] [--function QUALNAME ...] [--max-label N]
```

- Defaults: `-o flowcharts`, `-f svg json`.
- Only the selected formats are written (e.g. `-f mermaid` writes no JSON).
- `OUTDIR/<stem>.json`: one JSON document per source file (when `json` is selected).
- `OUTDIR/<stem>/<qualname>.<ext>`: one file per function for `dot`, `svg`, `png`, `mermaid` (`.mmd`).
- `--function` restricts all outputs to the given qualnames. It accepts several names (`--function a b`) and can be repeated (`--function a --function b`). Put the input files before options that take several values.

## Errors and exit codes

| Situation | Behaviour | Exit |
|---|---|---|
| Syntax error in a function (including `break`/`continue` outside a loop) | `path:line: warning: syntax error in 'qualname'; function skipped`; the other functions are still written | 1 |
| Syntax error outside every function | `path:line: warning: syntax error outside functions; nearby code may be missing`; functions still written | 1 |
| Undecodable source, null bytes, missing file, unsupported extension | `path[:line]: error: message` on stderr; other files still processed | 1 |
| Unknown `--function` name | error listing the available qualnames | 1 |
| Two inputs with the same stem | error before anything is written | 1 |
| Code too deeply nested to parse or chart | `path: error: code is too deeply nested …`; other files still processed | 1 |
| An output file or directory cannot be written | `error: cannot write PATH: reason`; other outputs still written | 1 |
| `dot` binary missing while `svg`/`png` requested | error explaining how to install Graphviz; non-image outputs still written | 2 |
| File has no functions | warning on stderr; JSON with empty `functions` written if `json` is selected | 0 |

Source files are read as bytes so that PEP 263 coding cookies and BOMs are honoured. Validity is decided per function by `ast.parse` as described in the tree-sitter spec; compiler-only errors other than `break`/`continue` outside a loop are not checked.

Mermaid labels escape `#` as `#35;` before any other entity substitution, so literal text like `#34;` in source code isn't turned into a quotation mark.

## Future work this design prepares for

- **GUI explorer** reading the JSON: source locations enable click-to-source, stable IDs enable linking and diffing, and `schema_version` enables format evolution.
- **More languages**: implement the `Frontend` protocol with a tree-sitter grammar, produce `cfg.model` statements, and register the file extensions.
