# flowcharts

[![CI](https://github.com/juusolatva/flowcharts/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/juusolatva/flowcharts/actions/workflows/ci.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=juusolatva_flowcharts&metric=alert_status)](https://sonarcloud.io/summary/overall?id=juusolatva_flowcharts)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=juusolatva_flowcharts&metric=coverage)](https://sonarcloud.io/summary/overall?id=juusolatva_flowcharts)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/github/license/juusolatva/flowcharts)](LICENSE)

`pyflowcharts` reads Python source files (or whole directories of them) and draws a **control-flow flowchart for every function**: branches, loops, `try`/`except`/`finally`, `match`, `with`, returns and raises. The start node shows the function's parameters, return nodes show the returned value, and variable assignments can optionally be shown too. A file whose top level does work, such as a script with an `if __name__ == "__main__":` block, also gets a module-level chart. Each run also draws a **call graph** of the charted functions, clustered by file. Charts are written as SVG/PNG images, DOT, Mermaid, and JSON, or browsed in a local web app that updates as you edit (see [Exploring](#exploring)).

The JSON output (schema version 3) is the stable, machine-readable format. It holds the full graph, source locations and every call with its resolved target, and is meant for other tools, such as the explorer.

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
| `--no-call-graph` | Do not write the run's call graph picture (the JSON still records calls) |
| `--function QUALNAME ...` | Only chart these functions (`<module>` selects module-level charts); repeatable |
| `--exclude GLOB ...` | When walking a directory, skip matching files and directories: a pattern without `/` matches names at any depth, one with `/` matches the path relative to the directory, and a trailing `/` matches directories only; repeatable |
| `--max-label N` | Truncate node labels to N characters (default 60) |
| `--version` | Print the version and exit |

Put the input paths **before** options that take several values (`-f`, `--function`, `--exclude`).

A directory is walked recursively. Only files with a supported extension (`.py`) are charted; hidden files and directories, `__pycache__` and directory symlinks are skipped.

### Module-level charts

A file gets a module chart when its top level has a statement other than a docstring, imports, `def`/`class`, assignments, `type` aliases, `pass`, `...` or `global`, for example an `if __name__ == "__main__":` block, a loop, a `try` or a bare call. Library modules that only import and define things get none. Its start node reads `module <file stem>`, and its node IDs start with `<module>#`. Code in class bodies is charted only through the methods.

### Output layout

```
OUTDIR/
├── callgraph.svg              # the run's call graph (not for json-only runs)
├── mymodule.json              # one JSON document per source file (if json selected)
├── mymodule.svg               # the module-level chart, if the file has one
└── mymodule/
    ├── load.svg               # one file per function and format
    ├── Inventory.find.svg
    └── Inventory.size@L25.svg # later duplicates (e.g. property setters) get @L<line>
```

Files found by walking a directory keep their path relative to it: `pyflowcharts src/` writes `src/pkg/io/load.py` to `OUTDIR/pkg/io/load.json`, `load.svg` and `load/`. Two inputs whose outputs would overlap (the same relative path, or `pkg/mod.py` beside a `pkg/mod/` package) are an error before anything is written, and so is a file whose output would be `callgraph` (rename it, or pass `--no-call-graph`). Functions in one file whose names differ only in case (`Foo` and `foo`) give a warning, because their files overwrite each other on case-insensitive file systems such as the macOS and Windows defaults; the exit code is not affected.

Methods are named `Class.method` and nested functions `outer.inner`.

### Call graphs

Every chart's JSON lists its calls: the node each call is written in, the callee text, the candidate targets, and the `target` chart in this run when one matches. `OUTDIR/callgraph.<ext>` draws one node per chart and one edge per caller/callee pair, clustered by file. With `--function`, it shows only the selected charts.

Calls are resolved statically: names defined in the file (innermost function scope first), `self.method()` and `cls.method()` inside a class, `Class.method()`, and `import` / `from … import` (absolute and relative) into other files of the same run. Module names come from the walked paths, so walk the import root: `pyflowcharts src/` (not `src/mypkg/`) for a `src` layout.

A parameter named like a function hides it, as in Python. Not resolved: shadowing by local assignment or `for`/`with`/`except` targets, inheritance, decorators that replace functions, `getattr` and other dynamic calls, star imports, `global`/`nonlocal` rebinding, and calls through instance attributes other than `self.method`/`cls.method`. Such calls are still listed, with no target.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (a file named on the command line with nothing to chart, or a directory with no source files, only produces a warning) |
| 1 | A function was skipped because of a syntax error (a warning names it; the other functions are still written), a file could not be read or decoded, an output file could not be written, a directory could not be read, an unknown `--function`, or two inputs would write the same outputs |
| 2 | SVG/PNG requested but Graphviz `dot` is not installed (other formats are still written) |

## Exploring

```bash
uv run pyflowcharts explore src/                  # browse a tree in the browser
uv run pyflowcharts explore a.py b.py --port 8765 --no-browser
```

`explore` parses the given files or directories, starts a local web app and opens it in your browser (the URL is also printed). It needs the Graphviz `dot` executable, since the server draws the charts.

The app opens on the run's call graph. The sidebar lists the files and their charts, with a search box above them.

- Click a function in the call graph or the sidebar to open its flowchart. Each chart has its own address, so the browser's back and forward buttons work.
- The top bar shows **Called by** and **Calls** links for the open chart.
- Nodes that call charted functions are underlined. Click a node to select it: its source lines are highlighted and the strip above the chart lists its calls. Double-click it to open the callee when it calls exactly one charted function.
- Click a source line to select the node that covers it. If the line belongs to another function, a "go to" link opens that one. The source pane can be collapsed.
- Drag to pan and use the mouse wheel to zoom; the fit, + and − buttons reset and step the zoom.
- Press `/` to search by function name or file path; arrow keys move through the matches and Enter opens one.
- Light and dark mode follow the system setting.

| Option | Meaning |
|---|---|
| `--port N` | Port to listen on, 0 to 65535 (default 0, a free port) |
| `--no-browser` | Only print the URL |
| `--version` | Print the version and exit |
| `--variables`, `--no-parameters`, `--no-returns`, `--no-module`, `--max-label N` | As for charting |
| `--exclude GLOB ...` | As for charting; put the input paths before it |

`-o`, `-f`, `--function` and `--no-call-graph` do not exist here. A file literally named `explore` must be passed as `./explore`.

The server listens on `127.0.0.1` only and rejects requests for other host names. The printed URL carries a random token that is exchanged for a cookie (named per port, so two explorers can run side by side); requests without it get 403. Browsers send cookies to every server on `127.0.0.1`/`localhost` regardless of port, so other local servers you run can see the token cookie; it stays valid only while that explorer runs. Press Ctrl+C to stop.

The explorer watches the files and directories you gave it, including files added or deleted later. Within a second or two of saving a change, it re-parses the whole run, so charts, calls and source stay current, and the browser updates itself while keeping the selected node. The dot beside the search box is green when connected, yellow while re-parsing and red while reconnecting. A tab in the background closes its live connection and catches up when you return to it.

Problems stay visible instead of stopping the run. A function skipped because of a syntax error is listed in the sidebar with a warning sign; opening it shows the message and highlights the line in the source. A file that cannot be read or decoded is listed with a warning sign too. Opening it shows the error, and so does any of its charts that you have open when the error appears. A file with nothing to chart is greyed out. If a file added while running would have the same name as an existing one, only the first is shown and a collision message explains why. The warnings counter in the sidebar lists everything.

At startup the explorer exits with code 1 when nothing could be parsed and there were errors (a missing file, an unsupported type), when two inputs map to the same name, or when the port cannot be used; with code 2 when Graphviz is missing. A directory with no source files yet only gives a warning, and the explorer waits for files to appear.

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
- Call resolution is static and best-effort (see "Call graphs").

## Development

```bash
uv run pytest          # tests
node --test 'tests/js/*.test.mjs'   # explorer front-end tests (Node 24, no npm packages)
uv run ruff check      # lint
uv run ruff format     # format
```

The architecture is frontend (tree-sitter, Python only for now) → language-neutral CFG engine → IR → backends (JSON, Graphviz, Mermaid). See `AGENTS.md` for the architecture and project rules.
