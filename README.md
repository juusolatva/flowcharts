# flowcharts

`pyflowcharts` reads Python source files (or whole directories of them) and draws a **control-flow flowchart for every function**: branches, loops, `try`/`except`/`finally`, `match`, `with`, returns and raises. The start node shows the function's parameters, return nodes show the returned value, and variable assignments can optionally be shown too. A file whose top level does work, such as a script with an `if __name__ == "__main__":` block, also gets a module-level chart. Charts are written as SVG/PNG images, DOT, Mermaid, and JSON.

The JSON output (schema version 2) is the stable, machine-readable format. It holds the full graph plus source locations and is meant for other tools, such as a future GUI explorer.

## Installation

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

SVG and PNG output also need the Graphviz `dot` executable:

```bash
sudo apt install graphviz     # Debian/Ubuntu
brew install graphviz         # macOS
```

JSON, DOT and Mermaid output work without Graphviz.

## Usage

```bash
uv run pyflowcharts mymodule.py                     # SVG + JSON into ./flowcharts
uv run pyflowcharts mymodule.py -f json mermaid     # choose formats
uv run pyflowcharts mymodule.py --variables         # also show plain assignments like `n = 0`
uv run pyflowcharts mymodule.py --function load Inventory.find   # only some functions
uv run pyflowcharts a.py b.py -o docs/charts --max-label 40
uv run pyflowcharts src/ --exclude tests 'migrations/'   # a whole tree, skipping some names
uv run pyflowcharts script.py --function '<module>'      # only the module-level chart
uv run pyflowcharts src/ --no-module                     # functions only
```

| Option | Meaning |
|---|---|
| `-o, --output OUTDIR` | Output directory (default `flowcharts`) |
| `-f, --format FORMAT ...` | Any of `json dot svg png mermaid` (default `svg json`) |
| `--variables` | Show assignments without calls (assignments containing a call are always shown, and so are assignments in a block that would otherwise be empty) |
| `--no-parameters` | Start node shows `def name(...)` instead of the full signature |
| `--no-returns` | Return nodes show `return` without the value |
| `--no-module` | Never draw module-level charts |
| `--function QUALNAME ...` | Only chart these functions (`<module>` selects module-level charts); repeatable |
| `--exclude GLOB ...` | When walking a directory, skip matching files and directories: a pattern without `/` matches names at any depth, one with `/` matches the path relative to the directory, and a trailing `/` matches directories only; repeatable |
| `--max-label N` | Truncate node labels to N characters (default 60) |

Put the input paths **before** options that take several values (`-f`, `--function`, `--exclude`).

A directory is walked recursively. Only files with a supported extension (`.py`) are charted; hidden files and directories, `__pycache__` and directory symlinks are skipped.

### Module-level charts

A file gets a module chart when its top level has a statement other than a docstring, imports, `def`/`class`, assignments, `type` aliases, `pass`, `...` or `global`, for example an `if __name__ == "__main__":` block, a loop, a `try` or a bare call. Library modules that only import and define things get none. Its start node reads `module <file stem>`, and its node IDs start with `<module>#`. Code in class bodies is charted only through the methods.

### Output layout

```
OUTDIR/
├── mymodule.json              # one JSON document per source file (if json selected)
├── mymodule.svg               # the module-level chart, if the file has one
└── mymodule/
    ├── load.svg               # one file per function and format
    ├── Inventory.find.svg
    └── Inventory.size@L25.svg # later duplicates (e.g. property setters) get @L<line>
```

Files found by walking a directory keep their path relative to it: `pyflowcharts src/` writes `src/pkg/io/load.py` to `OUTDIR/pkg/io/load.json`, `load.svg` and `load/`. Two inputs whose outputs would overlap (the same relative path, or `pkg/mod.py` beside a `pkg/mod/` package) are an error before anything is written.

Methods are named `Class.method` and nested functions `outer.inner`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (a file named on the command line with nothing to chart, or a directory with no source files, only produces a warning) |
| 1 | A function was skipped because of a syntax error (a warning names it; the other functions are still written), a file could not be read or decoded, an output file could not be written, a directory could not be read, an unknown `--function`, or two inputs would write the same outputs |
| 2 | SVG/PNG requested but Graphviz `dot` is not installed (other formats are still written) |

## How code maps to the chart

| Shape | Used for |
|---|---|
| oval | start (`def …`) and end |
| box | statements, `try`, `except …`, `finally`, `with …`, nested `def`/`class` |
| diamond | `if`, `match` (edges `True`/`False`, `case …`, `no match`) |
| hexagon | `for`/`while` (edges `next`/`done`, `True`/`False`) |
| parallelogram | `return` |
| octagon | `raise` |

`break`/`continue` inside `try … finally` pass through a copy of the finally body (labelled `finally (break)` / `finally (continue)`) on their way to the loop exit or head.

### Syntax errors

A function that does not parse is skipped with a warning such as `mod.py:12: warning: syntax error in 'broken'; function skipped`, and every other function in the file is still charted. A syntax error outside every function gives `warning: syntax error outside functions; nearby code may be missing`, and the file gets no module chart. A top-level `break`/`continue` outside a loop skips only the module chart (`warning: syntax error in module code; module chart skipped`). Any of these warnings makes the exit code 1. `--function` accepts skipped names, so selecting only valid functions gives exit 0.

### Known simplifications

- Handlers are assumed to catch whatever reaches them, so the uncaught path out of a `try` that has handlers is not drawn.
- Class bodies are charted only through their methods.
- Call graphs between functions are not drawn.

## Development

```bash
uv run pytest          # tests
uv run ruff check      # lint
uv run ruff format     # format
```

The architecture is frontend (tree-sitter, Python only for now) → language-neutral CFG engine → IR → backends (JSON, Graphviz, Mermaid). See `AGENTS.md` for the project rules and `docs/superpowers/specs/` for the design.
