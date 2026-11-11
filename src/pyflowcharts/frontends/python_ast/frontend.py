"""Python frontend: parse a file, discover its functions and build one chart per function."""

from __future__ import annotations

import ast
import warnings

from pyflowcharts.frontends.base import SourceError
from pyflowcharts.frontends.python_ast.cfg import (
    CfgBuilder,
    FunctionNode,
    location_of,
    start_label_for,
)
from pyflowcharts.frontends.python_ast.source import SourceText
from pyflowcharts.ir import ChartOptions, Document, FunctionChart, Parameter, ParamKind


class PythonFrontend:
    language = "python"
    extensions: tuple[str, ...] = (".py",)

    def parse(self, source: bytes, path: str, options: ChartOptions) -> Document:
        tree = _parse(source, path)
        collector = _Collector(options, SourceText(source))
        try:
            collector.walk(tree.body, prefix="")
        except (RecursionError, MemoryError) as e:  # e.g. ast.unparse on huge expressions
            raise SourceError(path, "code is too deeply nested to chart") from e
        return Document(source=path, language=self.language, functions=collector.charts)


def _parse(source: bytes, path: str) -> ast.Module:
    try:
        tree = ast.parse(source, filename=path)
        # ast.parse accepts some programs only the compiler rejects (e.g. `break` outside a
        # loop). Compile purely to validate; the code object is discarded, never executed.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            compile(tree, path, "exec", dont_inherit=True)
    except SyntaxError as e:
        raise SourceError(path, e.msg, e.lineno) from e
    except ValueError as e:
        raise SourceError(path, str(e)) from e
    except (RecursionError, MemoryError) as e:
        raise SourceError(path, "code is too deeply nested to parse") from e
    return tree


class _Collector:
    """Walks the module in source order, emitting a chart for every function definition."""

    def __init__(self, options: ChartOptions, source: SourceText) -> None:
        self.options = options
        self.source = source
        self.charts: list[FunctionChart] = []
        self._seen: set[str] = set()

    def walk(self, stmts: list[ast.stmt], prefix: str) -> None:
        for stmt in stmts:
            match stmt:
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    qualname = self._unique(prefix + stmt.name, stmt.lineno)
                    self.charts.append(self._chart(stmt, qualname))
                    self.walk(stmt.body, qualname + ".")
                case ast.ClassDef():
                    self.walk(stmt.body, prefix + stmt.name + ".")
                case _:
                    for child in ast.iter_child_nodes(stmt):
                        if isinstance(child, ast.stmt):
                            self.walk([child], prefix)
                        elif isinstance(child, ast.ExceptHandler | ast.match_case):
                            self.walk(child.body, prefix)

    def _unique(self, qualname: str, lineno: int) -> str:
        if qualname in self._seen:
            qualname = f"{qualname}@L{lineno}"
        self._seen.add(qualname)
        return qualname

    def _chart(self, func: FunctionNode, qualname: str) -> FunctionChart:
        nodes, edges = CfgBuilder(qualname, self.options, self.source).build(
            func, start_label_for(func, self.options)
        )
        return FunctionChart(
            qualname=qualname,
            name=func.name,
            is_async=isinstance(func, ast.AsyncFunctionDef),
            parameters=_parameters(func.args),
            returns=ast.unparse(func.returns) if func.returns is not None else None,
            location=location_of(func),
            nodes=nodes,
            edges=edges,
        )


def _parameters(args: ast.arguments) -> list[Parameter]:
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += args.defaults
    params = [
        _parameter(
            arg,
            default,
            ParamKind.POSITIONAL_ONLY
            if i < len(args.posonlyargs)
            else ParamKind.POSITIONAL_OR_KEYWORD,
        )
        for i, (arg, default) in enumerate(zip(positional, defaults, strict=True))
    ]
    if args.vararg is not None:
        params.append(_parameter(args.vararg, None, ParamKind.VAR_POSITIONAL))
    params += [
        _parameter(arg, default, ParamKind.KEYWORD_ONLY)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    ]
    if args.kwarg is not None:
        params.append(_parameter(args.kwarg, None, ParamKind.VAR_KEYWORD))
    return params


def _parameter(arg: ast.arg, default: ast.expr | None, kind: ParamKind) -> Parameter:
    return Parameter(
        name=arg.arg,
        annotation=ast.unparse(arg.annotation) if arg.annotation is not None else None,
        default=ast.unparse(default) if default is not None else None,
        kind=kind,
    )
