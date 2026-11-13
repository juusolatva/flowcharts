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
