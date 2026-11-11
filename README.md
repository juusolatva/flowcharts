# python-flowcharts

`pyflowcharts` reads Python source files and draws a **control-flow flowchart for every function**: branches, loops, `try`/`except`/`finally`, `match`, `with`, returns and raises. The start node shows the function's parameters, return nodes show the returned value, and variable assignments can optionally be shown too. Charts are written as SVG/PNG images, DOT, Mermaid, and JSON.

The JSON output (schema version 1) is the stable, machine-readable format. It holds the full graph plus source locations and is meant for other tools, such as a future GUI explorer.

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
```

| Option | Meaning |
|---|---|
| `-o, --output OUTDIR` | Output directory (default `flowcharts`) |
| `-f, --format FORMAT ...` | Any of `json dot svg png mermaid` (default `svg json`) |
| `--variables` | Show assignments without calls (assignments containing a call are always shown) |
| `--no-parameters` | Start node shows `def name(...)` instead of the full signature |
| `--no-returns` | Return nodes show `return` without the value |
| `--function QUALNAME ...` | Only chart these functions; repeatable |
| `--max-label N` | Truncate node labels to N characters (default 60) |

Put the input files **before** options that take several values (`-f`, `--function`).

### Output layout

```
OUTDIR/
├── mymodule.json              # one JSON document per source file (if json selected)
└── mymodule/
    ├── load.svg               # one file per function and format
    ├── Inventory.find.svg
    └── Inventory.size@L25.svg # later duplicates (e.g. property setters) get @L<line>
```

Methods are named `Class.method` and nested functions `outer.inner`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (a file with no functions only produces a warning) |
| 1 | A file could not be read or parsed, an unknown `--function`, or two inputs share a file name |
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

### Known simplifications

- Exceptions are drawn as edges from the `try` node, not from each statement in the body.
- `return`/`raise` inside `try … finally` go straight to the end without passing through the finally body.
- Module-level code, directory recursion and call graphs between functions are not supported yet.

## Development

```bash
uv run pytest          # tests
uv run ruff check      # lint
uv run ruff format     # format
```

The architecture is frontend (Python `ast`) → language-neutral IR → backends (JSON, Graphviz, Mermaid). See `AGENTS.md` for the project rules and `docs/superpowers/specs/` for the design.
