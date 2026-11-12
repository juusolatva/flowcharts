import textwrap

from pyflowcharts.frontends.python.discovery import find_functions, parameters, returns
from pyflowcharts.frontends.python.source import Source
from pyflowcharts.ir import Parameter, ParamKind


def found(text):
    s = Source.from_bytes(textwrap.dedent(text).encode(), "t.py")
    return s, find_functions(s.tree.root_node)


def test_qualnames_duplicates_and_async():
    _, fs = found("""
        def top(): pass
        class A:
            def m(self):
                def inner(): pass
            @property
            def x(self): return 1
            @x.setter
            def x(self, v): pass
        async def co(): pass
        if True:
            def under_if(): pass
    """)
    expected = ["top", "A.m", "A.m.inner", "A.x", "A.x@L9", "co", "under_if"]
    assert [f.qualname for f in fs] == expected
    assert fs[-2].is_async and fs[2].enclosing is fs[1] and fs[1].enclosing is None
    assert fs[1].name == "m"


def test_functions_inside_error_regions():
    _, fs = found("class A(:\n    def m(self):\n        pass\n\ndef g():\n    pass\n")
    assert [f.qualname for f in fs] == ["A.m", "g"]
    _, fs = found("def f()\n    pass\n\ndef g():\n    pass\n")
    assert [f.qualname for f in fs] == ["g"]  # unrecoverable header: not found


def test_parameters_and_returns():
    s, (f,) = found('def f(a: int, /, b=2, *args, c, d: str = "a  b", **kw) -> list[int]: ...')
    P, K = Parameter, ParamKind
    assert parameters(f.node, s) == [
        P("a", "int", None, K.POSITIONAL_ONLY),
        P("b", None, "2", K.POSITIONAL_OR_KEYWORD),
        P("args", None, None, K.VAR_POSITIONAL),
        P("c", None, None, K.KEYWORD_ONLY),
        P("d", "str", '"a  b"', K.KEYWORD_ONLY),
        P("kw", None, None, K.VAR_KEYWORD),
    ]
    assert returns(f.node, s) == "list[int]"
    s, (g,) = found("def g(*, k, **kw: int): pass")
    assert [p.kind for p in parameters(g.node, s)] == [K.KEYWORD_ONLY, K.VAR_KEYWORD]
    assert parameters(g.node, s)[1].annotation == "int"
    assert returns(g.node, s) is None
