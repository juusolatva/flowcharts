from dataclasses import replace
from pathlib import PurePosixPath

from pyflowcharts.calls import link
from pyflowcharts.frontends.python import PythonFrontend
from pyflowcharts.ir import Call, CallRef, ChartOptions


def parse(src, key):
    return (
        PythonFrontend()
        .parse(src.encode(), f"{key}.py", ChartOptions(), PurePosixPath(key))
        .document
    )


def targets(doc, qualname=None):
    if qualname is None:
        chart = doc.module
    else:
        chart = next(c for c in doc.functions if c.qualname == qualname)
    return [(c.text, c.target and (c.target.module, c.target.qualname)) for c in chart.calls]


def test_first_existing_candidate_wins_across_documents():
    a = parse("from p import x\ndef f():\n    x.g()\n", "app")
    p = parse("def unused(): pass\n", "p/__init__")
    px = parse("def g(): pass\n", "p/x")
    linked = link([a, p, px])
    assert targets(linked[0], "f") == [("x.g", ("p.x", "g"))]


def test_falls_back_to_later_candidate_and_none():
    a = parse("from p import x\ndef f():\n    x.g()\n    print()\n", "app")
    p = parse("class x:\n    def g(): pass\n", "p/__init__")
    assert targets(link([a, p])[0], "f") == [("x.g", ("p", "x.g")), ("print", None)]


def test_module_chart_calls_are_linked_and_never_targets():
    d = parse("def main(): pass\nif __name__ == '__main__':\n    main()\n", "app")
    assert targets(link([d])[0]) == [("main", ("app", "main"))]
    f = d.functions[0]
    probe = Call(
        node=f"{f.qualname}#start", text="x", candidates=[CallRef("app", "<module>")], target=None
    )
    d2 = replace(d, functions=[replace(f, calls=[probe])])
    assert link([d2])[0].functions[0].calls[0].target is None


def test_independent_of_document_order():
    a = parse("from b import g\ndef f():\n    g()\n", "a")
    b = parse("def g(): pass\n", "b")
    assert link([a, b])[0] == link([b, a])[1]


def test_empty_and_duplicate_module_names_are_not_indexed():
    caller = parse("from a.b import g\ndef f():\n    g()\n    h()\n", "c")
    f = caller.functions[0]
    # no resolution rule produces module "", so build that candidate by hand
    h_call = replace(f.calls[1], candidates=[CallRef("", "h")])
    caller = replace(caller, functions=[replace(f, calls=[f.calls[0], h_call])])
    one = parse("def g(): pass\n", "a.b")  # module name "a.b"
    two = parse("def g(): pass\n", "a/b")  # module name "a.b" too
    init = parse("def h(): pass\n", "__init__")  # module name ""
    assert targets(link([caller, one, two, init])[0], "f") == [("g", None), ("h", None)]


def test_input_is_not_mutated():
    a = parse("def f():\n    f()\n", "a")
    link([a])
    assert a.functions[0].calls[0].target is None
