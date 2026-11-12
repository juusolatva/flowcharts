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
- `from_json` accepts versions 1 and 2. A version 1 document is read with `module = None`. Other versions are rejected as today.
- Backends (`to_dot`, `render`, `to_mermaid`) take a `Chart` instead of a `FunctionChart`. They only use `qualname`, `nodes` and `edges`, so only type hints change.

## Module charts

### When a file gets one

The Python frontend looks at the module's top-level statements (not inside class or function bodies). The file gets a module chart if any of them is something other than:

- a docstring (a plain string expression as the first statement),
- `import …`, `from … import …`, `from __future__ import …`,
- `def` or `class`, decorated or not,
- an assignment: `=`, augmented (`+=`, …) or annotated, or a `type` alias statement,
- `pass`, `...`, `global`.

So `if __name__ == "__main__":`, any loop, `try`, `with`, `match`, `assert`, `del`, `raise` or a bare expression statement such as a call each make the file get a module chart. This check is Python-specific and lives in the frontend; `cfg/` does not change.

With `--no-module` (`ChartOptions.show_module = False`) no module chart is built and the check is not run. `ChartOptions`' docstring changes accordingly: options affect labels, which assignment nodes exist, and whether a module chart is built, never the data inside a chart.

### What it contains

The module's top-level statements, with a leading docstring dropped, go through the same statement conversion as a function body, with all its rules: imports and unhandled statements become process nodes, `def`/`class` become process nodes like nested definitions, plain assignments are hidden unless `--variables` is given, the value contains a call, or the block would otherwise look empty.

The chart is built with `build_chart("<module>", "module <stem>", location, body, options)`, where `<stem>` is the file's stem as given to the frontend (`load` for `src/pkg/io/load.py`) and `location` spans the whole file. Its start node is labelled `module <stem>`, its end node `end`.

The frontend module `frontends/python/module.py` holds the "does work" check and builds the chart. `convert_body` is generalised to take the body's statement list, so functions and modules share it.

### Errors

- A syntax error outside every function (the existing module-skeleton check in `validate.py`) prints the existing warning, `syntax error outside functions; nearby code may be missing`, and the file gets no module chart, just as a function with a syntax error gets no chart.
- A `break` or `continue` at the top level, outside any loop (`StrayLoopTransfer` from the builder), skips the module chart with `path:line: warning: syntax error in module code; module chart skipped`. Module-level `return`, `yield` and `await` are already caught by `ast.parse` in the skeleton check.
- Module diagnostics have `qualname = None`, so `--function` never hides them.

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
- Directory symlinks are not followed (no loops). File symlinks are charted.
- Files are visited in sorted order of their relative path parts, so output is deterministic across platforms.

### `--exclude GLOB`

- Takes several values and can be repeated, like `--function`. Applies only to files found by a walk, never to files named explicitly.
- A pattern without `/` is matched against the name of every file and directory, so `--exclude venv tests '*_pb2.py'` matches those names at any depth.
- A pattern with `/` is matched against the path relative to the directory argument, in POSIX form: `--exclude 'scripts/old_*'`.
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

- The same file reached twice (resolved path) is charted once, under the first way it was reached.
- Two different files with the same output key are an error before anything is written, generalising today's stem check: `error: output name collision: A and B both map to 'K'; run them separately with different --output directories`. Examples: `a/x.py` and `b/x.py` walked from `a/` and `b/`; `x.py` named explicitly and a walked `sub/x.py` from `sub/`.
- A key that is a directory prefix of another key is also a collision, because `OUTDIR/K/` would mix one file's function charts with another file's outputs. Example: `pkg/mod.py` beside the package `pkg/mod/` (keys `pkg/mod` and `pkg/mod/__init__`). The message is the same, naming both files and the shorter key.
- `Document.source` is the path as reached, e.g. `src/pkg/io/load.py`.

### Warnings

- `warning: PATH: no functions found` becomes `warning: PATH: nothing to chart`, printed when a file has no function charts, no module chart and no skipped function or module chart. It is only printed for files named explicitly; otherwise every empty `__init__.py` in a walk would trigger it.
- A directory argument that yields no files gives `warning: DIR: no source files found` and does not change the exit code.
- A missing path is reported as today: `path: error: no such file`.

## `--function`

- `<module>` is a valid name. It is listed among the available names when some processed file has a module chart.
- When `--function` is given, module charts are dropped unless `<module>` is among the names. With several files, `--function '<module>'` keeps every file's module chart.
- Function names match across all files, as today.

## Code structure

`cli.py` is about 290 lines and would pass the ~300-line guideline, so it is split:

- `cli.py`: argument parsing, the main flow, `--function` selection and exit codes.
- `inputs.py` (new): expands `PATH` arguments into `(path, output key)` pairs, applies `--exclude`, deduplicates, and checks for collisions. It imports only `supported_extensions()` from `frontends`.
- `output.py` (new): the writer, moved out of `cli.py`, extended to write module charts.
- `frontends/python/module.py` (new): the "does work" check and module chart construction.

## Errors and exit codes

New or changed rows of the main spec's table:

| Situation | Behaviour | Exit |
|---|---|---|
| Stray top-level `break`/`continue` | `path:line: warning: syntax error in module code; module chart skipped`; other charts still written | 1 |
| Syntax error outside every function | existing warning; the file also gets no module chart | 1 |
| Two inputs map to the same output key, or one key is a directory prefix of another | error before anything is written (replaces the stem check) | 1 |
| Directory with no source files | `warning: DIR: no source files found` | 0 |
| Explicit file with nothing to chart | `warning: PATH: nothing to chart` (replaces "no functions found"); not printed for walked files | 0 |

## Testing

Test-first, as usual. Chart shapes are asserted with `flow(chart)`.

- **Frontend:** each statement kind that does or does not trigger a module chart; an `if __name__ == "__main__":` chart's flow; imports and `def`/`class` as process nodes; node IDs prefixed `<module>#`; the start label `module <stem>`; skeleton syntax error → no module chart; stray top-level `break` → skipped with the warning; `--no-module`.
- **IR/JSON:** version 2 round trip with and without a module chart; version 1 documents still load; determinism.
- **Inputs:** walk order; hidden files and directories, `__pycache__` and directory symlinks skipped; other extensions skipped in a walk but an error when explicit; `--exclude` name and path patterns; excluded directories pruned; deduplication of a file reached twice; collisions (`a/x.py` + `b/x.py`, explicit `x.py` + walked `x.py`, `pkg/mod.py` + package `pkg/mod/`); a directory with no files.
- **CLI:** mirrored output tree; module chart files beside the JSON; no `K/` directory for a file with only a module chart; `--function '<module>'` keeps module charts and other names drop them; `nothing to chart` only for explicit files; `--no-module`.

## Documentation

- The main spec: scope, IR (`Chart`, `module`, schema version 2), node IDs, output layout, CLI synopsis, `--function`, error table.
- `AGENTS.md`: node ID format with `<module>`, the architecture list (`inputs.py`, `output.py`), and a known simplification: class bodies are charted only through their methods.
- `README.md`: directory usage, `--exclude`, `--no-module`, module charts, the exit-code note.

## Out of scope

- Class bodies beyond their methods.
- `.gitignore` support.
- Call graphs.
