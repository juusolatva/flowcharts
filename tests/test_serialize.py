import copy
import json

import pytest

from pyflowcharts.ir import (
    MODULE_QUALNAME,
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
    assert data["schema_version"] == 2
    assert list(data) == ["source", "language", "functions", "module", "schema_version"]
    assert data["module"] is None
    assert list(data["functions"][0]) == [
        "qualname",
        "location",
        "nodes",
        "edges",
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
    assert set(json.loads(to_json(doc))["module"]) == {"qualname", "location", "nodes", "edges"}


def test_reads_version_1(doc):
    data = json.loads(to_json(doc))
    data["schema_version"] = 1
    del data["module"]
    old = from_json(json.dumps(data))
    assert (old.schema_version, old.module, old.functions) == (1, None, doc.functions)


def test_deterministic(doc):
    assert to_json(doc) == to_json(copy.deepcopy(doc))


def test_rejects_unknown_schema_version(doc):
    data = json.loads(to_json(doc))
    data["schema_version"] = 99
    with pytest.raises(UnsupportedSchemaVersionError, match=r"expected 1 or 2"):
        from_json(json.dumps(data))


def test_non_ascii_preserved(doc):
    assert "é" in to_json(doc)
