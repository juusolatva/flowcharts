"""Python frontend: parse a file with tree-sitter and build one chart per valid function."""

from __future__ import annotations

from pyflowcharts.cfg.builder import StrayLoopTransfer, build_chart
from pyflowcharts.frontends.base import Diagnostic, ParseResult, SourceError
from pyflowcharts.frontends.python.discovery import Found, find_functions, parameters, returns
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.frontends.python.statements import convert_body, signature_label
from pyflowcharts.frontends.python.validate import validate
from pyflowcharts.ir import ChartOptions, Document, FunctionChart

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
        except (RecursionError, MemoryError) as e:
            raise SourceError(path, TOO_DEEP) from e
        warnings.sort(key=lambda w: w.line or 0)
        if validation.outside is not None:
            warnings.insert(0, validation.outside)
        document = Document(source=path, language=self.language, functions=charts)
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
