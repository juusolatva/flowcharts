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
        ("cafe\u0301/m", "caf\u00e9.m", ("caf\u00e9",)),  # normalized like import names
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


def cands(src, qualname, text, key="pkg/mod"):
    d = doc_of(src, key=key)
    chart = d.module if qualname == "<module>" else fn(d, qualname)
    call = next(c for c in chart.calls if c.text == text)
    return [(r.module, r.qualname) for r in call.candidates]


TRY_IMPORTS = """\
try:
    from a import g
except ImportError:
    from b import g
    from a import g
def f():
    g()
"""


@pytest.mark.parametrize(
    "src, qualname, text, expected",
    [
        # bare names: innermost scope first; the owning chart's own scope first
        ("def h(): pass\ndef f():\n    def h(): pass\n    h()\n", "f", "h", [("pkg.mod", "f.h")]),
        (
            "def f():\n    def g():\n        h()\n    def h(): pass\n",
            "f.g",
            "h",
            [("pkg.mod", "f.h")],
        ),
        ("def f():\n    g()\ndef g(): pass\n", "f", "g", [("pkg.mod", "g")]),  # Review Focus 4
        # class scope invisible
        ("class C:\n    def h(self): pass\n    def m(self):\n        h()\n", "C.m", "h", []),
        ("class C: pass\ndef f():\n    C()\n", "f", "C", [("pkg.mod", "C.__init__")]),
        ("from a.b import g\ndef f():\n    g()\n", "f", "g", [("a.b", "g"), ("a.b", "g.__init__")]),
        ("from a import g as k\ndef f():\n    k()\n", "f", "k", [("a", "g"), ("a", "g.__init__")]),
        ("import os as g\ndef f():\n    g()\n", "f", "g", []),
        ("def f():\n    print(len(x))\n", "f", "print", []),
        # local import shadows module-level def and module-level import
        (
            "def foo(): pass\ndef bar():\n    from other import foo\n    foo()\n",
            "bar",
            "foo",
            [("other", "foo"), ("other", "foo.__init__")],
        ),
        (
            "from first import foo\ndef bar():\n    from other import foo\n    foo()\n",
            "bar",
            "foo",
            [("other", "foo"), ("other", "foo.__init__")],
        ),
        # try/except bindings both count, deduplicated
        (TRY_IMPORTS, "f", "g", [("a", "g"), ("a", "g.__init__"), ("b", "g"), ("b", "g.__init__")]),
        # self / cls, including a class nested in a function
        ("class C:\n    def m(self):\n        self.o()\n", "C.m", "self.o", [("pkg.mod", "C.o")]),
        (
            "class C:\n    @classmethod\n    def m(cls):\n        cls.o()\n",
            "C.m",
            "cls.o",
            [("pkg.mod", "C.o")],
        ),
        (
            "def outer():\n    class C:\n        def m(self):\n            self.o()\n",
            "outer.C.m",
            "self.o",
            [("pkg.mod", "outer.C.o")],
        ),
        ("class C:\n    def m(self):\n        self.x.o()\n", "C.m", "self.x.o", []),
        # a redefined class: self.m is the method of the class the call is in
        (
            "class C:\n    def m(self): pass\nclass C:\n    def m(self): pass\n    def n(self):\n        self.m()\n",
            "C.n",
            "self.m",
            [("pkg.mod", "C.m@L4")],
        ),
        # Class.method: local, enclosing-function, imported
        ("class C:\n    def s(): pass\ndef f():\n    C.s()\n", "f", "C.s", [("pkg.mod", "C.s")]),
        (
            "def outer():\n    class C:\n        def s(): pass\n    C.s()\n",
            "outer",
            "C.s",
            [("pkg.mod", "outer.C.s")],
        ),
        ("from m import C\ndef f():\n    C.s()\n", "f", "C.s", [("m.C", "s"), ("m", "C.s")]),
        # module imports
        ("import x.y\ndef f():\n    x.y.g()\n", "f", "x.y.g", [("x.y", "g")]),
        ("import x.y\ndef f():\n    x.g()\n", "f", "x.g", [("x", "g")]),
        # submodule imports under one name: the longest module comes first
        ("import a.b\nimport a.c\ndef f():\n    a.c.f()\n", "f", "a.c.f", [("a.c", "f")]),
        ("import a.c\nimport a.b\ndef f():\n    a.c.f()\n", "f", "a.c.f", [("a.c", "f")]),
        ("import a.b\nimport a.c\ndef f():\n    a.g()\n", "f", "a.g", [("a", "g")]),
        # unrelated imports bound to one name keep source order (the first one is preferred)
        (
            "try:\n    import fast as impl\nexcept ImportError:\n    import pkg.slow as impl\ndef f():\n    impl.run()\n",
            "f",
            "impl.run",
            [("fast", "run"), ("pkg.slow", "run")],
        ),
        # an import that may not run (in a try or if) counts on its own; one that always runs
        # makes its modules certain, so shorter fallbacks through them are dropped
        ("import a.b\nimport a.c\ndef f():\n    a.c()\n", "f", "a.c", []),
        ("def f():\n    import a.b\n    import a.c\n    a.c()\n", "f", "a.c", []),
        (
            "try:\n    import a.b\nexcept ImportError:\n    import a.c\ndef f():\n    a.c.f()\n",
            "f",
            "a.c.f",
            [("a.c", "f"), ("a", "c.f")],
        ),
        (
            "import a.b\nif x:\n    import a.b.c\ndef f():\n    a.b.c()\n",
            "f",
            "a.b.c",
            [("a.b", "c")],
        ),
        (
            "try:\n    import a.b\nexcept ImportError:\n    import a.b.c\ndef f():\n    a.b.c()\n",
            "f",
            "a.b.c",
            [("a.b", "c")],
        ),
        (
            "import a.b.c\nimport a.b\ndef f():\n    a.b.c.d()\n",
            "f",
            "a.b.c.d",
            [("a.b.c", "d")],
        ),
        ("import x.y as z\ndef f():\n    z.C.m()\n", "f", "z.C.m", [("x.y", "C.m")]),
        ("import x.y as z\ndef f():\n    x.g()\n", "f", "x.g", []),
        ("from p import x as a\ndef f():\n    a.g()\n", "f", "a.g", [("p.x", "g"), ("p", "x.g")]),
        (
            "from __future__ import annotations\nfrom m import *\ndef f():\n    annotations()\n",
            "f",
            "annotations",
            [],
        ),
        ("def f():\n    g()().h()\n", "f", "g()().h", []),
        ("import x.y\ndef f():\n    x.y()\n", "f", "x.y", []),  # proper prefixes only
        (
            "class C:\n    def m(self):\n        def inner():\n            self.o()\n",
            "C.m.inner",
            "self.o",
            [],
        ),
        # function-local import is scoped to that function
        ("def a():\n    from m import g\ndef b():\n    g()\n", "b", "g", []),
        # the owning node decides the scope chain: a default runs in outer
        (
            "def outer():\n    def helper(): pass\n    def inner(x=helper()): pass\n",
            "outer",
            "helper",
            [("pkg.mod", "outer.helper")],
        ),
        # a skipped (syntax error) nested function still gives its candidate, no outer fallback
        (
            "def helper(): pass\ndef f():\n    def helper(:\n        pass\n    helper()\n",
            "f",
            "helper",
            [("pkg.mod", "f.helper")],
        ),
        # parameters bind their names in the function's scope (no false edge)
        ("def callback(): pass\ndef run(callback):\n    callback()\n", "run", "callback", []),
        ("class C: pass\ndef run(C):\n    C.s()\n", "run", "C.s", []),
        ("def g(): pass\ndef run(g):\n    def inner():\n        g()\n", "run.inner", "g", []),
        # a definition and an import in one scope: definition first, then imports
        (
            "from m import g\ndef g(): pass\ndef f():\n    g()\n",
            "f",
            "g",
            [("pkg.mod", "g"), ("m", "g"), ("m", "g.__init__")],
        ),
    ],
)
def test_resolution(src, qualname, text, expected):
    assert cands(src, qualname, text) == expected


@pytest.mark.parametrize(
    "key, src, expected",
    [
        ("pkg/io/load", "from . import x\nx.f()\n", [("pkg.io.x", "f"), ("pkg.io", "x.f")]),
        (
            "pkg/io/load",
            "from .util import g\ng()\n",
            [("pkg.io.util", "g"), ("pkg.io.util", "g.__init__")],
        ),
        (
            "pkg/io/load",
            "from ..core import g\ng()\n",
            [("pkg.core", "g"), ("pkg.core", "g.__init__")],
        ),
        (
            "pkg/io/__init__",
            "from .util import g\ng()\n",
            [("pkg.io.util", "g"), ("pkg.io.util", "g.__init__")],
        ),
        ("pkg/io/load", "from ... import g\ng()\n", []),  # above the top
        ("a", "from . import g\ng()\n", []),  # top-level file has no package
    ],
)
def test_relative_imports(key, src, expected):
    call = doc_of(src, key=key).module.calls[0]
    assert [(r.module, r.qualname) for r in call.candidates] == expected


def test_empty_module_name_gives_no_own_candidates():
    d = doc_of("def g(): pass\nfrom m import h\ng()\nh()\n", key="__init__")
    assert [[(r.module, r.qualname) for r in c.candidates] for c in d.module.calls] == [
        [],
        [("m", "h"), ("m", "h.__init__")],
    ]


def test_skipped_function_case_is_really_skipped():
    src = "def helper(): pass\ndef f():\n    def helper(:\n        pass\n    helper()\n"
    r = PythonFrontend().parse(src.encode(), "t.py", ChartOptions(), PurePosixPath("pkg/mod"))
    assert [w.qualname for w in r.warnings] == ["f.helper"]
    assert "f" in [c.qualname for c in r.document.functions]


def test_every_parameter_kind_shadows():
    defs = "".join(f"def {n}(): pass\n" for n in "abcdef")
    src = defs + "def run(x, a=1, *b, c: int = 2, **d):\n    a(); b(); c(); d(); e()\n"
    src += "def s(*f: int):\n    f()\n"
    d = doc_of(src, key="m")
    assert [(c.text, c.candidates) for c in fn(d, "run").calls][:4] == [
        ("a", []),
        ("b", []),
        ("c", []),
        ("d", []),
    ]
    assert [r.qualname for r in fn(d, "run").calls[4].candidates] == ["e"]  # not a parameter
    assert fn(d, "s").calls[0].candidates == []


def test_names_are_nfkc_normalized_like_python():
    composed, decomposed = "caf\u00e9", "cafe\u0301"
    src = f"from m{decomposed} import {decomposed}\ndef f():\n    {composed}()\n"
    assert cands(src, "f", composed) == [
        (f"m{composed}", composed),
        (f"m{composed}", f"{composed}.__init__"),
    ]
    src = f"def {composed}(): pass\ndef f():\n    {decomposed}()\n"
    assert cands(src, "f", decomposed) == [("pkg.mod", composed)]
