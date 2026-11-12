# Tree-sitter Python frontend: design

Status: approved in brainstorming on 2026-11-12. Extends `2026-11-11-python-flowcharts-design.md` (the "main spec"). Where they disagree, this document wins, and step 5 of the migration folds it into the main spec.

## Goal

Replace the stdlib-`ast` Python frontend (`frontends/python_ast/`) with one built on tree-sitter. Python becomes the first language running on a shared, language-neutral CFG engine that later languages reuse.

Success means:

- `pyflowcharts` charts Python through tree-sitter, and `python_ast/` is gone.
- The CFG logic (frontier, branches, loops, `try`/`finally` copies, the reveal rule) lives in one language-neutral package that knows nothing about tree-sitter or Python.
- Files with syntax errors still produce charts for every function that parses cleanly.

Output may differ from the `ast` frontend where tree-sitter makes something better (e.g. labels). Every difference must be intentional (see Migration step 4).

## Decisions

| Question | Decision |
|---|---|
| Purpose | Replace `python_ast`. One engine for all languages. |
| Parity with today's output | Free to differ; differences must be intentional. |
| Syntax errors | Per function: chart clean functions, skip broken ones with a warning. |
| Validity check | Python's own parser (`ast.parse`) decides whether a function is valid; tree-sitter accepts some invalid Python without error nodes. `ast` is used only for validation, never for charting. |
| Architecture | Neutral statement model + one shared CFG builder; each language is an adapter. |
| Dependencies | `tree-sitter` and `tree-sitter-python` (one grammar wheel per language, not a language pack). Pin exact versions released at least two weeks before they are added. |

## Architecture

```
source bytes ──► frontends/python/ ──► cfg.model ──► cfg.builder ──► IR (Document) ──► backends
                 tree-sitter adapter    neutral       shared
                                        statements    CFG engine
```

### `pyflowcharts/cfg/` (new, language-neutral)

Imports neither tree-sitter nor anything from `frontends/`. Same layering rule as the backends.

- `model.py`: frozen dataclasses. `Block = tuple[Stmt, ...]`. Every statement carries `loc: SourceLocation`.
  - `Step(label, loc, body: Block = (), hidden: bool = False)`: one process node, then `body` (if any) continues from it. Used for expressions, `with`, nested `def`/`class`, assignments, and any statement without its own rule. `hidden=True` means the node is shown only with `--variables` or by the reveal rule.
  - `Branch(label, loc, arms: tuple[Arm, ...], default: str | None)`, `Arm(edge_label, body)`: a decision node. Each arm leaves on its edge label into its body. `default`, if not `None`, is an extra edge label that leaves the decision with no body (falls through to the next statement).
  - `Loop(label, loc, enter: str, exit: str | None, body, orelse)`: `exit=None` means only `break` leaves the loop.
  - `Try(loc, body, handlers: tuple[Handler, ...], orelse, finalbody: Block | None)`, `Handler(label, loc, body)`.
  - `Terminal(kind: NodeKind, label, loc)`: `RETURN` or `RAISE`; goes to `end`.
  - `Break(loc)`, `Continue(loc)`.
- `builder.py`: `build_chart(qualname, start_label, start_loc, body, options) -> (nodes, edges)`. Owns the frontier walk, node IDs, the reveal rule, branches and loops. Node ID scheme is unchanged: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}[~suffix]`, with `~finally` and the `~break@L…C…` / `~continue@L…C…` copy suffixes.
- `finally_.py`: the `try`/`finally` handling (pending `break`/`continue` routing and per-path finally-body copies), moved out of today's `cfg.py`.

**Reveal rule** (unchanged behaviour, now generic): when no statement in a block would get a node under the normal rules (every statement is a `hidden` step), the block's hidden steps are shown. Decided per block, including the function body.

### `frontends/python/` (replaces `frontends/python_ast/`)

Parses with tree-sitter, discovers functions, converts each function body into model statements, builds `Parameter`s, and calls the builder. Contains no graph logic.

### Unchanged

The IR, the JSON schema (no `SCHEMA_VERSION` bump), the backends, the registry, and the CLI's flags and output layout.

### Frontend protocol change

`Frontend.parse` returns `ParseResult(document: Document, warnings: tuple[Diagnostic, ...])` instead of a bare `Document`. `Diagnostic(path: str, line: int | None, message: str, qualname: str | None)` lives in `frontends/base.py` and renders as `path[:line]: warning: message`. `qualname` names the skipped function, or is `None` for an error outside functions; the CLI uses it for `--function` (see Error handling). Warnings are not part of the JSON.

## Python adapter

### Labels

- `source_text(node)`: the node's source with `comment` and `line_continuation` descendants removed, and each gap between tokens that contains whitespace (including newlines) replaced by one space. The contents of string and bytes literals are kept verbatim. It never truncates and does not depend on any option.
- A label is `source_text` passed through `shorten`: all whitespace runs (including inside literals) collapse to one space, then the text is truncated to `max_label_length` with `…`. There is no `ast.unparse` fallback; multi-line code keeps its written form.
- Start label: `[async ]def name(<parameters>)[ -> <return type>]` built from source text, or `[async ]def name(...)` with `--no-parameters`.
- `Parameter.annotation`, `Parameter.default` and `FunctionChart.returns` are `source_text`: complete, literal contents preserved (a default of `"a  b"` stays `"a  b"`), independent of `--max-label` and other display options.
- `return <expr>`, or `return` with `--no-returns` or no value.

### Function discovery

Walk the whole tree, including the inside of `ERROR` nodes. Every `function_definition` (directly, inside a `decorated_definition`, a class body, a function body or any control-flow block) gets a chart. Qualnames: `Class.method`, `outer.inner`; later duplicates get `@L{line}` as today. `is_async` comes from the `async` keyword.

### Statement mapping

| Python (tree-sitter) | Model |
|---|---|
| docstring as first statement, `...` expression, `pass`, `global`, `nonlocal` | dropped (paths flow through) |
| assignment, augmented assignment, annotated assignment (with or without value) | `Step(hidden=not contains a call)` |
| `if` / `elif` / `else` | `Branch("if <cond>")`: arm `True`; `else` → arm `False`; no `else` → `default="False"`; each `elif` is a nested `Branch` in the `False` arm |
| `match` | `Branch("match <subject>")`, one arm per case labelled `case <pattern>[ if <guard>]`; `default="no match"` unless the last case is a bare capture name or `_` with no guard |
| `for` / `async for` | `Loop("[async ]for <target> in <iter>", enter="next", exit="done")` |
| `while` | `Loop("while <cond>", enter="True", exit="False")`; `exit=None` when the condition is a single constant with a truthy value, the same rule as the `ast` frontend: `ast.parse(<cond>, mode="eval")` gives an `ast.Constant` and `bool(value)` is true (`True`, `1`, `1.0`, `"x"`, `b"x"`, `...`). `while 0.0`, `while ""` and non-constant conditions such as `(1,)` keep their exit |
| loop `else` | `Loop.orelse` |
| `try` / `except` / `except*` / `else` / `finally` | `Try`; handler labels `except[*][ <type>][ as <name>]` |
| `with` / `async with` | `Step("[async ]with <items>", body=…)` |
| `return`, `raise` | `Terminal(RETURN / RAISE)` |
| `break`, `continue` | `Break`, `Continue` |
| nested `def` | `Step(<its start label>)` |
| nested `class` | `Step("class <Name>")` |
| anything else | `Step(<source text>)` |

Unreachable code after `return`/`raise`/`break`/`continue` is still emitted, as today.

### Locations and encodings

- `line = row + 1`, `column` = byte offset within the line (as with `ast`).
- Source is decoded using the PEP 263 coding cookie or BOM (default UTF-8) and re-encoded to UTF-8 before parsing, so columns are UTF-8 byte offsets and labels decode as UTF-8.

## Error handling

### Per-function syntax errors

- Tree-sitter's grammar accepts some invalid Python without `ERROR` or `MISSING` nodes, for example empty bodies (`def f():` with nothing after it), `try:` with no `except` or `finally`, and inconsistent indentation (an over-indented line is folded into the enclosing block). So validity is decided by Python's own parser:
  1. Fast path: `ast.parse` on the whole (decoded) file. If it succeeds, every function is syntactically valid.
  2. Otherwise each function is checked on its own. Its validation source is the file text with everything outside the function's byte range (from `def`/`async`, decorators excluded) blanked, and the body of every nested function replaced by `pass` followed by blanks. Blanking replaces each character except newlines with a space, so lines and columns are unchanged. A function that doesn't start at column 0 is preceded by an `if 1:` header on a line of its own, and the reported line numbers are mapped back to the file. The source goes through `ast.parse` (not `compile()`, so scope checks such as `nonlocal` in an isolated nested function can't give false positives).
  3. A function is charted only if it passes step 1 or 2, has no `ERROR` or `MISSING` nodes in its own tree-sitter subtree (nested function bodies excluded), and passes the `break`/`continue` check below. Errors inside a nested function's body count only against the nested function; the outer chart still shows it as a `def` step.
  4. If step 1 failed but every function passes, the error is outside functions.
- A skipped function produces `path:LINE: warning: syntax error in '<qualname>'; function skipped`, where LINE is the line `ast.parse` reports (or the first `ERROR`/`MISSING` node when only tree-sitter finds a problem).
- An error outside every function produces `path:LINE: warning: syntax error outside functions; nearby code may be missing`, with LINE from the whole-file `ast.parse`.
- `break`/`continue` outside a loop (which both tree-sitter and `ast.parse` accept) is treated as a syntax error in that function. Other compiler-only errors (duplicate parameter names, `await` outside `async`, `nonlocal` without a binding, …) are not checked and are charted as written.

### Exit codes

- Any syntax-error warning (a skipped function or an error outside functions): exit 1. All other output is still written. The existing "no functions found" warning still exits 0.
- A file whose functions are all skipped still writes its JSON (when selected) with an empty `functions` list, and exits 1.

### `--function` and skipped functions

- The names `--function` accepts are the charted qualnames plus the skipped ones (`Diagnostic.qualname`). A skipped name is a recognised selection, not an unknown one.
- Unknown names still abort before anything is written, as today. The error lists the available names, with skipped ones marked: `available: f, g (skipped)`.
- A selected skipped function writes nothing, its warning is printed and the exit code is 1. The other selected functions are still written: `--function good broken` writes `good` and exits 1.
- Warnings for skipped functions that weren't selected are not printed and don't affect the exit code. Warnings for errors outside functions are always printed and give exit 1, since they may hide selected code.

### File-level errors (unchanged behaviour)

`path[:line]: error: message`, exit 1, other files still processed:

- undecodable source (bad coding cookie, invalid bytes) or null bytes,
- missing file, unsupported extension,
- code too deeply nested to chart (`RecursionError` in the adapter or builder).

The main spec's paragraph about running `compile()` after `ast.parse` is replaced by the validation described under Per-function syntax errors.

## Testing

- `tests/test_builder.py`: model statements built by hand, asserting on `flow()`. Covers branch defaults, loops without an exit, reveal per block, and `finally` copies.
- `conftest.chart_of` uses the new frontend, so the existing CFG tests become its acceptance tests. Intentional output changes update the test and are named in the commit message.
- New tests:
  - a broken function is skipped and its neighbours are charted; a well-formed function inside an `ERROR` region is found; an error in a nested function's body keeps the outer chart;
  - invalid Python that tree-sitter accepts is still caught: an empty function body, empty `if`/`for`/`while`/`with`/`try`/`except`/`finally` bodies, `try` with no handler, inconsistent indentation; a nested function using `nonlocal` is not a false positive; the reported line numbers point at the right file line, including for indented methods;
  - `break` outside a loop is reported as a syntax error in that function;
  - CLI: warnings on stderr, exit 1, output still written;
  - `--function`: `good broken` writes `good` and exits 1; an unknown name still aborts and lists skipped names as `(skipped)`; selecting only a good function in a file with an unselected broken one exits 0 with no warning; an error outside functions still warns and exits 1;
  - `while` with `1.0`, `"x"` and `b"x"` conditions has no exit edge, and code after it has no incoming edges; `while 0.0` and `while ""` keep the exit;
  - metadata: a default of `"a  b"` and a long annotation are stored complete and unchanged for every `--max-label`;
  - labels: multi-line code without comments or continuations, the signature from source, latin-1 source with a coding cookie;
  - locations: byte columns after non-ASCII text.
- Existing invariant and determinism tests run against the new frontend.

## Migration

On branch `feat/tree-sitter-frontend`, merged through a PR.

1. **Shared engine, no behaviour change.** Add `cfg/model.py`, `cfg/builder.py`, `cfg/finally_.py`; turn `python_ast/cfg.py` into an `ast` → model adapter. All existing tests pass unchanged.
2. **Builder unit tests** on the model.
3. **Tree-sitter adapter** in `frontends/python/`, plus `ParseResult` / `Diagnostic` and CLI warning handling. Switch `conftest` and the registry to it.
4. **Comparison run** (one-off, not committed): chart the stdlib with both frontends, compare `flow()` triples per function, and classify every difference as intended or a bug. Bugs get a regression test first.
5. **Remove `python_ast/`** and update the main spec (labels, statement rules, errors, dependencies), AGENTS.md (allowed dependencies, architecture diagram, `python_ast` references) and the README.

## Out of scope

- Other languages (the engine is built for them; adding one is a separate spec).
- Skipped-function information in the JSON (would need a schema bump).
- The tighter CFG modelling and scope additions listed in AGENTS.md's known simplifications.
