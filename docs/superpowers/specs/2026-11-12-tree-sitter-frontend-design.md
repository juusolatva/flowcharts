# Tree-sitter Python frontend: design

Status: approved in brainstorming on 2026-11-12, revised after review the same day. Extends `2026-11-11-python-flowcharts-design.md` (the "main spec"). Where they disagree, this document wins, and step 5 of the migration folds it into the main spec.

## Goal

Replace the stdlib-`ast` Python frontend (`frontends/python_ast/`) with one built on tree-sitter. Python becomes the first language running on a shared, language-neutral CFG engine that later languages reuse.

Success means:

- `pyflowcharts` charts Python through tree-sitter, and `python_ast/` is gone.
- The CFG logic (frontier, branches, loops, `try`/`finally` copies, the reveal rule) lives in one language-neutral package that knows nothing about tree-sitter or Python.
- Files with syntax errors still produce charts for every function that tree-sitter recognises as a function and that Python's parser accepts.

Output may differ from the `ast` frontend where tree-sitter makes something better (e.g. labels). Every difference must be intentional (see Migration step 4).

## Decisions

| Question | Decision |
|---|---|
| Purpose | Replace `python_ast`. One engine for Python now, designed so other languages can reuse it. |
| Parity with today's output | Free to differ; differences must be intentional. |
| Syntax errors | Per function: chart clean functions, skip broken ones with a warning. |
| Validity check | Python's own parser (`ast.parse`) decides whether a function is valid; tree-sitter accepts some invalid Python without error nodes. `ast` is used for validation and for the constant test of `while` conditions, never to build the chart. |
| Charted language | A function is charted only if both parsers accept it. tree-sitter-python may support syntax the running interpreter rejects (e.g. `except A, B:` from PEP 758 on Python 3.13) or lag behind it. Such functions are skipped with the ordinary syntax-error warning. (A version hint was considered and dropped: tree-sitter has no error node for empty bodies or handler-less `try` either, so the hint would mislabel ordinary mistakes.) |
| Dependencies | `tree-sitter` and `tree-sitter-python` (one grammar wheel per language, not a language pack). `pyproject.toml` carries `tree-sitter>=0.25.2,!=0.26.0` and `tree-sitter-python>=0.25`; `uv.lock` pins exact versions released at least two weeks before they are added (on 2026-11-12: tree-sitter 0.25.2 and tree-sitter-python 0.25.0). tree-sitter 0.26.0 is excluded: it corrupts node positions and segfaults once several trees are alive and an identifier is 255+ bytes (reproduced; 0.26.1 fixes it but was three days old). |

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
  - `Try(loc, body, handlers: tuple[Handler, ...], orelse, finalbody: Block | None)`, `Handler(label, loc, body)`. `finalbody=()` is a `finally:` whose statements are all dropped (e.g. `pass`); it still gets a `finally` node. `None` means no `finally` clause.
  - `Terminal(kind: NodeKind, label, loc)`: `RETURN` or `RAISE`; goes to `end`.
  - `Break(loc)`, `Continue(loc)`.
- `builder.py`: `build_chart(qualname, start_label, start_loc, body, options) -> (nodes, edges)`. Owns the frontier walk, node IDs, the reveal rule, branches and loops. Node ID scheme is unchanged: `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}[~suffix]`, with `~finally` and the `~break@L…C…` / `~continue@L…C…` copy suffixes. A `Break`/`Continue` outside any loop raises `StrayLoopTransfer(kind, loc)`, a public exception the frontend turns into a diagnostic.
- `finally_.py`: the `try`/`finally` handling (pending `break`/`continue` routing and per-path finally-body copies), moved out of today's `cfg.py`.

**Reveal rule** (unchanged behaviour, now generic): when no statement in a block would get a node under the normal rules (every statement is a `hidden` step), the block's hidden steps are shown. Decided per block, including the function body.

**Model limits.** The model covers Python. It has no labelled `break`/`continue`, no loop whose test runs after the body (`do … while`), and no fall-through between branch arms (`switch`). A later language that needs them extends the model in its own spec.

### `frontends/python/` (replaces `frontends/python_ast/`)

Parses with tree-sitter, discovers functions, converts each function body into model statements, builds `Parameter`s, and calls the builder. Contains no graph logic.

### Unchanged

The IR, the JSON schema (no `SCHEMA_VERSION` bump), the backends, the registry, and the CLI's flags and output layout.

### Frontend protocol change

`Frontend.parse` returns `ParseResult(document: Document, warnings: tuple[Diagnostic, ...])` instead of a bare `Document`. `Diagnostic(path: str, line: int | None, message: str, qualname: str | None)` lives in `frontends/base.py` and renders as `path[:line]: warning: message`. `qualname` names the skipped function, or is `None` for an error outside functions; the CLI uses it for `--function` (see Error handling). Warnings are not part of the JSON.

## Python adapter

### Labels

- `source_text(node)`: the node's source with `comment` and `line_continuation` descendants removed, and each gap between tokens that contains whitespace (including newlines) replaced by one space, except that no space is written after `(`, `[`, `{` or before `)`, `]`, `}`, `,`, `.`. So a wrapped call becomes `g(1, 2)` and a wrapped chain `(df.filter().select())`. `string` nodes are atomic: their contents (including f-string interpolations) are kept verbatim. It never truncates and does not depend on any option.
- A label is `source_text` passed through `shorten`: all whitespace runs (including inside literals) collapse to one space, then the text is truncated to `max_label_length` with `…`. There is no `ast.unparse` fallback; multi-line code keeps its written form.
- Start label: `[async ]def name(<parameters>)[ -> <return type>]` built from source text, or `[async ]def name(...)` with `--no-parameters`. Parameters keep their written spacing (`d: str = 'x'`, where `ast.unparse` gave `d: str='x'`).
- `Parameter.annotation`, `Parameter.default` and `FunctionChart.returns` are `source_text`: complete, literal contents preserved (a default of `"a  b"` stays `"a  b"`), independent of `--max-label` and other display options.
- `return <expr>`, or `return` with `--no-returns` or no value.
- Intentional label differences from the `ast` frontend: `with (a as b, c)` keeps its parentheses; multi-line statements keep their written token order and spacing instead of being re-printed.

### Function discovery

Walk the whole tree, including the inside of `ERROR` nodes. Every `function_definition` (directly, inside a `decorated_definition`, a class body, a function body or any control-flow block) gets a chart. Qualnames: `Class.method`, `outer.inner`, built from the `class_definition`/`function_definition` ancestors tree-sitter still recognises (it keeps them for broken headers such as `class A(:`); later duplicates get `@L{line}` as today. `is_async` comes from the `async` keyword. A definition whose header tree-sitter cannot recover at all (e.g. `def f()` or `class A` without the colon) yields no `function_definition` and is not found; the error is reported as outside functions (see Error handling).

Parameter kinds come from the `parameters` node's children: `positional_separator` (`/`) ends the positional-only group, `keyword_separator` (`*`) or `list_splat_pattern` (`*args`) starts the keyword-only group, `dictionary_splat_pattern` is `**kwargs`; `identifier`, `typed_parameter`, `default_parameter` and `typed_default_parameter` are ordinary parameters (a `typed_parameter` may wrap a splat pattern).

### Locations

- `line = row + 1`, `column` = byte offset within the line (as with `ast`).
- End positions exclude trailing `comment` nodes: a tree-sitter `block` extends over a comment that follows its last statement, `ast` does not. The end of a function or compound statement is the end of its last non-comment descendant.
- The location of a decorated nested `def`/`class` is that of the inner `function_definition`/`class_definition`, not the `decorated_definition` (which starts at `@`), matching `ast`.
- An `elif` node ends at the end of its own clause. (`ast` extended it over the remaining `elif`/`else` chain.)

### Statement mapping

| Python (tree-sitter) | Model |
|---|---|
| docstring (first statement of the function body that is a `string` or `concatenated_string` without an `f`/`b` prefix), `...` expression, `pass`, `global`, `nonlocal` | dropped (paths flow through) |
| assignment, augmented assignment, annotated assignment (with or without value) | `Step(hidden=…)`; hidden unless the `right` field contains a `call` descendant (the target is not searched, so `x[g()] = 1` is hidden, as today) |
| `if` / `elif` / `else` | `Branch("if <cond>")`: arm `True`; `else` → arm `False`; no `else` → `default="False"`; each `elif` is a nested `Branch` in the `False` arm, located at the `elif_clause` |
| `match` | `Branch("match <subject>")`, one arm per case labelled `case <patterns>[ if <guard>]` (text from the first to the last `case_pattern`); `default="no match"` unless the last case is irrefutable: no guard and a single `case_pattern` that is `_`, a `dotted_name` with exactly one identifier (`case y:`; `case Foo.bar:` is a value pattern), or a `tuple_pattern` with exactly one such pattern and no comma (`case (y):`) |
| `for` / `async for` | `Loop("[async ]for <target> in <iter>", enter="next", exit="done")` |
| `while` | `Loop("while <cond>", enter="True", exit="False")`; `exit=None` when the condition is a single constant with a truthy value, the same rule as the `ast` frontend: `ast.parse(<cond source_text>, mode="eval")` gives an `ast.Constant` and `bool(value)` is true (`True`, `1`, `1.0`, `"x"`, `b"x"`, `...`, also `(1)`). `while 0.0`, `while ""` and non-constant conditions such as `(1,)` keep their exit |
| loop `else` | `Loop.orelse` |
| `try` / `except` / `except*` / `else` / `finally` | `Try`; handler labels `except[*][ <type>][ as <name>]`, i.e. the clause's source text from `except` up to the colon |
| `with` / `async with` | `Step("[async ]with <items>", body=…)` |
| `return`, `raise` | `Terminal(RETURN / RAISE)` |
| `break`, `continue` | `Break`, `Continue` |
| nested `def` | `Step(<its start label>)` |
| nested `class` | `Step("class <Name>")` |
| anything else | `Step(<source text>)` |

Unreachable code after `return`/`raise`/`break`/`continue` is still emitted, as today. A string expression anywhere other than the first statement is an ordinary `Step`, as today.

### Encodings

Source is decoded using the PEP 263 coding cookie or BOM (default UTF-8), with newlines normalised to `\n`, and re-encoded to UTF-8 before parsing, so columns are UTF-8 byte offsets, labels decode as UTF-8, and tree-sitter rows match the line numbers `ast.parse` reports. Undecodable source and null bytes are file-level errors checked before anything else (`ast.parse` would otherwise report a null byte as a syntax error in every function).

## Error handling

### Per-function syntax errors

Tree-sitter's grammar accepts some invalid Python without `ERROR` or `MISSING` nodes, for example empty bodies (`def f():` with nothing after it), `try:` with no `except` or `finally`, and inconsistent indentation (an over-indented line is folded into the enclosing block). So validity is decided by Python's own parser. All checks work on the UTF-8 bytes (so byte columns from tree-sitter apply) and decode just before `ast.parse`.

1. **Fast path.** `ast.parse` on the whole decoded file. If it succeeds, every function is syntactically valid for this interpreter.
2. **Module skeleton.** Otherwise the file is parsed again with every outermost function stubbed: everything after the function's name to the end of its subtree is replaced by `(): pass` followed by blanks (each character except newlines becomes a space, so line numbers are unchanged). Stubbing from the name rather than the colon keeps a broken signature such as `def f(:` out of the skeleton, so it is attributed to the function. Decorators stay, since they belong to the enclosing scope. If this fails, the error is outside functions and is reported with the line `ast.parse` gives; functions are still checked individually.
3. **Per function.** Each function's validation source is the lines from its `def`/`async` (decorators excluded) to the end of its subtree, with every nested function stubbed the same way. A function that doesn't start at column 0 is preceded by an `if 1:` header on a line of its own. The source goes through `ast.parse` (not `compile()`, so scope checks such as `nonlocal` in an isolated nested function can't give false positives). The reported line is mapped back to the file and clamped into the function's line range: `ast` reports a missing body at the next token, which in a slice is the end of the slice, so an empty body is reported at the function's own lines.
4. **Tree-sitter errors.** A function is charted only if it passes step 1 or 3, has no `ERROR` or `MISSING` nodes in its own tree-sitter subtree (nested `function_definition` subtrees excluded; their errors count only against the nested function, and the outer chart still shows it as a `def` step), and passes the `break`/`continue` check below.
5. If step 1 failed, step 2 passed and every function passes, the error is in code tree-sitter attached to no function it recognised (e.g. a `def` without its colon); it is still reported as outside functions, with the line from step 1.

Warnings:

- A skipped function: `path:LINE: warning: syntax error in '<qualname>'; function skipped`, where LINE is the mapped, clamped line from step 3. When only tree-sitter finds a problem (the interpreter accepts the function, e.g. PEP 696 type-parameter defaults on a grammar that predates them), the message is `unsupported syntax in '<qualname>'; function skipped` and LINE is the first `ERROR`/`MISSING` node.
- `ast.parse` is run with warnings suppressed: a `SyntaxWarning` about the user's code (an invalid escape such as `"\d"`) is neither printed nor allowed to become an error under `-W error`.
- An error outside every function: `path:LINE: warning: syntax error outside functions; nearby code may be missing`, with LINE from step 2 (or step 1 in case 5). At most one such warning per file.
- `break`/`continue` outside a loop (which both tree-sitter and `ast.parse` accept) is treated as a syntax error in that function: the builder raises `StrayLoopTransfer`, the frontend reports the transfer's line. Other compiler-only errors (duplicate parameter names, `await` outside `async`, `nonlocal` without a binding, …) are not checked and are charted as written.

### Exit codes

- Any syntax-error warning (a skipped function or an error outside functions): exit 1. All other output is still written. The existing "no functions found" warning still exits 0.
- A file whose functions are all skipped still writes its JSON (when selected) with an empty `functions` list, exits 1, and does not additionally warn "no functions found".

### `--function` and skipped functions

- The names `--function` accepts are the charted qualnames plus the skipped ones (`Diagnostic.qualname`). A skipped name is a recognised selection, not an unknown one.
- Unknown names still abort before anything is written, as today. The error lists the available names, with skipped ones marked: `available: f, g (skipped)`.
- A selected skipped function writes nothing, its warning is printed and the exit code is 1. The other selected functions are still written: `--function good broken` writes `good` and exits 1.
- Warnings for skipped functions that weren't selected are not printed and don't affect the exit code. Warnings for errors outside functions are always printed and give exit 1, since they may hide selected code.

### File-level errors (unchanged behaviour)

`path[:line]: error: message`, exit 1, other files still processed:

- undecodable source (bad coding cookie, invalid bytes) or null bytes,
- missing file, unsupported extension,
- code too deeply nested to chart (`RecursionError` or `MemoryError` in the validating `ast.parse`, the adapter or the builder).

The main spec's paragraph about running `compile()` after `ast.parse` is replaced by the validation described under Per-function syntax errors.

## Testing

- `tests/test_builder.py`: model statements built by hand, asserting on `flow()`. Covers branch defaults, loops without an exit, reveal per block, `finally` copies and `StrayLoopTransfer`.
- `conftest.chart_of` uses the new frontend, so the existing CFG tests become its acceptance tests. Intentional output changes update the test and are named in the commit message.
- New tests:
  - a broken function (a body error, or `def f(:`) is skipped and its neighbours are charted; a well-formed method inside a class with a broken header (`class A(:`) is found as `A.m`; an error in a nested function's body keeps the outer chart; a `def` without its colon gives the outside-functions warning and the following function is still charted;
  - invalid Python that tree-sitter accepts is still caught: an empty function body (reported at the function's own line, not the end of the file), empty `if`/`for`/`while`/`with`/`try`/`except`/`finally` bodies, `try` with no handler, inconsistent indentation; a nested function with an empty body is skipped while its outer function is charted; a nested function using `nonlocal` is not a false positive; the reported line numbers point at the right file line, including for indented methods;
  - a file with both a broken function and a broken module-level statement gets both warnings;
  - a decorator with a syntax error gives the outside-functions warning;
  - null bytes are a file-level error, not per-function warnings;
  - `break` outside a loop is reported as a syntax error in that function;
  - CLI: warnings on stderr, exit 1, output still written; all functions skipped writes empty JSON without "no functions found";
  - `--function`: `good broken` writes `good` and exits 1; an unknown name still aborts and lists skipped names as `(skipped)`; selecting only a good function in a file with an unselected broken one exits 0 with no warning; an error outside functions still warns and exits 1;
  - `while` with `1.0`, `"x"`, `b"x"` and `(1)` conditions has no exit edge, and code after it has no incoming edges; `while 0.0` and `while ""` keep the exit;
  - `match`: `case y:` and `case (y):` are irrefutable, `case Foo.bar:` and `case y if g:` are not;
  - metadata: a default of `"a  b"` and a long annotation are stored complete and unchanged for every `--max-label`;
  - labels: multi-line code without comments or continuations (`g(1, 2)` from a wrapped call, no space after `(` or before `)`/`,`/`.`), the signature from source, an f-string first statement is not a docstring, latin-1 source with a coding cookie, CRLF line endings;
  - locations: byte columns after non-ASCII text; a function's end line ignores a trailing comment; a decorated nested function is located at its `def`.
- Existing invariant and determinism tests run against the new frontend.

## Migration

On branch `feat/tree-sitter-frontend`, merged through a PR.

1. **Shared engine, no behaviour change.** Add `cfg/model.py`, `cfg/builder.py`, `cfg/finally_.py` with their unit tests; turn `python_ast/cfg.py` into an `ast` → model adapter. All existing tests pass unchanged.
2. **Protocol change.** `ParseResult`/`Diagnostic` in `frontends/base.py`, the CLI prints warnings; `python_ast` returns no warnings yet.
3. **Tree-sitter adapter** in `frontends/python/`, with validation. Switch `conftest` and the registry to it, update tests for intentional differences, add the new tests.
4. **Comparison run** (one-off, not committed): chart the stdlib with both frontends, with and without `--variables`, and compare per function the `flow()` triples, the node IDs and the node and function locations. Classify every difference as intended or a bug. Bugs get a regression test first.

   Outcome (2026-11-12, CPython 3.13.14 stdlib, 573 files, 14358 functions, both option sets): no function skipped, none missing, every node ID and start position identical. Three bugs found and fixed with regression tests: `type(x).attr = v` parsed by the grammar as a PEP 695 alias (lost its hidden-assignment status), chained assignments counting calls in nested targets, and multi-line `case` patterns bypassing the label rule. Remaining differences were all intentional: labels, defaults and return annotations keeping source quoting, implicit string concatenation, parentheses and spacing; and `elif` node end positions (see Locations).
5. **Remove `python_ast/`** and update the main spec (labels, statement rules, errors, dependencies, exit codes), AGENTS.md (allowed dependencies, architecture diagram, `python_ast` references) and the README (exit codes, warnings).

## Out of scope

- Other languages (the engine is built for them; adding one is a separate spec). See Model limits for what such a spec must add.
- Skipped-function information in the JSON (would need a schema bump).
- The tighter CFG modelling and scope additions listed in AGENTS.md's known simplifications.
