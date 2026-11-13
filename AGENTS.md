# AGENTS.md

Instructions for AI coding agents (and humans) working in this repository.

## Project

`flowcharts` is a CLI (`pyflowcharts`) that turns each function in Python source files or directories into a control-flow flowchart, plus a module-level chart for files whose top level does work, and draws one call graph per run. It outputs JSON, DOT, SVG, PNG and Mermaid. The JSON is the stable, machine-readable format, and a future GUI explorer will read it.

When behaviour is unclear, the README and the tests describe the intended behaviour. If the code and the documentation disagree, raise it rather than silently picking one.

## Commands

Use `uv` for everything. Don't call `pip` or bare `python`/`pytest`.

```bash
uv sync                                  # install dependencies (incl. dev group)
uv run pytest                            # run all tests
uv run pytest tests/test_cli.py -v       # run one test file
uv run ruff check                        # lint
uv run ruff format                       # format
uv run pyflowcharts PATH -o OUTDIR       # run the CLI (files or directories)
```

SVG/PNG output needs the system Graphviz `dot` binary (`sudo apt install graphviz`). Tests that need it are skipped when it's missing.

## Architecture

```
source file ──► Frontend (per language) ──► cfg (shared engine) ──► IR (Document) ──► Backends
                 frontends/python/           cfg/model.py            ir.py             serialize.py (json)
                 (tree-sitter adapter)       cfg/builder.py                            backends/dot.py (dot/svg/png)
                                             cfg/finally_.py                           backends/mermaid.py
                                                                                       backends/callgraph.py
```

Between parsing and the backends, `calls.py` links the calls of every document in the run.

- `src/pyflowcharts/ir.py`: language-neutral dataclasses (`Document`, `Chart`, `FunctionChart`, `Node`, `Edge`, `Call`, `CallRef`, …). This is the contract between frontends and backends.
- `src/pyflowcharts/cfg/`: the language-neutral statement model (`Step`, `Branch`, `Loop`, `Try`, …) and the chart builder (frontier walk, node IDs, reveal rule, `finally` copies). Frontends produce the model; the builder produces nodes and edges.
- `src/pyflowcharts/frontends/`: the `Frontend` protocol (`parse(source, path, options, key=None) -> ParseResult`, a document plus warnings; `key` is the output key the module name comes from) and an extension-based registry. `python/` is the only frontend: it parses with tree-sitter, validates each function with `ast.parse`, and converts statements into the model. Functions with syntax errors are skipped with a warning. `python/module.py` decides whether a file's top level does work and builds its module chart. `python/calls.py` finds each statement's calls and their candidate targets (scopes and imports).
- `src/pyflowcharts/calls.py`: the language-neutral linker; sets each call's `target` against all documents of the run.
- `src/pyflowcharts/backends/`: renderers that depend only on the IR. `callgraph.py` draws the run's call graph.
- `src/pyflowcharts/inputs.py`: expands path arguments (directory walk, `--exclude`), deduplicates them, assigns each file its output key and checks for output collisions.
- `src/pyflowcharts/output.py`: writes each document under its output key in the selected formats, and the call graph as `OUTDIR/callgraph.<ext>`.
- `src/pyflowcharts/cli.py`: argument parsing, linking, `--function` selection, warnings and exit codes.

## Rules

**Layering**
- Backends, the linker and the CLI must not import `ast`, tree-sitter or anything from `frontends/python/`. Language-specific logic lives only in its frontend.
- `cfg/` must not import tree-sitter or anything from `frontends/`. It knows nothing about Python.
- Adding a language means adding a frontend module that produces `cfg.model` statements and registering its extensions. No backend or `cfg/` changes should be needed.

**IR and JSON format**
- The IR holds no layout data (no x/y). Layout belongs to Graphviz or the GUI.
- Node IDs follow `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}[~suffix]` (duplicated finally bodies add `~break@L{line}C{col}`, `~continue@…`, `~return@…` or `~exception@…` naming the owning `try`), must be unique within a chart, and must never contain `:` (DOT treats it as port syntax). The module-level chart uses the qualname `<module>` (`MODULE_QUALNAME`), which no function qualname can equal.
- Output must be deterministic: the same input gives byte-identical JSON, DOT and Mermaid. No sets, hashes or timestamps in the output order.
- Any change to the JSON shape requires bumping `SCHEMA_VERSION` in `ir.py`, updating `from_json`, and noting it in the README.

**Code style**
- Python ≥ 3.12, full type hints, and `match` statements for AST dispatch.
- Stay within the standard library plus `graphviz`, `tree-sitter` and `tree-sitter-python`. Ask before adding a runtime dependency. Pin new dependency versions released at least two weeks earlier; `tree-sitter` 0.26.0 is excluded (it corrupts node positions and segfaults). Dependabot proposes dependency and action updates weekly with the same two-week cooldown (`.github/dependabot.yml`); CI must pass before one is merged.
- Keep modules focused. If a file grows past roughly 300 lines, propose a split.

**Testing**
- Test-driven: write the failing test first, then the implementation.
- CFG tests assert on `flow(chart)` (a set of `(source_label, target_label, edge_label)` triples, from `tests/conftest.py`) rather than on node IDs or ordering.
- Every new statement type, CLI flag or error path gets a test. Bug fixes start with a test that reproduces the bug.
- `uv run pytest` and `uv run ruff check` must both pass before committing.

**Git**
- Never commit directly to `main`. Work on a feature branch (`feat/…`, `fix/…`).
- Make small commits, one logical change each, with Conventional Commit messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
- Don't commit generated output (`flowcharts/`, `*.svg`/`*.png` outside `docs/`).

## Known simplifications (not bugs)

- Handlers are assumed to catch whatever reaches them: the uncaught path out of a `try` with handlers is not drawn, and the `try` node itself has no exception edges.
- Only syntax errors are detected (via `ast.parse`), plus `break`/`continue` outside a loop. Other compiler-only errors (duplicate parameters, `await` outside `async`, …) are charted as written.
- Class bodies are charted only through their methods.
- Call resolution is static and best-effort: shadowing by local assignment or `for`/`with`/`except` targets, inheritance, decorators that replace functions, `getattr` and other dynamic calls, star imports, `global`/`nonlocal` rebinding, and calls through instance attributes other than `self.m`/`cls.m` are not handled.
