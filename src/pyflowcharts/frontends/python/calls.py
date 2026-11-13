"""Find the calls in Python code and the charts they may reach (static, best-effort)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from tree_sitter import Node

from pyflowcharts.cfg.model import CallSite
from pyflowcharts.frontends.python.discovery import Found
from pyflowcharts.frontends.python.source import Source, identifier
from pyflowcharts.ir import CallRef


@dataclass(frozen=True)
class ModuleInfo:
    """A file's dotted module name (``""`` when it has none) and the package that relative
    imports start from."""

    name: str
    package: tuple[str, ...]


def module_info(key: PurePosixPath) -> ModuleInfo:
    """``pkg/io/load`` → ``pkg.io.load`` in package ``pkg.io``; ``pkg/__init__`` → ``pkg``
    in package ``pkg``; a bare ``__init__`` has no module name."""
    package = key.parts[:-1]
    if key.name == "__init__":
        return ModuleInfo(".".join(package), package)
    return ModuleInfo(".".join(key.parts), package)


def call_roots(stmt: Node) -> list[Node]:
    """The subtrees whose calls the statement's node owns (the spec's ownership table)."""
    match stmt.type:
        case "if_statement" | "elif_clause" | "while_statement":
            return _fields(stmt, "condition")
        case "match_statement":
            body = stmt.child_by_field_name("body")
            cases = body.named_children if body is not None else []
            guards = [g for c in cases if (g := c.child_by_field_name("guard")) is not None]
            return stmt.children_by_field_name("subject") + guards
        case "for_statement":
            return _fields(stmt, "left", "right")
        case "with_statement":
            return [c for c in stmt.children if c.type == "with_clause"]
        case "except_clause" | "except_group_clause":
            return [c for c in stmt.children if c.type != "block"]
        case "decorated_definition":
            decorators = [c for c in stmt.children if c.type == "decorator"]
            definition = stmt.child_by_field_name("definition")
            return decorators + (call_roots(definition) if definition is not None else [])
        case "function_definition":
            return _fields(stmt, "type_parameters", "parameters", "return_type")
    return [stmt]


def _fields(node: Node, *names: str) -> list[Node]:
    return [c for name in names if (c := node.child_by_field_name(name)) is not None]


@dataclass(frozen=True)
class _Name:
    """``from module import name``: ``name`` may be a submodule or a name in ``module``."""

    module: str
    name: str


@dataclass(frozen=True)
class _Module:
    """``import x.y`` (``base`` ``x``, reachable ``x`` and ``x.y``) or ``import x.y as z``
    (``base`` and reachable ``x.y`` only)."""

    base: str
    reachable: frozenset[str]


type _Binding = _Name | _Module


@dataclass
class _Class:
    """A class body: its qualname and its methods (name → qualname, first wins), so that
    ``self.m`` in a redefined class names that class's ``m`` (``C.m@L{line}``)."""

    qualname: str
    methods: dict[str, str] = field(default_factory=dict)


@dataclass
class _Scope:
    """A module's or function's bindings: definitions (name → kind and qualname, first
    wins), imports (name → bindings in source order) and parameters (bound to nothing we
    can resolve, but they stop the lookup)."""

    definitions: dict[str, tuple[str, str]] = field(default_factory=dict)
    imports: dict[str, list[_Binding]] = field(default_factory=dict)
    parameters: frozenset[str] = frozenset()

    def binds(self, name: str) -> bool:
        return name in self.definitions or name in self.imports or name in self.parameters

    def define(self, name: str, kind: str, qualname: str) -> None:
        self.definitions.setdefault(name, (kind, qualname))

    def bind(self, name: str, binding: _Binding) -> None:
        self.imports.setdefault(name, []).append(binding)


class Resolver:
    """Finds a file's call sites and their candidate targets."""

    def __init__(self, root: Node, functions: list[Found], info: ModuleInfo, src: Source) -> None:
        self.info = info
        self.src = src
        self._found = {f.node.id: f for f in functions}
        self._module = _Scope()
        self._scopes: dict[int, _Scope] = {}  # by function node id
        self._classes: dict[int, _Class] = {}  # function node id → directly enclosing class
        self._index(root, "", self._module, None)

    def sites(self, roots: Sequence[Node], scope: Found | None) -> tuple[CallSite, ...]:
        """Every call in ``roots``, in pre-order, skipping function bodies. ``scope`` is the
        owning chart's function (``None`` for the module chart)."""
        out: list[CallSite] = []
        for root in roots:
            for call in _calls(root):
                callee = call.child_by_field_name("function")
                if callee is not None:
                    refs = dict.fromkeys(self._candidates(callee, scope))
                    out.append(CallSite(self.src.source_text(callee), tuple(refs)))
        return tuple(out)

    # -- tables ---------------------------------------------------------------

    def _index(self, node: Node, prefix: str, scope: _Scope, cls: _Class | None) -> None:
        for child in node.children:
            match child.type:
                case "function_definition":
                    name = _name(child)
                    found = self._found.get(child.id)
                    qualname = found.qualname if found is not None else prefix + name
                    scope.define(name, "def", qualname)
                    if cls is not None:
                        self._classes[child.id] = cls
                        cls.methods.setdefault(name, qualname)
                    inner = self._scopes[child.id] = _Scope(parameters=_parameters(child))
                    self._index(child, qualname + ".", inner, None)
                case "class_definition":
                    qualname = prefix + _name(child)
                    scope.define(_name(child), "class", qualname)
                    # A class body binds nothing visible to the functions inside it.
                    self._index(child, qualname + ".", _Scope(), _Class(qualname))
                case "import_statement":
                    self._import(child, scope)
                case "import_from_statement":
                    self._import_from(child, scope)
                case _:
                    self._index(child, prefix, scope, cls)

    def _import(self, stmt: Node, scope: _Scope) -> None:
        for name in stmt.children_by_field_name("name"):
            if name.type == "aliased_import":
                dotted, alias = name.child_by_field_name("name"), name.child_by_field_name("alias")
                if dotted is not None and alias is not None:
                    target = _text(dotted)
                    scope.bind(_text(alias), _Module(target, frozenset({target})))
            elif name.type == "dotted_name":
                parts = _text(name).split(".")
                reachable = frozenset(".".join(parts[:i]) for i in range(1, len(parts) + 1))
                scope.bind(parts[0], _Module(parts[0], reachable))

    def _import_from(self, stmt: Node, scope: _Scope) -> None:
        source = stmt.child_by_field_name("module_name")
        module = self._from_module(source) if source is not None else None
        if module is None:
            return
        for name in stmt.children_by_field_name("name"):
            original, bound = name, name
            if name.type == "aliased_import":
                original = name.child_by_field_name("name") or name
                bound = name.child_by_field_name("alias") or original
            scope.bind(_text(bound), _Name(module, _text(original)))

    def _from_module(self, source: Node) -> str | None:
        """The absolute module of ``from SOURCE import …``, or ``None`` above the top."""
        if source.type != "relative_import":
            return _text(source)
        prefix = next((c for c in source.children if c.type == "import_prefix"), None)
        dots = _text(prefix).count(".") if prefix is not None else 1
        package = self.info.package
        if dots > len(package):
            return None
        parts = list(package[: len(package) - dots + 1])
        rest = next((c for c in source.children if c.type == "dotted_name"), None)
        if rest is not None:
            parts.append(_text(rest))
        return ".".join(parts) or None

    # -- lookup ---------------------------------------------------------------

    def _chain(self, scope: Found | None) -> Iterator[_Scope]:
        while scope is not None:
            if (table := self._scopes.get(scope.node.id)) is not None:
                yield table
            scope = scope.enclosing
        yield self._module

    def _lookup(self, name: str, scope: Found | None) -> _Scope | None:
        return next((s for s in self._chain(scope) if s.binds(name)), None)

    def _own(self, qualname: str) -> list[CallRef]:
        return [CallRef(self.info.name, qualname)] if self.info.name else []

    def _candidates(self, callee: Node, scope: Found | None) -> list[CallRef]:
        parts = _parts(callee)
        if not parts:
            return []
        first, rest = parts[0], parts[1:]
        cls = self._classes.get(scope.node.id) if scope is not None else None
        if first in ("self", "cls") and len(parts) == 2 and cls is not None:
            return self._own(cls.methods.get(rest[0], f"{cls.qualname}.{rest[0]}"))
        table = self._lookup(first, scope)
        if table is None:
            return []
        out: list[CallRef] = []
        if (definition := table.definitions.get(first)) is not None:
            kind, qualname = definition
            if kind == "class":
                out += self._own(".".join([qualname, *rest]) if rest else f"{qualname}.__init__")
            elif not rest:
                out += self._own(qualname)
        return out + _import_candidates(table.imports.get(first, []), rest)


def _import_candidates(bindings: list[_Binding], rest: list[str]) -> list[CallRef]:
    """Candidates through the imports binding one name, in source order. Each import counts
    on its own (it may sit in one branch of a ``try`` or ``if``), but the ``import`` bindings
    of one package come together, the longest module first: with ``import a.b`` and
    ``import a.c``, ``a.c.f()`` must try ``a.c`` before ``a``."""
    packages: dict[str, list[_Module]] = {}
    for binding in bindings:
        if isinstance(binding, _Module):
            packages.setdefault(binding.base, []).append(binding)
    out: list[CallRef] = []
    for binding in bindings:
        match binding:
            case _Name():
                out += _through(binding, rest)
            case _Module(base) if base in packages:
                refs = [ref for module in packages.pop(base) for ref in _through(module, rest)]
                out += sorted(refs, key=lambda ref: -ref.module.count("."))
    return out


def _through(binding: _Binding, rest: list[str]) -> list[CallRef]:
    """Candidates for calling ``rest`` (attribute parts, possibly none) on an import."""
    match binding:
        case _Name(module, name) if rest:
            tail = ".".join(rest)
            return [CallRef(f"{module}.{name}", tail), CallRef(module, f"{name}.{tail}")]
        case _Name(module, name):
            return [CallRef(module, name), CallRef(module, f"{name}.__init__")]
        case _Module(base, reachable):
            full = base.split(".") + rest
            if ".".join(full) in reachable:
                return []  # the chain names a module, and modules are not called
            for k in range(len(full) - 1, 0, -1):  # proper prefixes, longest first
                if (prefix := ".".join(full[:k])) in reachable:
                    return [CallRef(prefix, ".".join(full[k:]))]
    return []


def _parts(callee: Node) -> list[str]:
    """``a.b.c`` as ``["a", "b", "c"]``; ``[]`` unless it is a chain of plain names."""
    match callee.type:
        case "identifier":
            return [_text(callee)]
        case "attribute":
            obj, attr = (
                callee.child_by_field_name("object"),
                callee.child_by_field_name("attribute"),
            )
            if obj is None or attr is None or not (head := _parts(obj)):
                return []
            return [*head, _text(attr)]
    return []


def _parameters(func: Node) -> frozenset[str]:
    params = func.child_by_field_name("parameters")
    names = (_parameter_name(p) for p in params.named_children) if params is not None else ()
    return frozenset(name for name in names if name)


def _parameter_name(param: Node) -> str:
    """``x``, ``x=1``, ``x: T``, ``x: T = 1``, ``*x``, ``**x`` and ``*x: T`` give ``x``;
    separators give ``""``."""
    if param.type == "identifier":
        return _text(param)
    if (name := param.child_by_field_name("name")) is not None:
        return _text(name)
    for child in param.named_children:
        if child.type in ("identifier", "list_splat_pattern", "dictionary_splat_pattern"):
            return _parameter_name(child)
    return ""


def _text(node: Node) -> str:
    return identifier(node)


def _name(node: Node) -> str:
    name = node.child_by_field_name("name")
    return _text(name) if name is not None else ""


def _calls(node: Node) -> Iterator[Node]:
    if node.type == "call":
        yield node
    skip_body = node.type == "function_definition"
    for i, child in enumerate(node.children):
        if skip_body and node.field_name_for_child(i) == "body":
            continue
        yield from _calls(child)
