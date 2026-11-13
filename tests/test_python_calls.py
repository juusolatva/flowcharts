import textwrap
from pathlib import PurePosixPath

import pytest

from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.frontends.python.calls import ModuleInfo, module_info
from pyflowcharts.ir import ChartOptions


@pytest.mark.parametrize(
    "key, name, package",
    [
        ("pkg/io/load", "pkg.io.load", ("pkg", "io")),
        ("pkg/io/__init__", "pkg.io", ("pkg", "io")),
        ("pkg/__init__", "pkg", ("pkg",)),
        ("util", "util", ()),
        ("__init__", "", ()),
    ],
)
def test_module_info(key, name, package):
    assert module_info(PurePosixPath(key)) == ModuleInfo(name, package)


def test_document_module_name_from_key_and_default():
    fe = PythonFrontend()
    keyed = fe.parse(b"", "src/pkg/a.py", ChartOptions(), PurePosixPath("pkg/a"))
    assert keyed.document.module_name == "pkg.a"
    assert fe.parse(b"", "src/pkg/a.py", ChartOptions()).document.module_name == "a"


def doc_of(src, key="t", **opts):
    return (
        PythonFrontend()
        .parse(textwrap.dedent(src).encode(), "t.py", ChartOptions(**opts), PurePosixPath(key))
        .document
    )


def owned(chart) -> list[tuple[str, str]]:
    label = {n.id: n.label for n in chart.nodes}
    return [(label[c.node], c.text) for c in chart.calls]


def texts(chart) -> list[str]:
    return [t for _, t in owned(chart)]


def fn(doc, qualname):
    return next(c for c in doc.functions if c.qualname == qualname)


def test_statement_kinds_own_their_calls():
    d = doc_of("""
        def f(xs):
            g(1)
            y = load()
            if ok(y):
                pass
            elif other():
                pass
            for r in rows(xs):
                pass
            while more():
                pass
            with open_(p) as fh:
                pass
            try:
                pass
            except make_exc() as e:
                pass
            match subj():
                case 1 if guard():
                    pass
            return done()
        """)
    assert owned(fn(d, "f")) == [
        ("g(1)", "g"),
        ("y = load()", "load"),
        ("if ok(y)", "ok"),
        ("if other()", "other"),
        ("for r in rows(xs)", "rows"),
        ("while more()", "more"),
        ("with open_(p) as fh", "open_"),
        ("except make_exc() as e", "make_exc"),
        ("match subj()", "subj"),
        ("match subj()", "guard"),
        ("return done()", "done"),
    ]


def test_raise_and_nested_calls_preorder():
    d = doc_of("def f():\n    raise Err(msg(a().b()))\n")
    assert texts(fn(d, "f")) == ["Err", "msg", "a().b", "a"]


def test_nested_def_signature_on_parent_body_in_child():
    d = doc_of("""
        def outer():
            @deco(arg())
            @bare
            def inner(x=default(), y: ann() = 1) -> ret():
                body()
        """)
    assert texts(fn(d, "outer")) == ["deco", "arg", "default", "ann", "ret"]
    assert texts(fn(d, "outer.inner")) == ["body"]


def test_class_subtree_on_class_node_method_bodies_in_methods():
    d = doc_of("""
        def outer():
            @cdeco()
            class C(Base(), metaclass=meta()):
                x = a()
                def m(self, y=b()):
                    c()
        """)
    assert texts(fn(d, "outer")) == ["cdeco", "Base", "meta", "a", "b"]
    assert texts(fn(d, "outer.C.m")) == ["c"]


def test_top_level_definitions_own_calls_only_with_a_module_chart():
    src = "@deco()\ndef f(x=d()): pass\nmain()\n"
    assert texts(doc_of(src).module) == ["deco", "d", "main"]
    assert doc_of("@deco()\ndef f(x=d()): pass\n").module is None


def test_lambdas_and_comprehensions_belong_to_the_statement():
    d = doc_of("def f(xs):\n    out = [h(x) for x in xs if keep(x)]\n    k = lambda: z()\n")
    assert owned(fn(d, "f")) == [
        ("out = [h(x) for x in xs if keep(x)]", "h"),
        ("out = [h(x) for x in xs if keep(x)]", "keep"),
        ("k = lambda: z()", "z"),
    ]


def test_calls_ignore_label_options():
    src = "def f():\n    def inner(a=d()): pass\n    return g()\n"
    d = doc_of(src, show_returns=False, show_parameters=False)
    assert owned(fn(d, "f")) == [("def inner(...)", "d"), ("return", "g")]


def test_hidden_assignment_records_calls_only_when_shown():
    src = "def f():\n    x[g()] = 1\n    h()\n"
    assert texts(fn(doc_of(src), "f")) == ["h"]
    assert texts(fn(doc_of(src, show_variables=True), "f")) == ["g", "h"]


def test_fstring_calls_are_recorded():  # Review Focus 1
    d = doc_of('def f(x):\n    print(f"{fmt(x)}")\n')
    assert texts(fn(d, "f")) == ["print", "fmt"]


def test_await_and_async_with_calls():  # Review Focus 2
    d = doc_of("async def f():\n    await g()\n    async with open_conn():\n        pass\n")
    assert texts(fn(d, "f")) == ["g", "open_conn"]


def test_same_function_nested_gives_two_calls():  # Review Focus 3
    d = doc_of("def f(x):\n    g(g(x))\n")
    assert owned(fn(d, "f")) == [("g(g(x))", "g"), ("g(g(x))", "g")]
