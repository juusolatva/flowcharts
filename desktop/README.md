# Native desktop explorer (first working slice)

A C++17 / Qt 6 Widgets application for Linux and Windows. The GUI is native: no browser,
WebView, JavaScript, HTTP server or listening port. The existing browser explorer remains available.

The analysis engine is **still Python**. It runs in a persistent subprocess, outside the UI
thread. A separately versioned JSON-lines protocol lets a future C++ engine replace that
process without replacing the GUI. See [the protocol](../docs/desktop-protocol.md).

## Build and run

Requirements:

- CMake >= 3.21 and a C++17 compiler.
- Qt >= 6.4, with Widgets; Qt Test is also required unless `BUILD_TESTING=OFF`.
- `uv` and the repository's existing Python dependencies (`uv sync`).
- Graphviz `dot` on `PATH`, with its JSON output plugin (normal desktop Graphviz packages).

On Debian/Ubuntu, the native build dependencies are available as:

```sh
sudo apt install build-essential cmake qt6-base-dev graphviz
```

From the repository root:

```sh
uv sync
cmake -S desktop -B build/desktop -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build/desktop --parallel
./build/desktop/flowcharts-desktop src/
```

You can also start with no paths and use **File → Open files / Open folder**. Multiple paths
can be supplied on the command line. The development launcher uses `uv run --project` with
this checkout's absolute path and `--no-sync`; run `uv sync` before launching it. Running the
executable from another directory does not change where its engine comes from: `uv` is found
on `PATH`, the worker runs in this checkout, and Python starts in isolated mode (`-I`), so
nothing in the launch directory is imported. Source path arguments are relative to the
caller's directory. A replacement engine given with `--engine` runs as given, in the caller's
directory.

### Windows

Install Qt with a matching compiler (for example, Qt's MSVC 2022 x64 kit and Visual Studio's
Desktop development with C++ workload), plus CMake, `uv` and Graphviz. Put `dot.exe` and the
Qt kit's `bin` directory on `PATH`. Configure in a Developer PowerShell/command prompt:

```powershell
uv sync
cmake -S desktop -B build/desktop -A x64 -DCMAKE_PREFIX_PATH="C:/Qt/6.8.3/msvc2022_64"
cmake --build build/desktop --config Release --parallel
./build/desktop/Release/flowcharts-desktop.exe src/
ctest --test-dir build/desktop -C Release --output-on-failure
```

Adjust the Qt path to your installation. CI builds and tests both Linux and Windows; Windows
is not implied to have been tested locally by a successful Linux build.

The engine command can be replaced without rebuilding the GUI:

```sh
./build/desktop/flowcharts-desktop --engine /path/to/engine source/
```

Use repeated `--engine-argument=value` options for arguments (including values beginning with
`-`). The executable must implement desktop protocol v1; this is the seam for the later C++
analysis engine, not a requirement to rewrite it now.

## Current interactions

- Dockable workspace, source and diagnostics panes.
- Case-insensitive file/function search (`Ctrl+F`).
- Call graph, per-function charts and module charts.
- Native vector nodes, edges, labels and cluster boundaries, laid out by Graphviz.
- Drag empty canvas space to pan, wheel to zoom, or use Fit / `Ctrl+0` and `Ctrl++` / `Ctrl+-`.
- Select a flowchart node to highlight its source lines; click a source line to select the
  smallest covering node in the current chart.
- Double-click a call-graph node to open its chart. Double-click a flowchart node to open its
  callee when its resolved calls have exactly one distinct target.
- Back/forward chart navigation (`Alt+Left` / `Alt+Right` on typical desktop keymaps).
- Automatic file-change polling and settled re-parsing, including new/deleted directory inputs.
- Retain pan/zoom and surviving node selection when the same chart is redrawn after a save.
- Visible parse, read, layout and engine-startup errors. **File → Restart analysis engine**
  recovers from a stopped worker.

## Tests

```sh
uv run pytest tests/test_desktop_worker.py
ctest --test-dir build/desktop --output-on-failure
```

CTest runs headlessly using Qt's `offscreen` platform plugin. It includes protocol framing,
semantic navigation/source mapping, native drawing, view-state retention, subprocess failures,
and a real GUI → Python worker → Graphviz integration test. The integration test skips if
`uv` is unavailable; it otherwise needs the existing Python environment and Graphviz.

For clangd, the repository's `.clangd` points to `build/desktop`. Configure with
`CMAKE_EXPORT_COMPILE_COMMANDS=ON` before requesting C++ diagnostics. Optional formatting:

```sh
clang-format --dry-run --Werror desktop/src/*.cpp desktop/src/*.h desktop/tests/*.cpp
```

### Native coverage (GCC/Linux)

CI runs the same native suites with GCC instrumentation and imports both line and branch
coverage into SonarQube, alongside Python and JavaScript coverage. To reproduce locally:

```sh
uv sync --locked --group native-coverage
cmake -S desktop -B build/coverage -DCMAKE_BUILD_TYPE=Debug -DFLOWCHARTS_COVERAGE=ON
cmake --build build/coverage --parallel
ctest --test-dir build/coverage --output-on-failure
uv run --no-sync gcovr --root . --filter 'desktop/src/' \
  --exclude-unreachable-branches --exclude-throw-branches \
  --sonarqube build/native-coverage.xml --txt build/native-coverage.txt build/coverage
```

Test code is classified separately from production code in SonarQube; native application code
is not excluded from coverage. Windows test reports are also saved as CTest text artifacts.

## Deliberately not finished yet

This is a development build, **not yet a self-contained installer**. It currently needs `uv`,
the checkout's Python environment, Graphviz and Qt libraries. Packaging must collect those
runtimes/plugins and their license notices (or, later, the C++ analysis executable). Simply
copying this development executable is not a portable distribution.

The initial slice also does not yet have source syntax highlighting/editing, the browser's
full Calls/Called-by controls, cross-function source-line navigation, chart-option controls,
export dialogs, saved sessions or persisted window layout. The browser is not being removed
until the replacement is ready. Python analysis/CFG behavior and IR schema version 3 are unchanged.

The native renderer implements the Graphviz drawing operations used by the existing DOT
backends, not an arbitrary SVG/xdot viewer; unsupported drawing operations are reported rather
than silently omitted.

## Source layout

- `commandline.*`: launcher options and replaceable engine command.
- `engineclient.*`, `protocol.*`: asynchronous, bounded JSON-lines process transport.
- `workspace.*`: semantic document access, stable chart identity and source/call navigation.
- `drawing.*`, `graphlayout.*`: Graphviz geometry decoding, independent of widgets.
- `graphview.*`: native scene items and canvas interaction.
- `sourceview.*`, `chartbrowser.*`: source gutter/highlighting and filtered chart tree.
- `mainwindow.*`, `mainwindow_data.cpp`: application shell and workspace/view coordination.
- `../src/pyflowcharts/desktop/`: temporary Python engine adapter, not analysis-engine changes.

Qt API references: [Graphics View](https://doc.qt.io/qt-6/graphicsview.html),
[QProcess](https://doc.qt.io/qt-6/qprocess.html), and
[Qt Test](https://doc.qt.io/qt-6/qttest-index.html). These were checked against the Qt documentation
through Context7 library `/websites/doc_qt_io_qt-6` when implementing the first slice.
