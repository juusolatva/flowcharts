# Directory recursion and module-level code: design

Status: approved in brainstorming on 2026-11-13. Extends `2026-11-11-python-flowcharts-design.md` (the "main spec"). Where they disagree, this document wins, and the last implementation step folds it into the main spec.

## Goal

Remove two scope limits of the MVP:

1. Inputs can only be files. A directory should be walked recursively, so a whole project can be charted in one run.
2. Code outside functions is never charted. A file whose top level does work (a script, an `if __name__ == "__main__":` block) should get a module chart.

The tool is used on whole projects and on individual scripts about equally, so the defaults must suit both: library files whose top level only imports and defines things get no module chart, and scripts do.

Success means `pyflowcharts src/` writes a mirrored output tree with one JSON document per file, module charts appear exactly for files whose top level does work, and output stays deterministic.

## Decisions

| Question | Decision |
|---|---|
| When a module chart is built | When the top level has a statement that "does work" (see Module charts). `--no-module` turns module charts off. |
| Where it lives in the IR | A new `Document.module: Chart \| None`, with a new base type `Chart`. `SCHEMA_VERSION` becomes 2. |
| Module chart qualname and IDs | `<module>`; node IDs `<module>#start`, `<module>#end`, `<module>#L{line}C{col}[~suffix]`. A function qualname can never contain `<`, so they cannot collide. |
| Imports in module charts | Shown as process nodes, as inside functions. |
| Class bodies | Out of scope. They are charted only through their methods. |
| Directory output layout | Mirror the tree relative to the directory argument. |
| Which files a walk picks up | Supported extensions only; no hidden files or directories, no `__pycache__`, directory symlinks not followed; plus a repeatable `--exclude GLOB`. `.gitignore` is not consulted. |

## IR and JSON

`ir.py`:

```python
@dataclass
class Chart:
    qualname: str
    location: SourceLocation
    nodes: list[Node]
    edges: list[Edge]

@dataclass
class FunctionChart(Chart):
    name: str
    is_async: bool
    parameters: list[Parameter]
    returns: str | None

@dataclass
class Document:
    source: str
    language: str
    functions: list[FunctionChart]
    module: Chart | None = None
    schema_version: int = SCHEMA_VERSION  # 2
```

- `MODULE_QUALNAME = "<module>"` is defined in `ir.py` so the frontend, CLI and tests share it.
- `serialize.py` keeps using `dataclasses.asdict`, so inherited fields come first: a function chart's keys become `qualname`, `location`, `nodes`, `edges`, `name`, `is_async`, `parameters`, `returns`. This order change is part of the version 2 format. A module chart is written as `{"qualname", "location", "nodes", "edges"}`.
- The document gets a `"module"` key after `"functions"`: the chart object, or `null`.
- `from_json` accepts versions 1 and 2 and keeps the version it read in `schema_version`. A version 1 document is read with `module = None`. Other versions are rejected as today, with the message `unsupported schema_version X (expected 1 or 2)`.
- Backends (`to_dot`, `render`, `to_mermaid`) take a `Chart` instead of a `FunctionChart`. `to_mermaid` does not emit the qualname, so only its type hint changes. `to_digraph` must pass `graphviz.nohtml(chart.qualname)` as the graph name: `graphviz` leaves a name that looks like `<…>` unquoted as an HTML-like ID, so `<module>` would come out as `digraph <module> {` and Graphviz would strip the brackets.

## Module charts

### When a file gets one

The Python frontend looks at the module's top-level statements (not inside class or function bodies). The file gets a module chart if any of them is something other than:

- a docstring (a plain string expression as the first statement),
- `import …`, `from … import …`, `from __future__ import …`,
- `def` or `class`, decorated or not,
- an assignment: `=`, augmented (`+=`, …) or annotated, or a `type` alias statement,
- `pass`, `...`, `global`.

Assignments never trigger a module chart, even when the value contains a call. Library modules routinely have `logger = getLogger(__name__)` or `_PARSER = Parser(...)` at the top level, and those should not get charts. A script consisting only of assignments such as `res = run()` gets no module chart; that is accepted.

So `if __name__ == "__main__":`, any loop, `try`, `with`, `match`, `assert`, `del`, `raise` or a bare expression statement such as a call each make the file get a module chart. This check is Python-specific and lives in the frontend; `cfg/` does not change.

With `--no-module` (`ChartOptions.show_module = False`, added as the last field so positional construction keeps working) no module chart is built, and neither the "does work" check nor the module-only error checks below run. `ChartOptions`' docstring changes accordingly: options affect labels, which assignment nodes exist, and whether a module chart is built, never the data inside a chart.

### What it contains

The module's top-level statements, with a leading docstring dropped, go through the same statement conversion as a function body, with all its rules: imports and unhandled statements become process nodes, `def`/`class` become process nodes like nested definitions, plain assignments are hidden unless `--variables` is given, the value contains a call, or the block would otherwise look empty.

The chart is built with `build_chart("<module>", "module <stem>", location, body, options)`, where `<stem>` is the file's stem as given to the frontend (`load` for `src/pkg/io/load.py`) and `location` runs from the start of the module's first statement to the end of its last token, so leading comments (a shebang, a coding line) and trailing blank lines and comments are not included. `Source.location` does not change; the module chart takes its end from `Source.location(root)`. Its start node is labelled `module <stem>`, its end node `end`.

The frontend module `frontends/python/module.py` holds the "does work" check and builds the chart. `statements.py` gets `convert_statements(stmts, src, options)`, which drops a leading docstring and converts a statement list; `convert_body(func, …)` keeps its signature and calls it, and the module chart calls it with the root's children.

### Errors

- A syntax error outside every function (the existing module-skeleton check in `validate.py`) prints the existing warning, `syntax error outside functions; nearby code may be missing`, and the file gets no module chart, just as a function with a syntax error gets no chart.
- A `break` or `continue` at the top level, outside any loop (`StrayLoopTransfer` from the builder), skips the module chart with `path:line: warning: syntax error in module code; module chart skipped`. Module-level `return`, `yield` and `await` are already caught by `ast.parse` in the skeleton check.
- A tree-sitter `ERROR` or `MISSING` node outside every function subtree, when `ast.parse` accepts the module skeleton, means tree-sitter misread syntax that Python accepts (e.g. PEP 696 defaults, `type Box[T = int] = list[T]`). The module chart is skipped with `path:line: warning: unsupported syntax in module code; module chart skipped`, mirroring the per-function "unsupported syntax" warning. The "does work" check is not consulted first: a misread statement could look like work or hide it. Errors inside function subtrees are already handled per function and do not affect the module chart.
- The two module-only warnings above (stray `break`/`continue`, unsupported syntax) have `qualname = "<module>"`: they skip only the module chart, so they behave like a skipped function. `--function '<module>'` recognises `<module>` as skipped and prints the warning; `--function good` hides it and does not count it towards the exit code. The skeleton syntax-error warning keeps `qualname = None`, because it can affect functions too, so it is always shown.

## Directory inputs

### Arguments

```
pyflowcharts PATH [PATH ...] [-o OUTDIR] [-f FORMAT ...] [--variables]
             [--no-parameters] [--no-returns] [--no-module]
             [--function QUALNAME ...] [--exclude GLOB ...] [--max-label N]
```

Each `PATH` is a file (as today) or a directory, which is walked recursively.

### The walk

- A file is picked up if its extension is handled by some frontend. `frontends/__init__.py` gets `supported_extensions() -> tuple[str, ...]`, so the CLI does not hard-code `.py`. Other files in a walked directory are skipped silently; a file named explicitly with an unsupported extension is still an error.
- Files and directories whose name starts with `.` are skipped below the directory argument. The argument itself may be `.` or a hidden directory.
- `__pycache__` directories are skipped.
- Directory symlinks below the argument are not followed (no loops). A directory argument that is itself a symlink is walked, since the user named it.
- Only regular files are picked up (`is_file()`, which follows file symlinks), so a broken symlink or a socket named `*.py` is skipped silently. File symlinks to regular files are charted.
- A directory that cannot be read (`PermissionError` and other `OSError`s from the walk) is reported as `DIR: error: cannot read directory: reason`; the rest of the walk continues and the exit code is 1.
- Files are visited in sorted order of their relative path parts, so output is deterministic across platforms.

### `--exclude GLOB`

- Takes several values and can be repeated, like `--function`. Applies only to files found by a walk, never to files named explicitly.
- A pattern without `/` is matched against the name of every file and directory, so `--exclude venv tests '*_pb2.py'` matches those names at any depth.
- A pattern with `/` is matched against the path relative to the directory argument, in POSIX form: `--exclude 'scripts/old_*'`.
- A trailing `/` is stripped before matching and makes the pattern match directories only, as in `.gitignore`: `--exclude build/` prunes every directory named `build`, and `--exclude 'scripts/old_*/'` prunes matching directories under `scripts/`. A pattern that is only `/` is rejected as an argument error.
- A matched directory is not walked.
- Matching uses `fnmatch.fnmatchcase`, so it is case-sensitive on every platform, and `*` also matches `/` in path patterns.

### Output paths

Each input file gets an *output key*: a relative path without extension.

- A file named explicitly: its stem (`OUTDIR/<stem>…`, as today).
- A file found by a walk: its path relative to the directory argument, without extension (`src/pkg/io/load.py` walked from `src/` → `pkg/io/load`).

For a key `K`:

- `OUTDIR/K.json`: the JSON document (when `json` is selected).
- `OUTDIR/K.<ext>`: the module chart, for `dot`, `svg`, `png`, `mermaid` (`.mmd`).
- `OUTDIR/K/<qualname>.<ext>`: one file per function, as today. The directory is only created if the file has function charts.

Rules:

- The same file reached twice (resolved path) is charted once, under the first way it was reached (its path and output key). It counts as named explicitly if any of the ways reached it was explicit, so `pyflowcharts dir/ dir/empty.py` still warns `nothing to chart` for `empty.py`.
- Two different files with the same output key are an error before anything is written, generalising today's stem check: `error: output name collision: A and B both map to 'K'; run them separately with different --output directories`. Examples: `a/x.py` and `b/x.py` walked from `a/` and `b/`; `x.py` named explicitly and a walked `sub/x.py` from `sub/`.
- A key whose path segments are a proper prefix of another key's segments is also a collision, because `OUTDIR/K/` would mix one file's function charts with the other file's outputs. Example: `pkg/mod.py` beside the package `pkg/mod/` (keys `pkg/mod` and `pkg/mod/__init__`). Comparison is by segments, so `pkg/mod` and `pkg/mod_extra` do not collide. The check must run in both directions, because sorted walk order visits `pkg/mod/__init__.py` before `pkg/mod.py`. The message names both keys: `error: output name collision: A maps to 'pkg/mod' and B to 'pkg/mod/__init__', which would share the directory 'pkg/mod'; run them separately with different --output directories`.
- `Document.source` is the path as reached, e.g. `src/pkg/io/load.py`.

### Warnings

- `warning: PATH: no functions found` becomes `warning: PATH: nothing to chart`, printed when a file has no function charts, no module chart and no warnings at all (so a file whose only problem is a syntax error gets just that warning). It is decided on the full parse result, before `--function` filtering, so a file that merely has no requested function is not reported. It is only printed for files named explicitly; otherwise every empty `__init__.py` in a walk would trigger it.
- A directory argument whose walk yields no files, and reports no read error, gives `warning: DIR: no source files found` and does not change the exit code. An unreadable directory argument gets only the `cannot read directory` error. This is decided per argument, before deduplication across arguments, so `pyflowcharts dir/ dir/` does not warn.
- A missing path is reported as today: `path: error: no such file`.

## `--function`

- `<module>` is a valid name. It is listed among the available names when some processed file has a module chart, or as `<module> (skipped)` when a module chart was skipped with a `<module>` warning.
- The available list is deduplicated across files (first occurrence kept), so `<module>` or a common function name appears once.
- When `--function` is given, module charts are dropped unless `<module>` is among the names. With several files, `--function '<module>'` keeps every file's module chart.
- Function names match across all files, as today.
- Filtering builds the new document with `dataclasses.replace`, so `module` (when selected) and `schema_version` are preserved.

## Code structure

`cli.py` is about 290 lines and would pass the ~300-line guideline, so it is split:

- `cli.py`: argument parsing, the main flow, `--function` selection and exit codes.
- `inputs.py` (new): expands `PATH` arguments into inputs, applies `--exclude`, deduplicates, and checks for collisions. It imports only `supported_extensions()` from `frontends`. It returns the inputs, each `Input(path, key, explicit)`, plus the diagnostics found while expanding (empty directories, unreadable directories), in argument order. A missing or unsupported explicit file is passed through as an input; parsing reports it, as today.
- `output.py` (new): the writer, moved out of `cli.py`, extended to write module charts. It creates the parent directory of each file it writes when writing it, so a file that produces no outputs (e.g. `-f svg` on an empty `__init__.py`) leaves no empty directories behind.
- The `cli.py` epilog lists `--exclude` among the options that take several values.
- `frontends/python/module.py` (new): the "does work" check and module chart construction.

## Errors and exit codes

New or changed rows of the main spec's table:

| Situation | Behaviour | Exit |
|---|---|---|
| Stray top-level `break`/`continue` | `path:line: warning: syntax error in module code; module chart skipped`; other charts still written | 1 |
| Tree-sitter misreads top-level syntax that `ast` accepts | `path:line: warning: unsupported syntax in module code; module chart skipped`; other charts still written | 1 |
| Directory that cannot be read | `DIR: error: cannot read directory: reason`; rest of the walk continues | 1 |
| Syntax error outside every function | existing warning; the file also gets no module chart | 1 |
| Two inputs map to the same output key, or one key is a directory prefix of another | error before anything is written (replaces the stem check) | 1 |
| Directory with no source files | `warning: DIR: no source files found` | 0 |
| Explicit file with nothing to chart | `warning: PATH: nothing to chart` (replaces "no functions found"); not printed for walked files | 0 |

## Testing

Test-first, as usual. Chart shapes are asserted with `flow(chart)`.

- **Frontend:** each statement kind that does or does not trigger a module chart (including an assignment with a call, which does not); an `if __name__ == "__main__":` chart's flow; imports and `def`/`class` as process nodes; node IDs prefixed `<module>#`; the start label `module <stem>`; skeleton syntax error → no module chart, warning with `qualname = None`; stray top-level `break` → skipped, warning with `qualname = "<module>"`; top-level PEP 696 syntax → "unsupported syntax" warning, no module chart, functions still charted; `--no-module`.
- **IR/JSON:** version 2 round trip with and without a module chart; version 1 documents still load and keep `schema_version == 1`; other versions rejected with the new message; determinism.
- **DOT:** a module chart's DOT source starts with `digraph "<module>"`, and its SVG title keeps the brackets (when Graphviz is installed).
- **Inputs:** walk order; hidden files and directories, `__pycache__`, directory symlinks and broken file symlinks skipped; a symlinked directory argument walked; an unreadable directory reported; other extensions skipped in a walk but an error when explicit; `--exclude` name, path and trailing-`/` patterns; excluded directories pruned; deduplication of a file reached twice, with `explicit` set if either was explicit; collisions (`a/x.py` + `b/x.py`, explicit `x.py` + walked `x.py`, `pkg/mod.py` + package `pkg/mod/` in both orders) and the non-collision `pkg/mod` + `pkg/mod_extra`; a directory with no files, and `dir/ dir/` not warning.
- **CLI:** mirrored output tree; module chart files beside the JSON; no `K/` directory and no empty parent directories for files without outputs; `--function '<module>'` keeps module charts and other names drop them; `--function '<module>'` on a file whose module chart was skipped prints the warning, and `--function good` hides it with exit 0; the available list is deduplicated; `nothing to chart` only for explicit files, not after `--function` filtering, and not alongside a syntax warning; `--no-module`.

Existing tests that change:

- `tests/test_cli.py`: `test_missing_graphviz` monkeypatches `pyflowcharts.cli.render`, which moves to `pyflowcharts.output.render`; the tests that expect `no functions found` now expect `nothing to chart`.
- `tests/test_serialize.py` and `tests/test_python_frontend.py`: `schema_version == 1` becomes 2.
- `tests/test_python_statements.py` keeps calling `convert_body(func, …)`, whose signature does not change.

## Documentation

- The main spec: scope, IR (`Chart`, `module`, schema version 2), node IDs, output layout, CLI synopsis, `--function`, error table.
- `AGENTS.md`: node ID format with `<module>`, the architecture list (`inputs.py`, `output.py`), the CLI command example, and the known simplifications: remove directory recursion and module-level code from the out-of-scope line, and add that class bodies are charted only through their methods.
- `README.md`: the schema version, directory usage, `--exclude`, `--no-module`, module charts, the exit-code note, and the known simplifications list (remove directory recursion and module code).

## Out of scope

- Class bodies beyond their methods.
- `.gitignore` support.
- Call graphs.
