# AGENTS.md

Instructions for AI coding agents (and humans) working in this repository.

## Project

`flowcharts` is a CLI (`pyflowcharts`) that turns each function in Python source files or directories into a control-flow flowchart, plus a module-level chart for files whose top level does work, and draws one call graph per run. It outputs JSON, DOT, SVG, PNG and Mermaid, and `pyflowcharts explore` serves the same charts in a local web app that updates as files change. The JSON is the stable, machine-readable format; the explorer's front end reads it.

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
uv run pyflowcharts explore PATH         # run the explorer (needs Graphviz)
node --test 'tests/js/*.test.mjs'        # JavaScript tests (Node 24; quote the glob)
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
- `src/pyflowcharts/frontends/`: the `Frontend` protocol (`parse(source, path, options, key=None) -> ParseResult`, a document plus warnings and `source_text`, the decoded text the frontend charted, so nothing else decodes bytes; `key` is the output key the module name comes from) and an extension-based registry. `python/` is the only frontend: it parses with tree-sitter, validates each function with `ast.parse`, and converts statements into the model. Functions with syntax errors are skipped with a warning. `python/module.py` decides whether a file's top level does work and builds its module chart. `python/calls.py` finds each statement's calls and their candidate targets (scopes and imports).
- `src/pyflowcharts/calls.py`: the language-neutral linker; sets each call's `target` against all documents of the run.
- `src/pyflowcharts/backends/`: renderers that depend only on the IR. `callgraph.py` draws the run's call graph.
- `src/pyflowcharts/inputs.py`: expands path arguments (directory walk, `--exclude`), deduplicates them, assigns each file its output key and checks for output collisions.
- `src/pyflowcharts/output.py`: writes each document under its output key in the selected formats, and the call graph as `OUTDIR/callgraph.<ext>`.
- `src/pyflowcharts/pipeline.py`: `parse_all` parses and links the inputs of a run; shared by the CLI and the explorer. It prints nothing.
- `src/pyflowcharts/cli_options.py`: the chart options, their validators and the exit codes, shared by the CLI and the explorer.
- `src/pyflowcharts/cli.py`: argument parsing, `--function` selection, warnings and exit codes; `explore` hands over to the explorer.
- `src/pyflowcharts/explorer/`: `pyflowcharts explore`, a local web app.
  - `main.py`: arguments and startup.
  - `workspace.py`: the watcher thread in `server.py` calls its `refresh()` once a second; when the files change (fingerprint of paths, keys and `stat()`, plus an open-probe for files that failed to read) it waits for writes to settle, re-parses the whole run and publishes an immutable, numbered snapshot.
  - `server.py`: 127.0.0.1 only. Host check, token cookie, security headers, routing, the event stream and the watcher thread.
  - `api.py`: pure request-to-response logic for `/api/*` (generation checks, SVG cache).
  - `render.py`: DOT to SVG with `dot`, with a timeout.
  - `assets.py`: the fixed table of static files.
  - `static/lib/`: pure ES modules that Node tests import: routing, search, file tree, call index, source map, SVG ids, drag, keys, view state, generation tracking and the API client (`client.mjs`, with `fetch` injected).
  - `static/views/`: the thin DOM glue.
  - No npm, no build step.

## Rules

**Layering**
- Backends, the linker and the CLI must not import `ast`, tree-sitter or anything from `frontends/python/`. Language-specific logic lives only in its frontend.
- `explorer/`, `pipeline.py` and `cli_options.py` follow the same rule as the CLI: no `ast`, tree-sitter or `frontends/python/`. The explorer serves on `127.0.0.1` only and never lets a request path reach the file system.
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
- Front-end logic goes in `explorer/static/lib/` as pure modules with `node --test` tests in `tests/js/`; `views/` stays thin DOM glue without logic worth testing.
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` and `node --test 'tests/js/*.test.mjs'` must all pass before committing.

**Git**
- Never commit directly to `main`. Work on a feature branch (`feat/…`, `fix/…`).
- Make small commits, one logical change each, with Conventional Commit messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
- Don't commit generated output (`flowcharts/`, `*.svg`/`*.png` outside `docs/`).

## Known simplifications (not bugs)

- Handlers are assumed to catch whatever reaches them: the uncaught path out of a `try` with handlers is not drawn, and the `try` node itself has no exception edges.
- Only syntax errors are detected (via `ast.parse`), plus `break`/`continue` outside a loop. Other compiler-only errors (duplicate parameters, `await` outside `async`, …) are charted as written.
- Class bodies are charted only through their methods.
- Call resolution is static and best-effort: shadowing by local assignment or `for`/`with`/`except` targets, inheritance, decorators that replace functions, `getattr` and other dynamic calls, star imports, `global`/`nonlocal` rebinding, and calls through instance attributes other than `self.m`/`cls.m` are not handled.

## Potential future fixes

Found in a code review and not yet done. Each is small; pick one up as its own change.

- **Module size.** `frontends/python/statements.py` (~385 lines) and `frontends/python/calls.py` (~360) are past the ~300-line guideline. Candidates: move the match-pattern helpers (`_irrefutable`, `_capture`) and the docstring/type-alias helpers out of `statements.py`; move the import tables (`_Scope`, `_Module`, `_Name`, `_Class`, `_through`) out of `calls.py`.
- **`if`/`elif` duplication.** `_if` and `_if_chain` in `statements.py` build the same branch shape twice, and `stmt()` matches `"elif_clause"`, which never reaches it (an `elif_clause` only appears inside an `if_statement`, never in a block).
- **Unguarded `next()`.** The `with_statement` and `finally_clause` cases in `statements.py` call `next(...)` without a default. If tree-sitter error recovery in module code ever yields a `with` without a `with_clause` or a `finally` without a block, this raises `StopIteration`. Start with a test that tries to reproduce it.
- **Case-only clashes between files.** `inputs.collision_error` compares output keys exactly, so `A.py` and `a.py` in one directory are not reported, though their outputs overwrite each other on case-insensitive file systems. (Function names in one file already give a warning, from `output.py`.)
- **Explorer pan/zoom on live reload.** A re-parse redraws the open chart with a fresh `viewBox`, so the user's pan and zoom are lost on every save. Keep the view when the redrawn chart is the one already open, with the "same chart?" decision in `static/lib/` and a Node test.
- **Type checking in CI.** `[tool.pyright]` is configured in `pyproject.toml`, but no CI job runs it.
- **Files spelled two ways.** Module names from paths are NFC-normalized (so a decomposed `café.py` on macOS matches `import café`). On Linux, `café.py` precomposed and decomposed can sit side by side; both get the module name `café`, and `calls.link` drops both as ambiguous although only the precomposed one is importable. A fix needs a tie-break by exact spelling that keeps the linker language-neutral.
- **Imports that always run.** `_always_runs` in `frontends/python/calls.py` accepts imports in a module or function body, `with` bodies and `finally` blocks; an import under `if True:` still counts as conditional.
- **Trivial wrapper.** `explorer/api.py` `_docs(snapshot)` only returns `list(snapshot.documents)`.
