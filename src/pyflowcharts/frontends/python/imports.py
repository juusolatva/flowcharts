"""Import bindings in a scope, and the call targets a call through them may reach."""

from __future__ import annotations

from dataclasses import dataclass, field

from pyflowcharts.ir import CallRef


@dataclass(frozen=True)
class FromImport:
    """``from module import name``: ``name`` may be a submodule or a name in ``module``."""

    module: str
    name: str


@dataclass(frozen=True)
class ModuleImport:
    """``import x.y`` (``base`` ``x``, reachable ``x`` and ``x.y``) or ``import x.y as z``
    (``base`` and reachable ``x.y`` only). ``certain`` when the import always runs: it sits
    directly in a module's or function's body, not in a ``try``, ``if`` or other block."""

    base: str
    reachable: frozenset[str]
    certain: bool = False


type Binding = FromImport | ModuleImport


@dataclass
class Class:
    """A class body: its qualname and its methods (name → qualname, first wins), so that
    ``self.m`` in a redefined class names that class's ``m`` (``C.m@L{line}``)."""

    qualname: str
    methods: dict[str, str] = field(default_factory=dict)


@dataclass
class Scope:
    """A module's or function's bindings: definitions (name → kind and qualname, first
    wins), imports (name → bindings in source order) and parameters (bound to nothing we
    can resolve, but they stop the lookup)."""

    definitions: dict[str, tuple[str, str]] = field(default_factory=dict)
    imports: dict[str, list[Binding]] = field(default_factory=dict)
    parameters: frozenset[str] = frozenset()

    def binds(self, name: str) -> bool:
        return name in self.definitions or name in self.imports or name in self.parameters

    def define(self, name: str, kind: str, qualname: str) -> None:
        self.definitions.setdefault(name, (kind, qualname))

    def bind(self, name: str, binding: Binding) -> None:
        self.imports.setdefault(name, []).append(binding)


def import_candidates(bindings: list[Binding], rest: list[str]) -> list[CallRef]:
    """Candidates through the imports binding one name, in source order. Each import counts
    on its own (it may sit in one branch of a ``try`` or ``if``), but the ``import`` bindings
    of one package come together, the longest module first: with ``import a.b`` and
    ``import a.c``, ``a.c.f()`` must try ``a.c`` before ``a``."""
    packages: dict[str, list[ModuleImport]] = {}
    for binding in bindings:
        if isinstance(binding, ModuleImport):
            packages.setdefault(binding.base, []).append(binding)
    out: list[CallRef] = []
    for binding in bindings:
        match binding:
            case FromImport():
                out += _through(binding, rest)
            case ModuleImport(base) if base in packages:
                out += _package_candidates(packages.pop(base), rest)
    return out


def _package_candidates(modules: list[ModuleImport], rest: list[str]) -> list[CallRef]:
    """Candidates through the ``import`` bindings of one package, the longest module first.
    A module reachable through an import that always runs is certainly a module, so shorter
    fallbacks through it are dropped (none at all when the whole chain is a module)."""
    full = modules[0].base.split(".") + rest
    certain = {path for module in modules if module.certain for path in module.reachable}
    known = next((k for k in range(len(full), 0, -1) if ".".join(full[:k]) in certain), 0)
    if known == len(full):
        return []  # the chain certainly names a module, and modules are not called
    refs = [ref for module in modules for ref in _through(module, rest)]
    refs = [ref for ref in refs if ref.module.count(".") + 1 >= known]
    return sorted(refs, key=lambda ref: -ref.module.count("."))


def _through(binding: Binding, rest: list[str]) -> list[CallRef]:
    """Candidates for calling ``rest`` (attribute parts, possibly none) on an import."""
    match binding:
        case FromImport(module, name) if rest:
            # ``name`` may be a module or a package with submodules below it; every split,
            # the longest module first, then ``name`` as an attribute of ``module``.
            base = f"{module}.{name}"
            splits = [
                CallRef(".".join([base, *rest[:k]]), ".".join(rest[k:]))
                for k in range(len(rest) - 1, -1, -1)
            ]
            return [*splits, CallRef(module, ".".join([name, *rest]))]
        case FromImport(module, name):
            return [CallRef(module, name), CallRef(module, f"{name}.__init__")]
        case ModuleImport(base, reachable):
            full = base.split(".") + rest
            if ".".join(full) in reachable:
                return []  # the chain names a module, and modules are not called
            for k in range(len(full) - 1, 0, -1):  # proper prefixes, longest first
                if (prefix := ".".join(full[:k])) in reachable:
                    return [CallRef(prefix, ".".join(full[k:]))]
    return []
