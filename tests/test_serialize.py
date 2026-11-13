import copy
import json

import pytest

from pyflowcharts.ir import (
    MODULE_QUALNAME,
    Call,
    CallRef,
    Chart,
    Document,
    Edge,
    FunctionChart,
    Node,
    NodeKind,
    Parameter,
    ParamKind,
    SourceLocation,
)
from pyflowcharts.serialize import UnsupportedSchemaVersionError, from_json, to_json


@pytest.fixture
def doc() -> Document:
    loc = SourceLocation(1, 0, 3, 14)
    chart = FunctionChart(
        qualname="f",
        name="f",
        is_async=False,
        parameters=[Parameter("x", "int", "1", ParamKind.POSITIONAL_OR_KEYWORD)],
        returns="None",
        location=loc,
        nodes=[
            Node("f#start", NodeKind.START, "def f(x: int=1) -> None", loc),
            Node("f#end", NodeKind.END, "end", None),
            Node("f#L2C4", NodeKind.PROCESS, "print('é')", SourceLocation(2, 4, 2, 14)),
        ],
        edges=[Edge("f#start", "f#L2C4"), Edge("f#L2C4", "f#end", "True")],
    )
    return Document(source="t.py", language="python", functions=[chart])


def test_round_trip(doc):
    assert from_json(to_json(doc)) == doc


def test_json_shape(doc):
    data = json.loads(to_json(doc))
    assert data["schema_version"] == 3
    assert list(data) == [
        "source",
        "language",
        "functions",
        "module_name",
        "module",
        "schema_version",
    ]
    assert data["module"] is None
    assert list(data["functions"][0]) == [
        "qualname",
        "location",
        "nodes",
        "edges",
        "calls",
        "name",
        "is_async",
        "parameters",
        "returns",
    ]
    assert data["functions"][0]["nodes"][0]["kind"] == "start"
    assert data["functions"][0]["parameters"][0]["kind"] == "positional_or_keyword"


def test_round_trip_with_module(doc):
    f = doc.functions[0]
    doc.module = Chart(qualname=MODULE_QUALNAME, location=f.location, nodes=f.nodes, edges=f.edges)
    assert from_json(to_json(doc)) == doc
    assert set(json.loads(to_json(doc))["module"]) == {
        "qualname",
        "location",
        "nodes",
        "edges",
        "calls",
    }


def test_round_trip_with_calls(doc):
    f = doc.functions[0]
    f.calls = [
        Call(
            node="f#L2C4",
            text="g",
            candidates=[CallRef("m", "g"), CallRef("m", "g.__init__")],
            target=CallRef("m", "g"),
        ),
        Call(node="f#L2C4", text="print", candidates=[], target=None),
    ]
    doc.module_name = "pkg.m"
    assert from_json(to_json(doc)) == doc
    assert json.loads(to_json(doc))["functions"][0]["calls"][0] == {
        "node": "f#L2C4",
        "text": "g",
        "candidates": [{"module": "m", "qualname": "g"}, {"module": "m", "qualname": "g.__init__"}],
        "target": {"module": "m", "qualname": "g"},
    }


@pytest.mark.parametrize("version", [1, 2])
def test_reads_older_versions(doc, version):
    data = json.loads(to_json(doc))
    data["schema_version"] = version
    del data["module_name"]
    for chart in data["functions"]:
        del chart["calls"]
    if version == 1:
        del data["module"]
    old = from_json(json.dumps(data))
    assert (old.schema_version, old.module_name, old.functions[0].calls) == (version, "", [])
    assert old.module is None
    assert old.functions == doc.functions


def test_reads_version_2_module_chart_without_calls(doc):
    f = doc.functions[0]
    doc.module = Chart(qualname=MODULE_QUALNAME, location=f.location, nodes=f.nodes, edges=f.edges)
    data = json.loads(to_json(doc))
    data["schema_version"] = 2
    del data["module_name"]
    del data["module"]["calls"]
    for chart in data["functions"]:
        del chart["calls"]
    assert from_json(json.dumps(data)).module.calls == []


def test_deterministic(doc):
    assert to_json(doc) == to_json(copy.deepcopy(doc))


def test_rejects_unknown_schema_version(doc):
    data = json.loads(to_json(doc))
    data["schema_version"] = 99
    with pytest.raises(UnsupportedSchemaVersionError, match=r"expected 1, 2 or 3"):
        from_json(json.dumps(data))


def test_non_ascii_preserved(doc):
    assert "é" in to_json(doc)


def test_document_positional_fields_keep_their_order():
    doc = Document("t.py", "python", [], None, 2)
    assert (doc.module, doc.schema_version, doc.module_name) == (None, 2, "")
