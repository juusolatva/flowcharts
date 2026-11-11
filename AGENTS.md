# AGENTS.md

Instructions for AI coding agents (and humans) working in this repository.

## Project

`python-flowcharts` is a CLI (`pyflowcharts`) that turns each function in a Python source file into a control-flow flowchart. It outputs JSON, DOT, SVG, PNG and Mermaid. The JSON is the stable, machine-readable format, and a future GUI explorer will read it.

- Design spec: `docs/superpowers/specs/2026-11-11-python-flowcharts-design.md`
- MVP implementation plan: `docs/superpowers/plans/2026-11-11-python-flowcharts-mvp.md`

When behaviour is unclear, the spec is the source of truth. If the code and the spec disagree, raise it rather than silently picking one.

## Commands

Use `uv` for everything. Don't call `pip` or bare `python`/`pytest`.

```bash
uv sync                                  # install dependencies (incl. dev group)
uv run pytest                            # run all tests
uv run pytest tests/test_cli.py -v       # run one test file
uv run ruff check                        # lint
uv run ruff format                       # format
uv run pyflowcharts FILE.py -o OUTDIR    # run the CLI
```

SVG/PNG output needs the system Graphviz `dot` binary (`sudo apt install graphviz`). Tests that need it are skipped when it's missing.

## Architecture

```
source file ──► Frontend (per language) ──► IR (Document) ──► Backends
                 frontends/python_ast/       ir.py             serialize.py (json)
                                                               backends/dot.py (dot/svg/png)
                                                               backends/mermaid.py
```

- `src/pyflowcharts/ir.py`: language-neutral dataclasses (`Document`, `FunctionChart`, `Node`, `Edge`, …). This is the contract between frontends and backends.
- `src/pyflowcharts/frontends/`: the `Frontend` protocol and an extension-based registry. `python_ast/` is the only frontend (stdlib `ast`).
- `src/pyflowcharts/backends/`: renderers that depend only on the IR.
- `src/pyflowcharts/cli.py`: argument parsing, file output and exit codes.

## Rules

**Layering**
- Backends and the CLI must not import `ast` or anything from `frontends/python_ast/`. Language-specific logic lives only in its frontend.
- Adding a language means adding a frontend module and registering its extensions. No backend changes should be needed.

**IR and JSON format**
- The IR holds no layout data (no x/y). Layout belongs to Graphviz or the GUI.
- Node IDs follow `{qualname}#start`, `{qualname}#end`, `{qualname}#L{line}C{col}[~suffix]`, and must never contain `:` (DOT treats it as port syntax).
- Output must be deterministic: the same input gives byte-identical JSON, DOT and Mermaid. No sets, hashes or timestamps in the output order.
- Any change to the JSON shape requires bumping `SCHEMA_VERSION` in `ir.py`, updating `from_json`, and noting it in the spec.

**Code style**
- Python ≥ 3.12, full type hints, and `match` statements for AST dispatch.
- Stay within the standard library plus `graphviz`. Ask before adding a runtime dependency.
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

- Exception edges start at the `try` node, not at each statement in the body.
- `return`/`raise` inside `try … finally` go straight to `end` without passing through the finally body. `break`/`continue` *do* pass through it, and that path must stay correct.
- Module-level code, directory recursion and call graphs are out of scope for the MVP.
