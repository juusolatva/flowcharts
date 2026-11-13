"""Python frontend: parse a file with tree-sitter and build one chart per valid function."""

from __future__ import annotations

from pyflowcharts.cfg.builder import StrayLoopTransfer, build_chart
from pyflowcharts.frontends.base import Diagnostic, ParseResult, SourceError
from pyflowcharts.frontends.python.discovery import Found, find_functions, parameters, returns
from pyflowcharts.frontends.python.module import STRAY, UNSUPPORTED, does_work, module_chart
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.frontends.python.statements import convert_body, signature_label
from pyflowcharts.frontends.python.validate import first_error_line, validate
from pyflowcharts.ir import MODULE_QUALNAME, Chart, ChartOptions, Document, FunctionChart

TOO_DEEP = "code is too deeply nested to chart"


class PythonFrontend:
    language = "python"
    extensions: tuple[str, ...] = (".py",)

    def parse(self, source: bytes, path: str, options: ChartOptions) -> ParseResult:
        src = Source.from_bytes(source, path)
        try:
            functions = find_functions(src.tree.root_node)
            validation = validate(src, functions, path)
            warnings = list(validation.skipped.values())
            charts = []
            for func in functions:
                if func.qualname in validation.skipped:
                    continue
                try:
                    charts.append(_chart(func, src, options))
                except StrayLoopTransfer as e:
                    message = f"syntax error in '{func.qualname}'; function skipped"
                    warnings.append(Diagnostic(path, e.loc.line, message, func.qualname))
            module = None
            if options.show_module and validation.outside is None:
                module = _module(src, path, options, warnings)
        except (RecursionError, MemoryError) as e:
            raise SourceError(path, TOO_DEEP) from e
        warnings.sort(key=lambda w: w.line or 0)
        if validation.outside is not None:
            warnings.insert(0, validation.outside)
        document = Document(source=path, language=self.language, functions=charts, module=module)
        return ParseResult(document, tuple(warnings))


def _chart(func: Found, src: Source, options: ChartOptions) -> FunctionChart:
    nodes, edges = build_chart(
        func.qualname,
        signature_label(func.node, src, options),
        src.location(func.node),
        convert_body(func.node, src, options),
        options,
    )
    return FunctionChart(
        qualname=func.qualname,
        name=func.name,
        is_async=func.is_async,
        parameters=parameters(func.node, src),
        returns=returns(func.node, src),
        location=src.location(func.node),
        nodes=nodes,
        edges=edges,
    )


def _module(
    src: Source, path: str, options: ChartOptions, warnings: list[Diagnostic]
) -> Chart | None:
    """The module chart, or ``None`` (appending a warning when it had to be skipped). A
    tree-sitter error only matters when a chart would be drawn; a top-level ``ERROR`` node
    is not a declaration, so it counts as work and is still reported."""
    root = src.tree.root_node
    if not does_work(root):
        return None
    if (line := first_error_line(root)) is not None:
        warnings.append(Diagnostic(path, line, UNSUPPORTED, MODULE_QUALNAME))
        return None
    try:
        return module_chart(root, src, path, options)
    except StrayLoopTransfer as e:
        warnings.append(Diagnostic(path, e.loc.line, STRAY, MODULE_QUALNAME))
        return None
