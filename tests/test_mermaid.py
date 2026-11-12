from conftest import chart_of

from pyflowcharts.backends.mermaid import to_mermaid


def test_mermaid_structure():
    out = to_mermaid(chart_of("def f(x):\n    if x > 0:\n        return 1\n    g()\n"))
    lines = out.splitlines()
    assert lines[0] == "flowchart TD" and out.endswith("\n")
    assert '    n0(["def f(x)"])' in lines
    assert '    n2{"if x #62; 0"}' in lines
    assert '    n2 -->|"True"| n3' in lines
    assert "    n0 --> n2" in lines


def test_mermaid_escaping():
    out = to_mermaid(chart_of('def f():\n    print("it\'s")\n'))
    assert '["print(#34;it\'s#34;)"]' in out


def test_mermaid_escapes_literal_hash():  # literal "#34;" in source must stay literal
    out = to_mermaid(chart_of("def f():\n    print('#34; x#1')\n"))
    assert "[\"print('#35;34; x#35;1')\"]" in out


def test_mermaid_shapes():
    out = to_mermaid(chart_of("def f(xs):\n    for x in xs:\n        raise E(x)\n"))
    assert '{{"for x in xs"}}' in out and '>"raise E(x)"]' in out


def test_exception_edges_are_dashed():
    out = to_mermaid(chart_of("def f():\n    try:\n        a()\n    except E:\n        h()\n"))
    assert out.count('-.->|"exception"|') == 1 and '-->|"exception"|' not in out
