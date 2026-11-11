# flowcharts — Design

**Date:** 2026-11-11
**Status:** Draft for review

## Purpose

A Python CLI tool that reads Python source files and produces a **control-flow flowchart for each function**. The start node shows the parameters and return nodes show the returned value. Variable assignments can optionally be shown too. Output is static images (SVG/PNG) for people and JSON for machines. A future GUI explorer will read the JSON.

## Scope

**In scope (MVP)**
- Python source files (`.py`) parsed with the standard-library `ast` module.
- One flowchart per function: module-level functions, methods (`Class.method`), nested functions (`outer.inner`), and `async def`.
- Output formats: `json`, `dot`, `svg`, `png`, `mermaid`.
- Detail options: show/hide parameters, return values and variable assignments.

**Out of scope (for now)**
- Other languages. The architecture allows them (see "Frontends"), but none are built.
- The GUI explorer. Only its input format (JSON) is built now.
- Directory recursion, module-level (non-function) code, call graphs between functions.
- Exact exception edges (see "Known simplifications").

## Architecture

```
source file ──► Frontend (per language) ──► IR (Document) ──► Backends (shared)
                 PythonFrontend (ast)                          json | dot → svg/png | mermaid
```

- **Frontend**: turns one source file into a `Document`. It's selected by file extension through a small registry, so a new language means adding a module, not a new project.
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
- **Stable node IDs**: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}` for statements, with the suffix `~finally` for synthetic nodes and `~break@L{line}C{col}`/`~continue@L{line}C{col}` (naming the owning `try`) for nodes in duplicated finally bodies, so nested copies stay unique. IDs never contain `:`, because DOT reads it as port syntax.
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
- `try`: a `try` node, then the body. Each `except` handler is a node reached from the `try` node with an `exception` edge. `else` follows the body. If there's a `finally` block, everything that completes normally flows into a synthetic `finally` node, then into the finally body. A `break`/`continue` leaving the `try` also runs the finally body first. To keep paths distinct, the finally body is drawn once per path (`finally`, `finally (break)`, `finally (continue)`), and each copy continues to its own target: the next statement, the loop exit or the loop head. If the finally body ends the path itself (e.g. with its own `continue`), that overrides the pending transfer. `except*` works the same way.
- `with`: a node labelled `with <items>`, then the body.
- `return` and `raise` go to `end` and end the current path.
- A nested `def`/`class` becomes a process node in its parent, and nested functions also get their own chart.
- Skipped statements (no node): a docstring as the first statement, `pass`, `...`, `global`, `nonlocal`. Paths flow through them.
- Variable assignments (`=`, `+=`, annotated) get nodes only with `--variables`, **unless** the assigned value contains a call (then they're always shown).
- Code after `return`/`raise`/`break`/`continue` (unreachable) is still emitted as nodes with no incoming edges.
- Any statement type without its own rule becomes a process node labelled with its source text.

**Known simplifications** (documented, not bugs): exceptions are drawn as edges from the `try` node, not from each statement. `return`/`raise` inside `try … finally` go straight to `end` without passing through the finally body (unlike `break`/`continue`, which do).

## Labels

- Source text comes from `ast.unparse`. Whitespace runs collapse to one space, and text is truncated to `max_label_length` (default 60) with `…`.
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
| Syntax error (including compiler-only errors like `break` outside a loop), null bytes, missing file, unsupported extension | `path[:line]: error: message` on stderr; other files still processed | 1 |
| Unknown `--function` name | error listing the available qualnames | 1 |
| Two inputs with the same stem | error before anything is written | 1 |
| Code too deeply nested to parse or chart | `path: error: code is too deeply nested …`; other files still processed | 1 |
| An output file or directory cannot be written | `error: cannot write PATH: reason`; other outputs still written | 1 |
| `dot` binary missing while `svg`/`png` requested | error explaining how to install Graphviz; non-image outputs still written | 2 |
| File has no functions | warning on stderr; JSON with empty `functions` written if `json` is selected | 0 |

Source files are read as bytes so that PEP 263 coding cookies and BOMs are honoured. After `ast.parse`, the tree is also passed through `compile()` (never executed, with warnings suppressed), because `ast.parse` accepts some invalid programs that only the compiler rejects.

Mermaid labels escape `#` as `#35;` before any other entity substitution, so literal text like `#34;` in source code isn't turned into a quotation mark.

## Future work this design prepares for

- **GUI explorer** reading the JSON: source locations enable click-to-source, stable IDs enable linking and diffing, and `schema_version` enables format evolution.
- **More languages**: implement the `Frontend` protocol (probably with tree-sitter) and register the file extensions.
